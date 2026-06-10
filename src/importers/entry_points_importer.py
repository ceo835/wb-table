from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import FactEntryPointDay
from src.db.session import session_scope, upsert_rows
from src.importers.common import (
    ParsedImportResult,
    cell_to_decimal,
    cell_to_int,
    cell_to_text,
    close_workbook,
    iter_data_rows,
    json_ready_preview,
    load_workbook_readonly,
    normalize_header,
    resolve_import_date,
)


ENTRY_POINT_REQUIRED_COLUMNS = (
    "Раздел",
    "Точка входа",
    "Артикул WB",
    "Артикул продавца",
    "Бренд",
    "Название",
    "Предмет",
    "Показы",
    "Переходы в карточку",
    "CTR",
    "Добавления в корзину",
    "Конверсия в корзину",
    "Заказы",
    "Конверсия в заказ",
)
ENTRY_POINT_CONFLICT_COLUMNS = ("date", "nm_id", "section", "entry_point")
ENTRY_POINT_TARGET_TABLE = "fact_entry_point_day"
ENTRY_POINT_SOURCE_STATUS = "CSV_EXPORT"

ENTRY_POINT_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "Раздел": ("Раздел",),
    "Точка входа": ("Точка входа",),
    "Артикул WB": ("Артикул WB", "Артикул ВБ"),
    "Артикул продавца": ("Артикул продавца",),
    "Бренд": ("Бренд",),
    "Название": ("Название",),
    "Предмет": ("Предмет",),
    "Показы": ("Показы",),
    "Переходы в карточку": ("Переходы в карточку",),
    "CTR": ("CTR",),
    "Добавления в корзину": ("Добавления в корзину",),
    "Конверсия в корзину": ("Конверсия в корзину",),
    "Заказы": ("Заказы",),
    "Конверсия в заказ": ("Конверсия в заказ",),
}


def _normalize_key(value: Any) -> str:
    return normalize_header(value).casefold()


def _resolve_header_index(headers: tuple[str, ...]) -> tuple[dict[str, int], tuple[str, ...], int]:
    by_normalized_header = {
        _normalize_key(header): index
        for index, header in enumerate(headers)
        if normalize_header(header)
    }
    resolved: dict[str, int] = {}
    missing: list[str] = []
    for canonical, aliases in ENTRY_POINT_HEADER_ALIASES.items():
        matched_index = None
        for alias in aliases:
            matched_index = by_normalized_header.get(_normalize_key(alias))
            if matched_index is not None:
                break
        if matched_index is None:
            missing.append(canonical)
            continue
        resolved[canonical] = matched_index
    return resolved, tuple(missing), len(resolved)


def _select_entry_point_sheet(workbook) -> tuple[str | None, int | None, dict[str, int], tuple[str, ...]]:
    preferred_titles = (
        "детализация по артикулам",
        "отчет",
    )
    best_candidate: tuple[int, int, int, str, dict[str, int], tuple[str, ...]] | None = None

    for sheet in workbook.worksheets:
        title_key = _normalize_key(sheet.title)
        priority = next((index for index, value in enumerate(preferred_titles) if value in title_key), len(preferred_titles))
        for row_index in range(1, min(sheet.max_row, 6) + 1):
            row_iter = sheet.iter_rows(min_row=row_index, max_row=row_index)
            row_cells = next(row_iter, None)
            if row_cells is None:
                continue
            headers = tuple(cell.value for cell in row_cells)
            resolved, missing, overlap = _resolve_header_index(tuple(normalize_header(header) for header in headers))
            candidate = (priority, -overlap, row_index, sheet.title, resolved, missing)
            if best_candidate is None or candidate < best_candidate:
                best_candidate = candidate
            if not missing:
                return sheet.title, row_index, resolved, missing

    if best_candidate is None:
        return None, None, {}, ENTRY_POINT_REQUIRED_COLUMNS

    _, _, row_index, sheet_title, resolved, missing = best_candidate
    return sheet_title, row_index, resolved, missing


def parse_entry_points_xlsx(file_path: str, explicit_date: date | None = None) -> ParsedImportResult:
    workbook = load_workbook_readonly(file_path)
    try:
        detected_date = resolve_import_date(file_path, explicit_date=explicit_date, workbook=workbook)
        sheet_name, header_row_index, header_index, missing_required_columns = _select_entry_point_sheet(workbook)
        if sheet_name is None or header_row_index is None:
            return ParsedImportResult(
                file_path=Path(file_path),
                detected_date=detected_date,
                sheet_name=None,
                rows_read=0,
                rows_normalized=(),
                missing_required_columns=missing_required_columns,
            )

        sheet = workbook[sheet_name]
        normalized_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        rows_read = 0

        for row_cells in iter_data_rows(sheet, header_row_index):
            row_map = {
                header: row_cells[index]
                for header, index in header_index.items()
                if index < len(row_cells)
            }
            if not any(cell.value not in (None, "") for cell in row_map.values()):
                continue

            rows_read += 1
            nm_id = cell_to_int(row_map.get("Артикул WB"))
            section = cell_to_text(row_map.get("Раздел"))
            entry_point = cell_to_text(row_map.get("Точка входа"))
            normalized = {
                "date": detected_date,
                "nm_id": nm_id,
                "section": section,
                "entry_point": entry_point,
                "supplier_article": cell_to_text(row_map.get("Артикул продавца")),
                "brand": cell_to_text(row_map.get("Бренд")),
                "title": cell_to_text(row_map.get("Название")),
                "subject": cell_to_text(row_map.get("Предмет")),
                "impressions": cell_to_decimal(row_map.get("Показы")),
                "card_clicks": cell_to_decimal(row_map.get("Переходы в карточку")),
                "ctr": cell_to_decimal(row_map.get("CTR"), percent_mode=True),
                "cart_count": cell_to_decimal(row_map.get("Добавления в корзину")),
                "add_to_cart_conversion": cell_to_decimal(row_map.get("Конверсия в корзину"), percent_mode=True),
                "order_count": cell_to_decimal(row_map.get("Заказы")),
                "order_conversion": cell_to_decimal(row_map.get("Конверсия в заказ"), percent_mode=True),
                "metric_name": None,
                "metric_value": None,
                "orders_qty": None,
                "revenue": None,
                "source_file_name": file_path,
                "data_status": "REAL_FILE",
                "source_status": ENTRY_POINT_SOURCE_STATUS,
                "loaded_at": None,
            }
            if detected_date is None or nm_id is None or not section or not entry_point:
                skipped_rows.append(
                    {
                        "nm_id": nm_id,
                        "section": section,
                        "entry_point": entry_point,
                    }
                )
                continue
            normalized_rows.append(normalized)

        return ParsedImportResult(
            file_path=Path(file_path),
            detected_date=detected_date,
            sheet_name=sheet_name,
            rows_read=rows_read,
            rows_normalized=tuple(normalized_rows),
            missing_required_columns=missing_required_columns,
            skipped_rows_count=len(skipped_rows),
            skipped_rows_preview=tuple(skipped_rows[:5]),
        )
    finally:
        close_workbook(workbook)


def prepare_entry_point_upsert_rows(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    prepared: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(column_name) for column_name in ENTRY_POINT_CONFLICT_COLUMNS)
        if any(value in (None, "") for value in key):
            continue
        prepared_row = dict(row)
        if prepared_row.get("loaded_at") is None:
            prepared_row["loaded_at"] = datetime.now(timezone.utc)
        prepared[key] = prepared_row
    return list(prepared.values())


def upsert_entry_point_rows(session: Session, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> int:
    prepared_rows = prepare_entry_point_upsert_rows(rows)
    if not prepared_rows:
        return 0
    upsert_rows(
        session=session,
        model=FactEntryPointDay,
        rows=prepared_rows,
        conflict_columns=ENTRY_POINT_CONFLICT_COLUMNS,
    )
    return len(prepared_rows)


def count_entry_point_rows_in_db(session: Session, detected_date: date) -> int:
    stmt = (
        select(func.count())
        .select_from(FactEntryPointDay)
        .where(FactEntryPointDay.date == detected_date)
        .where(FactEntryPointDay.source_status == ENTRY_POINT_SOURCE_STATUS)
    )
    return int(session.execute(stmt).scalar_one())


def count_entry_point_duplicates(session: Session, detected_date: date) -> int:
    stmt = (
        select(
            FactEntryPointDay.date,
            FactEntryPointDay.nm_id,
            FactEntryPointDay.section,
            FactEntryPointDay.entry_point,
        )
        .where(FactEntryPointDay.date == detected_date)
        .where(FactEntryPointDay.source_status == ENTRY_POINT_SOURCE_STATUS)
        .group_by(
            FactEntryPointDay.date,
            FactEntryPointDay.nm_id,
            FactEntryPointDay.section,
            FactEntryPointDay.entry_point,
        )
        .having(func.count() > 1)
    )
    return len(session.execute(stmt).all())


def source_status_counts_for_entry_points(session: Session, detected_date: date) -> dict[str, int]:
    stmt = (
        select(FactEntryPointDay.source_status, func.count())
        .where(FactEntryPointDay.date == detected_date)
        .group_by(FactEntryPointDay.source_status)
    )
    return {str(source_status or ""): int(count) for source_status, count in session.execute(stmt).all()}


def build_entry_point_summary(parsed: ParsedImportResult) -> dict[str, Any]:
    return {
        "target_table": ENTRY_POINT_TARGET_TABLE,
        "source_status": ENTRY_POINT_SOURCE_STATUS,
        "detected_date": parsed.detected_date.isoformat() if parsed.detected_date else None,
        "sheet_name": parsed.sheet_name,
        "rows_read": parsed.rows_read,
        "rows_normalized": len(parsed.rows_normalized),
        "missing_required_columns": list(parsed.missing_required_columns),
        "skipped_rows_count": parsed.skipped_rows_count,
        "preview_rows": json_ready_preview(parsed.rows_normalized),
        "skipped_rows_preview": list(parsed.skipped_rows_preview),
    }


def import_entry_points_xlsx(file_path: str, explicit_date: date | None = None, *, apply: bool = False) -> dict[str, Any]:
    parsed = parse_entry_points_xlsx(file_path, explicit_date=explicit_date)
    summary = build_entry_point_summary(parsed)
    if not apply or parsed.detected_date is None or parsed.missing_required_columns:
        return summary

    with session_scope() as session:
        rows_upserted = upsert_entry_point_rows(session, parsed.rows_normalized)
        rows_in_db_for_date = count_entry_point_rows_in_db(session, parsed.detected_date)
        duplicate_keys = count_entry_point_duplicates(session, parsed.detected_date)
        source_status_counts = source_status_counts_for_entry_points(session, parsed.detected_date)

    summary.update(
        {
            "rows_upserted": rows_upserted,
            "rows_in_db_for_date": rows_in_db_for_date,
            "duplicate_keys": duplicate_keys,
            "source_status_counts": source_status_counts,
        }
    )
    return summary
