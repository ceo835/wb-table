from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Optional, Sequence

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from src.clients.google_sheets_client import GoogleSheetsClient
from src.config.settings import settings
from src.db.models import FactIvanStockSheetDay
from src.db.session import session_scope, upsert_rows
from src.utils.logger import get_logger

logger = get_logger("ivan_stock_sheet_loader")

STOCK_SHEET_NAME = "Остатки"
DATE_REGEX = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
SIZE_LABEL_REGEX = re.compile(r"\u0420\u0430\u0437\u043c\u0435\u0440:\s*(.*?)(?=\s*\u0426\u0432\u0435\u0442:|,\s*$|$)")
COLOR_LABEL_REGEX = re.compile(r"\u0426\u0432\u0435\u0442:\s*(.*?)(?=\s*\u0420\u0430\u0437\u043c\u0435\u0440:|,\s*$|$)")
BARCODE_TAIL_REGEX = re.compile(r",\s*(\d+)\s*$")


def _parse_tail_size_without_label(text: str) -> str:
    if not text:
        return ""

    tail_patterns = (
        r"([0-9]+XL\s*\([0-9]+(?:-[0-9]+)?\))$",
        r"([A-Za-z\u0410-\u042f\u0430-\u044f]{1,4}\s*\([0-9]+(?:-[0-9]+)?\))$",
        r"([0-9]+(?:/[0-9]+)?-[0-9]+)$",
        r"([0-9]+/[0-9]+)$",
    )
    for pattern in tail_patterns:
        match = re.search(pattern, text.strip())
        if match:
            return match.group(1).strip()
    return ""


def parse_row_nomenclature(text: str) -> tuple[str, Optional[str], str]:
    if not text:
        return "", None, ""

    text_str = str(text).strip()
    barcode = ""
    barcode_match = BARCODE_TAIL_REGEX.search(text_str)
    if barcode_match:
        barcode = barcode_match.group(1)
        main_part = text_str[: barcode_match.start()].strip()
    else:
        main_part = text_str.rstrip(",").strip()

    size_name = ""
    size_match = SIZE_LABEL_REGEX.search(main_part)
    if size_match:
        size_name = size_match.group(1).strip()
    else:
        size_name = _parse_tail_size_without_label(main_part)

    color_name = None
    color_match = COLOR_LABEL_REGEX.search(main_part)
    if color_match:
        color_name = color_match.group(1).strip()

    return size_name, color_name, barcode


def parse_quantity(val: Any) -> Optional[Decimal]:
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str:
        return None
    val_str = val_str.replace(" ", "").replace("\xa0", "")
    val_str = val_str.replace(",", ".")
    try:
        return Decimal(val_str)
    except Exception:
        return None


def normalize_ivan_stock_quantity(val: Any) -> Decimal:
    parsed = val if isinstance(val, Decimal) else parse_quantity(val)
    if parsed is None:
        return Decimal("0")
    return parsed if parsed >= 0 else Decimal("0")


def resolve_latest_ivan_stock_date(session: Session, target_date: Optional[date]) -> Optional[date]:
    stmt = select(func.max(FactIvanStockSheetDay.stock_date))
    if target_date is not None:
        stmt = stmt.where(FactIvanStockSheetDay.stock_date <= target_date)
    return session.execute(stmt).scalar()


def prune_legacy_blank_size_rows(session: Session, stock_date: date) -> int:
    result = session.execute(
        text(
            """
            delete from fact_ivan_stock_sheet_day stale
            using fact_ivan_stock_sheet_day actual
            where stale.stock_date = :stock_date
              and actual.stock_date = stale.stock_date
              and actual.nm_id = stale.nm_id
              and coalesce(actual.barcode, '') = coalesce(stale.barcode, '')
              and coalesce(actual.barcode, '') <> ''
              and coalesce(stale.size_name, '') = ''
              and coalesce(actual.size_name, '') <> ''
              and stale.id <> actual.id
            """
        ),
        {"stock_date": stock_date},
    )
    return max(result.rowcount or 0, 0)


def _parse_sheet_date(value: Any) -> Optional[date]:
    if not value:
        return None
    match = DATE_REGEX.search(str(value).strip())
    if not match:
        return None
    day_num, month_num, year_num = map(int, match.group(0).split("."))
    return date(year_num, month_num, day_num)


def _is_stock_header_row(row: Sequence[Any]) -> bool:
    row_lower = [str(cell).strip().lower() for cell in row if cell]
    return any("\u043d\u043e\u043c\u0435\u043d\u043a\u043b\u0430\u0442\u0443\u0440" in cell or "\u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432" in cell for cell in row_lower)


def _resolve_latest_stock_sheet_block(all_values: Sequence[Sequence[Any]]) -> tuple[date, int, int]:
    date_rows: list[tuple[int, date]] = []
    for idx, row in enumerate(all_values):
        row_date = next((_parse_sheet_date(cell) for cell in row if _parse_sheet_date(cell) is not None), None)
        if row_date is not None:
            date_rows.append((idx, row_date))

    if not date_rows:
        raise RuntimeError("Stock date not found in the sheet.")

    date_row_idx, stock_date = date_rows[-1]
    header_idx = -1
    search_end = min(len(all_values), date_row_idx + 10)
    for idx in range(date_row_idx + 1, search_end):
        if _is_stock_header_row(all_values[idx]):
            header_idx = idx
            break
    if header_idx == -1:
        raise RuntimeError(f"Header row not found for stock date block {stock_date.isoformat()}.")

    return stock_date, header_idx, len(all_values)


def parse_ivan_stock_values(
    all_values: Sequence[Sequence[Any]],
    *,
    source_sheet: str = STOCK_SHEET_NAME,
) -> dict[str, Any]:
    total_rows = len(all_values)
    stock_date, header_idx, parse_end = _resolve_latest_stock_sheet_block(all_values)

    rows_to_save: list[dict[str, Any]] = []
    skipped_no_nm_id = 0
    data_rows = 0
    quantity_sum_total = Decimal("0")

    for idx in range(header_idx + 1, parse_end):
        row = all_values[idx]
        if not row:
            continue

        col1 = str(row[0]).strip() if len(row) > 0 else ""
        col2 = str(row[1]).strip() if len(row) > 1 else ""
        col3 = str(row[2]).strip() if len(row) > 2 else ""
        if not col1 and not col2 and not col3:
            continue

        data_rows += 1
        nm_id_raw = col2.replace(" ", "").replace("\xa0", "").strip()
        if not nm_id_raw:
            skipped_no_nm_id += 1
            continue

        try:
            nm_id = int(nm_id_raw)
        except ValueError:
            skipped_no_nm_id += 1
            continue

        qty = normalize_ivan_stock_quantity(col3)
        quantity_sum_total += qty
        size_name, color_name, barcode = parse_row_nomenclature(col1)
        rows_to_save.append(
            {
                "stock_date": stock_date,
                "nm_id": nm_id,
                "size_name": size_name,
                "barcode": barcode,
                "color_name": color_name,
                "quantity": qty,
                "nomenclature_raw": col1,
                "source_sheet": source_sheet,
                "raw_row": row,
            }
        )

    distinct_nm_ids = {row["nm_id"] for row in rows_to_save}
    distinct_nm_id_sizes = {(row["nm_id"], row["size_name"]) for row in rows_to_save}
    rows_with_barcode = sum(1 for row in rows_to_save if row["barcode"])

    return {
        "success": True,
        "stock_date": stock_date,
        "total_rows": total_rows,
        "data_rows": data_rows,
        "rows_with_nm_id": len(rows_to_save),
        "skipped_no_nm_id": skipped_no_nm_id,
        "rows_with_barcode": rows_with_barcode,
        "distinct_nm_id": len(distinct_nm_ids),
        "distinct_nm_id_size": len(distinct_nm_id_sizes),
        "size_level_rows": len(rows_to_save),
        "product_level_rows": len(distinct_nm_ids),
        "quantity_sum_total": int(quantity_sum_total) if quantity_sum_total % 1 == 0 else float(quantity_sum_total),
        "rows_to_save": rows_to_save,
    }


def save_ivan_stock_rows(
    *,
    stock_date: date,
    rows_to_save: Sequence[dict[str, Any]],
    write_db: bool,
) -> dict[str, int]:
    if not write_db or not rows_to_save:
        return {"rows_inserted": 0, "legacy_rows_deleted": 0}

    with session_scope() as session:
        rows_inserted = upsert_rows(
            session=session,
            model=FactIvanStockSheetDay,
            rows=list(rows_to_save),
            conflict_columns=("stock_date", "nm_id", "size_name", "barcode"),
        )
        legacy_rows_deleted = prune_legacy_blank_size_rows(session, stock_date)
    return {
        "rows_inserted": rows_inserted,
        "legacy_rows_deleted": legacy_rows_deleted,
    }


def load_ivan_stock_sheet(
    *,
    sheet_id: Optional[str] = None,
    write_db: bool = False,
) -> dict[str, Any]:
    resolved_sheet_id = (
        sheet_id
        or settings.vvbromo_google_sheet_id
        or "1MxVBCfKX6WSqU5_q-r9h_bFhQ61h3VxmgLNyYY9RcEs"
    )
    creds_path = settings.google_application_credentials or "credentials.json"

    logger.info(f"Connecting to Google Sheets for stock load: {resolved_sheet_id}")
    gs_client = GoogleSheetsClient(credentials_path=creds_path, spreadsheet_id=resolved_sheet_id)

    titles = gs_client.get_worksheet_titles(resolved_sheet_id)
    if not titles:
        raise RuntimeError("Failed to fetch worksheets titles.")

    target_sheet = next((title for title in titles if title.strip().lower() == STOCK_SHEET_NAME.lower()), None)
    if not target_sheet:
        raise RuntimeError(f"Worksheet '{STOCK_SHEET_NAME}' not found.")

    all_values = gs_client.read_range(resolved_sheet_id, f"{target_sheet}!A1:Z")
    if not all_values:
        raise RuntimeError(f"No data retrieved from sheet '{STOCK_SHEET_NAME}'.")

    parse_result = parse_ivan_stock_values(all_values, source_sheet=target_sheet)
    write_result = save_ivan_stock_rows(
        stock_date=parse_result["stock_date"],
        rows_to_save=parse_result["rows_to_save"],
        write_db=write_db,
    )

    return {
        key: value
        for key, value in {
            **parse_result,
            **write_result,
        }.items()
        if key != "rows_to_save"
    }


def load_ivan_stock_size_level(stock_date: Optional[date] = None) -> list[dict[str, Any]]:
    with session_scope() as session:
        stock_date = resolve_latest_ivan_stock_date(session, stock_date)
        if stock_date is None:
            return []

        stmt = select(
            FactIvanStockSheetDay.stock_date,
            FactIvanStockSheetDay.nm_id,
            FactIvanStockSheetDay.size_name,
            FactIvanStockSheetDay.barcode,
            FactIvanStockSheetDay.color_name,
            FactIvanStockSheetDay.quantity,
            FactIvanStockSheetDay.nomenclature_raw,
        ).where(FactIvanStockSheetDay.stock_date == stock_date)

        results = session.execute(stmt).all()
        rows: list[dict[str, Any]] = []
        for row in results:
            normalized_quantity = normalize_ivan_stock_quantity(row.quantity)
            rows.append(
                {
                    "stock_date": row.stock_date,
                    "nm_id": row.nm_id,
                    "size_name": row.size_name,
                    "barcode": row.barcode,
                    "color_name": row.color_name,
                    "quantity": int(normalized_quantity) if normalized_quantity % 1 == 0 else float(normalized_quantity),
                    "nomenclature_raw": row.nomenclature_raw,
                }
            )
        return rows


def load_ivan_stock_product_level(stock_date: Optional[date] = None) -> list[dict[str, Any]]:
    with session_scope() as session:
        stock_date = resolve_latest_ivan_stock_date(session, stock_date)
        if stock_date is None:
            return []

        stmt = (
            select(
                FactIvanStockSheetDay.stock_date,
                FactIvanStockSheetDay.nm_id,
                func.sum(
                    case(
                        (FactIvanStockSheetDay.quantity < 0, 0),
                        else_=FactIvanStockSheetDay.quantity,
                    )
                ).label("ivan_stock_qty"),
                func.count(func.distinct(FactIvanStockSheetDay.size_name)).label("sizes_count"),
                func.count(func.distinct(FactIvanStockSheetDay.barcode)).label("barcodes_count"),
            )
            .where(FactIvanStockSheetDay.stock_date == stock_date)
            .group_by(
                FactIvanStockSheetDay.stock_date,
                FactIvanStockSheetDay.nm_id,
            )
        )

        results = session.execute(stmt).all()
        rows: list[dict[str, Any]] = []
        for row in results:
            normalized_quantity = normalize_ivan_stock_quantity(row.ivan_stock_qty)
            rows.append(
                {
                    "stock_date": row.stock_date,
                    "nm_id": row.nm_id,
                    "ivan_stock_qty": int(normalized_quantity) if normalized_quantity % 1 == 0 else float(normalized_quantity),
                    "sizes_count": row.sizes_count,
                    "barcodes_count": row.barcodes_count,
                }
            )
        return rows
