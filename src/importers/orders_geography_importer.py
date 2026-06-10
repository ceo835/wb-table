from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import FactLocalizationRegionDay
from src.db.session import session_scope, upsert_rows
from src.importers.common import (
    ParsedImportResult,
    build_header_index,
    cell_to_decimal,
    cell_to_int,
    cell_to_text,
    close_workbook,
    iter_data_rows,
    json_ready_preview,
    load_workbook_readonly,
    resolve_import_date,
    select_sheet_by_required_columns,
)


ORDERS_GEOGRAPHY_REQUIRED_COLUMNS = (
    "Артикул продавца",
    "Название",
    "Артикул WB",
    "Предмет",
    "Бренд",
    "Регион",
    "Время доставки",
    "Итого заказов, шт",
    "Итого заказов по товарам локально, шт",
    "Итого заказов по товарам не локально, шт",
    "Итого заказы по товарам не локально, %",
    "Заказы со склада WB локально, шт",
    "Заказы со склада WB не локально, шт",
    "Заказы со склада WB не локально, %",
    "Заказы Маркетплейс локально, шт",
    "Заказы Маркетплейс не локально, шт",
    "Заказы Маркетплейс не локально, %",
    "Остатки склад WB, шт",
    "Остатки МП, шт",
)
ORDERS_GEOGRAPHY_CONFLICT_COLUMNS = ("period_start", "period_end", "nm_id", "region")
ORDERS_GEOGRAPHY_TARGET_TABLE = "fact_localization_region_day"
ORDERS_GEOGRAPHY_SOURCE_STATUS = "CSV_EXPORT"


def parse_orders_geography_xlsx(file_path: str, explicit_date: date | None = None) -> ParsedImportResult:
    workbook = load_workbook_readonly(file_path)
    try:
        detected_date = resolve_import_date(file_path, explicit_date=explicit_date, workbook=workbook)
        selection = select_sheet_by_required_columns(
            workbook,
            ORDERS_GEOGRAPHY_REQUIRED_COLUMNS,
            preferred_sheet_name="Детальные данные",
        )
        if selection.sheet_name is None or selection.header_row_index is None:
            return ParsedImportResult(
                file_path=Path(file_path),
                detected_date=detected_date,
                sheet_name=None,
                rows_read=0,
                rows_normalized=(),
                missing_required_columns=selection.missing_required_columns,
            )

        sheet = workbook[selection.sheet_name]
        header_index = build_header_index(selection.headers)
        normalized_rows: list[dict[str, Any]] = []
        skipped_rows: list[dict[str, Any]] = []
        rows_read = 0

        for row_cells in iter_data_rows(sheet, selection.header_row_index):
            row_map = {
                header: row_cells[index]
                for header, index in header_index.items()
                if index < len(row_cells)
            }
            if not any(cell.value not in (None, "") for cell in row_map.values()):
                continue

            rows_read += 1
            nm_id = cell_to_int(row_map.get("Артикул WB"))
            region = cell_to_text(row_map.get("Регион"))
            delivery_time_raw = cell_to_text(row_map.get("Время доставки"))
            normalized = {
                "period_start": detected_date,
                "period_end": detected_date,
                "date": detected_date,
                "nm_id": nm_id,
                "supplier_article": cell_to_text(row_map.get("Артикул продавца")),
                "title": cell_to_text(row_map.get("Название")),
                "subject": cell_to_text(row_map.get("Предмет")),
                "brand": cell_to_text(row_map.get("Бренд")),
                "region": region,
                "delivery_time": cell_to_decimal(row_map.get("Время доставки")),
                "delivery_time_text": delivery_time_raw,
                "orders_total_qty": cell_to_decimal(row_map.get("Итого заказов, шт")),
                "orders_local_qty": cell_to_decimal(row_map.get("Итого заказов по товарам локально, шт")),
                "orders_nonlocal_qty": cell_to_decimal(row_map.get("Итого заказов по товарам не локально, шт")),
                "orders_nonlocal_percent": cell_to_decimal(
                    row_map.get("Итого заказы по товарам не локально, %"),
                    percent_mode=True,
                ),
                "wb_stock_orders_local_qty": cell_to_decimal(row_map.get("Заказы со склада WB локально, шт")),
                "wb_stock_orders_nonlocal_qty": cell_to_decimal(row_map.get("Заказы со склада WB не локально, шт")),
                "wb_stock_orders_nonlocal_percent": cell_to_decimal(
                    row_map.get("Заказы со склада WB не локально, %"),
                    percent_mode=True,
                ),
                "mp_orders_local_qty": cell_to_decimal(row_map.get("Заказы Маркетплейс локально, шт")),
                "mp_orders_nonlocal_qty": cell_to_decimal(row_map.get("Заказы Маркетплейс не локально, шт")),
                "mp_orders_nonlocal_percent": cell_to_decimal(
                    row_map.get("Заказы Маркетплейс не локально, %"),
                    percent_mode=True,
                ),
                "wb_stock_qty": cell_to_decimal(row_map.get("Остатки склад WB, шт")),
                "mp_stock_qty": cell_to_decimal(row_map.get("Остатки МП, шт")),
                "sale_item_qty": None,
                "sale_amount": None,
                "country": None,
                "city": None,
                "local_orders_percent": None,
                "nonlocal_orders_percent": None,
                "data_status": "REAL_FILE",
                "source_status": ORDERS_GEOGRAPHY_SOURCE_STATUS,
                "loaded_at": None,
            }
            if detected_date is None or nm_id is None or not region:
                skipped_rows.append(
                    {
                        "nm_id": nm_id,
                        "region": region,
                        "supplier_article": normalized["supplier_article"],
                    }
                )
                continue
            normalized_rows.append(normalized)

        return ParsedImportResult(
            file_path=Path(file_path),
            detected_date=detected_date,
            sheet_name=selection.sheet_name,
            rows_read=rows_read,
            rows_normalized=tuple(normalized_rows),
            missing_required_columns=selection.missing_required_columns,
            skipped_rows_count=len(skipped_rows),
            skipped_rows_preview=tuple(skipped_rows[:5]),
        )
    finally:
        close_workbook(workbook)


def prepare_orders_geography_upsert_rows(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    prepared: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(column_name) for column_name in ORDERS_GEOGRAPHY_CONFLICT_COLUMNS)
        if any(value in (None, "") for value in key):
            continue
        prepared_row = dict(row)
        if prepared_row.get("loaded_at") is None:
            prepared_row["loaded_at"] = datetime.now(timezone.utc)
        prepared[key] = prepared_row
    return list(prepared.values())


def upsert_orders_geography_rows(session: Session, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> int:
    prepared_rows = prepare_orders_geography_upsert_rows(rows)
    if not prepared_rows:
        return 0
    upsert_rows(
        session=session,
        model=FactLocalizationRegionDay,
        rows=prepared_rows,
        conflict_columns=ORDERS_GEOGRAPHY_CONFLICT_COLUMNS,
    )
    return len(prepared_rows)


def count_orders_geography_rows_in_db(session: Session, detected_date: date) -> int:
    stmt = (
        select(func.count())
        .select_from(FactLocalizationRegionDay)
        .where(FactLocalizationRegionDay.period_start == detected_date)
        .where(FactLocalizationRegionDay.period_end == detected_date)
        .where(FactLocalizationRegionDay.source_status == ORDERS_GEOGRAPHY_SOURCE_STATUS)
    )
    return int(session.execute(stmt).scalar_one())


def count_orders_geography_duplicates(session: Session, detected_date: date) -> int:
    stmt = (
        select(
            FactLocalizationRegionDay.period_start,
            FactLocalizationRegionDay.period_end,
            FactLocalizationRegionDay.nm_id,
            FactLocalizationRegionDay.region,
        )
        .where(FactLocalizationRegionDay.period_start == detected_date)
        .where(FactLocalizationRegionDay.period_end == detected_date)
        .where(FactLocalizationRegionDay.source_status == ORDERS_GEOGRAPHY_SOURCE_STATUS)
        .group_by(
            FactLocalizationRegionDay.period_start,
            FactLocalizationRegionDay.period_end,
            FactLocalizationRegionDay.nm_id,
            FactLocalizationRegionDay.region,
        )
        .having(func.count() > 1)
    )
    return len(session.execute(stmt).all())


def source_status_counts_for_orders_geography(session: Session, detected_date: date) -> dict[str, int]:
    stmt = (
        select(FactLocalizationRegionDay.source_status, func.count())
        .where(FactLocalizationRegionDay.period_start == detected_date)
        .where(FactLocalizationRegionDay.period_end == detected_date)
        .group_by(FactLocalizationRegionDay.source_status)
    )
    return {str(source_status or ""): int(count) for source_status, count in session.execute(stmt).all()}


def build_orders_geography_summary(parsed: ParsedImportResult) -> dict[str, Any]:
    return {
        "target_table": ORDERS_GEOGRAPHY_TARGET_TABLE,
        "source_status": ORDERS_GEOGRAPHY_SOURCE_STATUS,
        "detected_date": parsed.detected_date.isoformat() if parsed.detected_date else None,
        "sheet_name": parsed.sheet_name,
        "rows_read": parsed.rows_read,
        "rows_normalized": len(parsed.rows_normalized),
        "missing_required_columns": list(parsed.missing_required_columns),
        "skipped_rows_count": parsed.skipped_rows_count,
        "preview_rows": json_ready_preview(parsed.rows_normalized),
        "skipped_rows_preview": list(parsed.skipped_rows_preview),
    }


def import_orders_geography_xlsx(file_path: str, explicit_date: date | None = None, *, apply: bool = False) -> dict[str, Any]:
    parsed = parse_orders_geography_xlsx(file_path, explicit_date=explicit_date)
    summary = build_orders_geography_summary(parsed)
    if not apply or parsed.detected_date is None or parsed.missing_required_columns:
        return summary

    with session_scope() as session:
        rows_upserted = upsert_orders_geography_rows(session, parsed.rows_normalized)
        rows_in_db_for_date = count_orders_geography_rows_in_db(session, parsed.detected_date)
        duplicate_keys = count_orders_geography_duplicates(session, parsed.detected_date)
        source_status_counts = source_status_counts_for_orders_geography(session, parsed.detected_date)

    summary.update(
        {
            "rows_upserted": rows_upserted,
            "rows_in_db_for_date": rows_in_db_for_date,
            "duplicate_keys": duplicate_keys,
            "source_status_counts": source_status_counts,
        }
    )
    return summary
