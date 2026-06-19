from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select

from scripts.export_streamlit_v1_dataset import export_streamlit_v1_dataset
from src.db.models import FactFunnelDay, SettingsProducts
from src.db.funnel_loader import build_fact_funnel_day_db_row
from src.db.mart_total_report_builder import build_mart_total_report
from src.db.session import session_scope
from src.importers.common import close_workbook, load_workbook_readonly, normalize_header


CSV_CANDIDATE_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251")
CSV_CANDIDATE_DELIMITERS = ",;\t"
SUPPORTED_FILE_SUFFIXES = {".csv", ".xlsx"}
SUPPORTED_IMPORT_MODES = ("insert-missing",)
IVAN_CURRENT_IMPORT_SOURCE = "IVAN_CURRENT_IMPORT"
IVAN_CURRENT_DATA_STATUS = "MANUAL_UPLOAD"

FUNNEL_EXPORT_COLUMNS = [
    "date",
    "nm_id",
    "supplier_article",
    "impressions",
    "card_clicks",
    "cart_count",
    "order_count",
    "order_sum",
    "ctr",
    "add_to_cart_conversion",
    "cart_to_order_conversion",
    "local_orders_percent",
    "avg_delivery_time",
]

AD_EXPORT_COLUMNS = [
    "date",
    "nm_id",
    "supplier_article",
    "ad_spend",
    "ad_views",
    "ad_clicks",
    "ad_atbs",
    "ad_orders",
]

COMBINED_EXPORT_COLUMNS = FUNNEL_EXPORT_COLUMNS + [
    column
    for column in AD_EXPORT_COLUMNS
    if column not in {"date", "nm_id", "supplier_article"}
]

POSITIONAL_FIELD_SPECS: tuple[dict[str, Any], ...] = (
    {"index": 0, "target": "supplier_article", "expected_headers": ("Артикул продавца",), "parser": "text"},
    {"index": 1, "target": "nm_id", "expected_headers": ("Артикул WB",), "parser": "int"},
    {"index": 2, "target": "date", "expected_headers": ("Дата",), "parser": "date"},
    {"index": 3, "target": "impressions", "expected_headers": ("Показы",), "parser": "decimal"},
    {"index": 4, "target": "card_clicks", "expected_headers": ("Переходы в карточку",), "parser": "decimal"},
    {"index": 5, "target": "cart_count", "expected_headers": ("Положили в корзину",), "parser": "decimal"},
    {"index": 6, "target": "order_count", "expected_headers": ("Заказали, шт",), "parser": "decimal"},
    {"index": 7, "target": None, "expected_headers": ("СиТиАр",), "parser": None, "reason": "legacy_duplicate_ctr_column"},
    {"index": 8, "target": "ctr", "expected_headers": ("CTR",), "parser": "decimal"},
    {"index": 9, "target": "add_to_cart_conversion", "expected_headers": ("Конверсия в корзину, %",), "parser": "decimal"},
    {"index": 10, "target": "cart_to_order_conversion", "expected_headers": ("Конверсия в заказ, %",), "parser": "decimal"},
    {"index": 11, "target": "order_sum", "expected_headers": ("Заказали на сумму, ₽", "Заказали на сумму, ?"), "parser": "decimal"},
    {"index": 12, "target": None, "expected_headers": ("Расход на все корзины",), "parser": None, "reason": "unconfirmed_metric_not_imported"},
    {"index": 13, "target": "local_orders_percent", "expected_headers": ("Локальные заказы, %",), "parser": "decimal"},
    {"index": 14, "target": "ad_spend", "expected_headers": ("Сумма кампания",), "parser": "decimal"},
    {"index": 15, "target": None, "expected_headers": ("Показы",), "parser": None, "reason": "ambiguous_post_campaign_metric_not_imported"},
    {"index": 16, "target": None, "expected_headers": ("Переходы в карточку",), "parser": None, "reason": "ambiguous_post_campaign_metric_not_imported"},
    {"index": 17, "target": None, "expected_headers": ("Положили в корзину",), "parser": None, "reason": "ambiguous_post_campaign_metric_not_imported"},
    {"index": 18, "target": None, "expected_headers": ("Заказали, шт",), "parser": None, "reason": "ambiguous_post_campaign_metric_not_imported"},
)


@dataclass(frozen=True)
class ParsedIvanCurrentFile:
    file_path: Path
    file_type: str
    encoding: str | None
    delimiter: str | None
    rows_read: int
    column_count: int
    raw_headers: tuple[str, ...]
    normalized_headers: tuple[str, ...]
    rows_normalized: tuple[dict[str, Any], ...]
    duplicate_key_count: int
    duplicate_key_examples: tuple[dict[str, Any], ...]
    recognized_targets: tuple[str, ...]
    recognized_blocks: tuple[str, ...]
    unmapped_columns: tuple[dict[str, Any], ...]
    header_mismatches: tuple[dict[str, Any], ...]


def _parse_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("&nbsp;", " ").replace("\xa0", " ").replace("\u202f", " ").strip()
    return text or None


def _parse_decimal(value: Any) -> Decimal | None:
    text = _parse_text(value)
    if text in (None, "-", "—"):
        return None
    normalized = (
        text.replace("\xa0", "")
        .replace("\u202f", "")
        .replace(" ", "")
        .replace("%", "")
        .replace("₽", "")
        .replace("?", "")
        .replace(",", ".")
    )
    if not normalized:
        return None
    try:
        return Decimal(normalized)
    except (ArithmeticError, InvalidOperation, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    decimal_value = _parse_decimal(value)
    if decimal_value is None:
        return None
    try:
        return int(decimal_value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    text = _parse_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parser_for(name: str | None):
    if name == "text":
        return _parse_text
    if name == "int":
        return _parse_int
    if name == "date":
        return _parse_date
    if name == "decimal":
        return _parse_decimal
    return lambda value: value


def _detect_csv_format(file_path: Path) -> tuple[str, str]:
    for encoding in CSV_CANDIDATE_ENCODINGS:
        try:
            text = file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        sample = text[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=CSV_CANDIDATE_DELIMITERS)
            return encoding, dialect.delimiter
        except csv.Error:
            return encoding, ","
    raise UnicodeDecodeError("utf-8", b"", 0, 1, "unable to decode CSV with supported encodings")


def _read_csv_rows(file_path: Path) -> tuple[str, str, list[list[Any]]]:
    encoding, delimiter = _detect_csv_format(file_path)
    with file_path.open("r", encoding=encoding, newline="") as file_handle:
        reader = csv.reader(file_handle, delimiter=delimiter)
        rows = [list(row) for row in reader]
    return encoding, delimiter, rows


def _read_xlsx_rows(file_path: Path) -> tuple[list[list[Any]], str]:
    workbook = load_workbook_readonly(file_path)
    try:
        sheet = workbook.active
        rows = [
            [cell.value for cell in row]
            for row in sheet.iter_rows()
        ]
    finally:
        close_workbook(workbook)
    return rows, sheet.title


def _normalize_headers(raw_headers: list[Any]) -> tuple[str, ...]:
    return tuple(normalize_header(header) for header in raw_headers)


def _json_safe(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _json_ready_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_safe(value) for key, value in row.items()}


def _build_keyed_rows(rows: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> dict[tuple[date, int], dict[str, Any]]:
    keyed: dict[tuple[date, int], dict[str, Any]] = {}
    for row in rows:
        row_date = row.get("date")
        nm_id = row.get("nm_id")
        if row_date is None or nm_id is None:
            continue
        keyed[(row_date, int(nm_id))] = row
    return keyed


def _load_active_products() -> dict[int, dict[str, Any]]:
    with session_scope() as session:
        rows = session.execute(
            select(
                SettingsProducts.nm_id,
                SettingsProducts.supplier_article,
                SettingsProducts.title,
                SettingsProducts.subject,
                SettingsProducts.brand,
            )
            .where(SettingsProducts.active.is_(True))
            .order_by(SettingsProducts.nm_id)
        ).all()
    return {
        int(row.nm_id): {
            "nm_id": int(row.nm_id),
            "supplier_article": row.supplier_article,
            "title": row.title,
            "subject": row.subject,
            "brand": row.brand,
        }
        for row in rows
        if row.nm_id is not None
    }


def _plan_header_mapping(normalized_headers: tuple[str, ...]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], tuple[str, ...], tuple[str, ...]]:
    mapped: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    recognized_targets: list[str] = []
    for spec in POSITIONAL_FIELD_SPECS:
        index = int(spec["index"])
        actual_header = normalized_headers[index] if index < len(normalized_headers) else ""
        expected_headers = tuple(spec["expected_headers"])
        target = spec.get("target")
        header_matches = actual_header in expected_headers
        if target:
            recognized_targets.append(target)
            mapped.append(
                {
                    "column_index": index + 1,
                    "raw_header": actual_header,
                    "target_field": target,
                    "expected_headers": list(expected_headers),
                    "header_matches_expected": header_matches,
                }
            )
        else:
            unmapped.append(
                {
                    "column_index": index + 1,
                    "raw_header": actual_header,
                    "reason": spec.get("reason", "not_imported"),
                }
            )
        if not header_matches:
            mismatches.append(
                {
                    "column_index": index + 1,
                    "actual_header": actual_header,
                    "expected_headers": list(expected_headers),
                    "target_field": target,
                }
            )
    recognized_blocks: list[str] = []
    funnel_targets = {"date", "nm_id", "supplier_article", "card_clicks", "cart_count", "order_count", "order_sum", "ctr", "add_to_cart_conversion", "cart_to_order_conversion"}
    ad_targets = {"ad_spend"}
    recognized_target_set = set(recognized_targets)
    if funnel_targets.issubset(recognized_target_set):
        recognized_blocks.append("funnel_day")
    if ad_targets.issubset(recognized_target_set):
        recognized_blocks.append("ad_day")
    return mapped, unmapped, tuple(sorted(recognized_targets)), tuple(recognized_blocks), tuple(mismatches)


def parse_ivan_current_file(file_path: str | Path) -> ParsedIvanCurrentFile:
    resolved_path = Path(file_path)
    suffix = resolved_path.suffix.lower()
    if suffix not in SUPPORTED_FILE_SUFFIXES:
        raise ValueError(f"Unsupported file type: {suffix}")

    if suffix == ".csv":
        encoding, delimiter, rows = _read_csv_rows(resolved_path)
        file_type = "csv"
    else:
        rows, _sheet_name = _read_xlsx_rows(resolved_path)
        encoding = None
        delimiter = None
        file_type = "xlsx"

    if not rows:
        raise ValueError(f"Input file is empty: {resolved_path}")

    raw_headers = ["" if value is None else str(value) for value in rows[0]]
    normalized_headers = _normalize_headers(raw_headers)
    mapped_columns, unmapped_columns, recognized_targets, recognized_blocks, header_mismatches = _plan_header_mapping(normalized_headers)

    parsed_rows: list[dict[str, Any]] = []
    key_counts: Counter[tuple[date | None, int | None]] = Counter()
    rows_read = 0
    for raw_row in rows[1:]:
        if not any(_parse_text(value) is not None for value in raw_row):
            continue
        row_values = list(raw_row) + [None] * max(0, len(POSITIONAL_FIELD_SPECS) - len(raw_row))
        normalized_row: dict[str, Any] = {}
        for spec in POSITIONAL_FIELD_SPECS:
            target = spec.get("target")
            if not target:
                continue
            parser = _parser_for(spec.get("parser"))
            normalized_row[target] = parser(row_values[int(spec["index"])])
        normalized_row["source_file_name"] = resolved_path.name
        parsed_rows.append(normalized_row)
        rows_read += 1
        key_counts[(normalized_row.get("date"), normalized_row.get("nm_id"))] += 1

    duplicate_examples: list[dict[str, Any]] = []
    duplicate_key_count = 0
    for (row_date, nm_id), count in key_counts.items():
        if row_date is None or nm_id is None or count <= 1:
            continue
        duplicate_key_count += 1
        if len(duplicate_examples) < 10:
            duplicate_examples.append({"date": row_date.isoformat(), "nm_id": int(nm_id), "rows_count": count})

    return ParsedIvanCurrentFile(
        file_path=resolved_path,
        file_type=file_type,
        encoding=encoding,
        delimiter=delimiter,
        rows_read=rows_read,
        column_count=len(raw_headers),
        raw_headers=tuple(raw_headers),
        normalized_headers=normalized_headers,
        rows_normalized=tuple(parsed_rows),
        duplicate_key_count=duplicate_key_count,
        duplicate_key_examples=tuple(duplicate_examples),
        recognized_targets=recognized_targets,
        recognized_blocks=recognized_blocks,
        unmapped_columns=tuple(unmapped_columns),
        header_mismatches=header_mismatches,
    )


def _scope_rows(parsed: ParsedIvanCurrentFile, *, only_active_products: bool) -> dict[str, Any]:
    valid_rows = [
        row
        for row in parsed.rows_normalized
        if row.get("date") is not None and row.get("nm_id") is not None
    ]
    if not only_active_products:
        return {
            "scope_name": "all_rows",
            "valid_rows": valid_rows,
            "scoped_rows": valid_rows,
            "skipped_rows": [],
            "active_products": None,
            "db_scope_status": "not_requested",
        }

    active_products = _load_active_products()
    active_nm_ids = set(active_products)
    scoped_rows = [row for row in valid_rows if int(row["nm_id"]) in active_nm_ids]
    skipped_rows = [row for row in valid_rows if int(row["nm_id"]) not in active_nm_ids]
    return {
        "scope_name": "active_products",
        "valid_rows": valid_rows,
        "scoped_rows": scoped_rows,
        "skipped_rows": skipped_rows,
        "active_products": active_products,
        "db_scope_status": "ok",
    }


def build_ivan_current_audit_summary(parsed: ParsedIvanCurrentFile, *, only_active_products: bool = False) -> dict[str, Any]:
    scope_data = _scope_rows(parsed, only_active_products=only_active_products)
    valid_rows = scope_data["valid_rows"]
    scoped_rows = scope_data["scoped_rows"]
    keyed_rows = _build_keyed_rows(valid_rows)
    scoped_keyed_rows = _build_keyed_rows(scoped_rows)
    valid_dates = sorted({row["date"] for row in valid_rows if row.get("date") is not None})
    file_nm_ids = sorted({int(row["nm_id"]) for row in valid_rows if row.get("nm_id") is not None})
    supplier_articles = sorted({str(row["supplier_article"]) for row in valid_rows if row.get("supplier_article") is not None})
    active_products = scope_data["active_products"] or {}
    active_nm_ids = sorted(active_products) if active_products else []
    file_nm_ids_in_active = sorted(nm_id for nm_id in file_nm_ids if nm_id in active_products) if active_products else []
    active_nm_ids_missing_in_file = sorted(nm_id for nm_id in active_nm_ids if nm_id not in set(file_nm_ids)) if active_products else []
    file_nm_ids_outside_active = sorted(nm_id for nm_id in file_nm_ids if nm_id not in set(active_nm_ids)) if active_products else []

    blocks_safe_for_normalization = list(parsed.recognized_blocks)
    if "ad_day" not in blocks_safe_for_normalization:
        blocks_safe_for_normalization = [block for block in blocks_safe_for_normalization if block != "ad_day"]

    return {
        "file_path": str(parsed.file_path),
        "file_type": parsed.file_type,
        "encoding": parsed.encoding,
        "delimiter": parsed.delimiter,
        "rows_read": parsed.rows_read,
        "column_count": parsed.column_count,
        "min_date": valid_dates[0].isoformat() if valid_dates else None,
        "max_date": valid_dates[-1].isoformat() if valid_dates else None,
        "unique_date_count": len(valid_dates),
        "unique_nm_id_count": len(file_nm_ids),
        "unique_supplier_article_count": len(supplier_articles),
        "valid_date_nm_id_rows": len(keyed_rows),
        "active_scope_requested": only_active_products,
        "db_scope_status": scope_data["db_scope_status"],
        "active_products_total": len(active_nm_ids),
        "file_nm_ids_in_active_count": len(file_nm_ids_in_active),
        "active_nm_ids_found_in_file_count": len(file_nm_ids_in_active),
        "active_nm_ids_missing_in_file_count": len(active_nm_ids_missing_in_file),
        "active_nm_ids_missing_in_file_preview": active_nm_ids_missing_in_file[:100],
        "file_nm_ids_outside_active_count": len(file_nm_ids_outside_active),
        "file_nm_ids_outside_active_preview": file_nm_ids_outside_active[:100],
        "rows_for_active_products": len(scoped_rows),
        "scoped_valid_date_nm_id_rows": len(scoped_keyed_rows),
        "duplicate_date_nm_id_keys": parsed.duplicate_key_count,
        "duplicate_date_nm_id_examples": list(parsed.duplicate_key_examples),
        "recognized_blocks": list(parsed.recognized_blocks),
        "recognized_targets": list(parsed.recognized_targets),
        "header_mismatches": list(parsed.header_mismatches),
        "blocks_safe_for_normalization": blocks_safe_for_normalization,
        "unmapped_columns": list(parsed.unmapped_columns),
        "rows_with_impressions": sum(1 for row in scoped_rows if row.get("impressions") is not None),
        "rows_with_order_count": sum(1 for row in scoped_rows if row.get("order_count") is not None),
        "rows_with_ctr": sum(1 for row in scoped_rows if row.get("ctr") is not None),
        "rows_with_ad_spend": sum(1 for row in scoped_rows if row.get("ad_spend") is not None),
        "rows_with_ad_orders": sum(1 for row in scoped_rows if row.get("ad_orders") is not None),
        "preview_rows": [_json_ready_row(row) for row in scoped_rows[:5]],
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _json_safe(row.get(column)) for column in columns})


def _write_unmapped_columns_csv(path: Path, unmapped_columns: tuple[dict[str, Any], ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=["column_index", "raw_header", "reason"])
        writer.writeheader()
        for row in unmapped_columns:
            writer.writerow(row)


def persist_ivan_current_audit_report(
    parsed: ParsedIvanCurrentFile,
    *,
    only_active_products: bool,
    output_dir: str | Path,
) -> dict[str, Any]:
    summary = build_ivan_current_audit_summary(parsed, only_active_products=only_active_products)
    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    report_path = resolved_output_dir / "audit_report.json"
    unmapped_path = resolved_output_dir / "unmapped_columns.csv"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_safe), encoding="utf-8")
    _write_unmapped_columns_csv(unmapped_path, parsed.unmapped_columns)
    summary["audit_report_path"] = str(report_path)
    summary["unmapped_columns_path"] = str(unmapped_path)
    return summary


def normalize_ivan_current_file(
    parsed: ParsedIvanCurrentFile,
    *,
    only_active_products: bool,
    output_dir: str | Path,
    split_by_nm: bool = False,
) -> dict[str, Any]:
    scope_data = _scope_rows(parsed, only_active_products=only_active_products)
    scoped_rows = scope_data["scoped_rows"]
    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    funnel_rows = [{column: row.get(column) for column in FUNNEL_EXPORT_COLUMNS} for row in scoped_rows]
    ad_rows = [
        {column: row.get(column) for column in AD_EXPORT_COLUMNS}
        for row in scoped_rows
        if any(row.get(metric) is not None for metric in ("ad_spend", "ad_views", "ad_clicks", "ad_atbs", "ad_orders"))
    ]

    created_files: dict[str, str] = {}
    funnel_path = resolved_output_dir / "funnel_day.csv"
    _write_csv(funnel_path, funnel_rows, FUNNEL_EXPORT_COLUMNS)
    created_files["funnel_day"] = str(funnel_path)

    if ad_rows:
        ad_path = resolved_output_dir / "ad_day.csv"
        _write_csv(ad_path, ad_rows, AD_EXPORT_COLUMNS)
        created_files["ad_day"] = str(ad_path)

    unmapped_path = resolved_output_dir / "unmapped_columns.csv"
    _write_unmapped_columns_csv(unmapped_path, parsed.unmapped_columns)
    created_files["unmapped_columns"] = str(unmapped_path)

    by_nm_dir = resolved_output_dir.parent / "by_nm_id"
    by_nm_count = 0
    if split_by_nm:
        combined_rows_by_nm: dict[int, list[dict[str, Any]]] = {}
        for row in scoped_rows:
            nm_id = row.get("nm_id")
            if nm_id is None:
                continue
            combined_rows_by_nm.setdefault(int(nm_id), []).append(
                {column: row.get(column) for column in COMBINED_EXPORT_COLUMNS}
            )
        for nm_id, rows in combined_rows_by_nm.items():
            _write_csv(by_nm_dir / f"{nm_id}.csv", rows, COMBINED_EXPORT_COLUMNS)
        by_nm_count = len(combined_rows_by_nm)

    return {
        "scope_name": scope_data["scope_name"],
        "rows_scoped": len(scoped_rows),
        "recognized_blocks": list(parsed.recognized_blocks),
        "created_files": created_files,
        "funnel_rows": len(funnel_rows),
        "ad_rows": len(ad_rows),
        "stock_rows": 0,
        "price_rows": 0,
        "by_nm_file_count": by_nm_count,
        "by_nm_dir": str(by_nm_dir) if split_by_nm else None,
        "rows_skipped_out_of_scope": len(scope_data["skipped_rows"]),
    }


def _read_normalized_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as file_handle:
        reader = csv.DictReader(file_handle)
        rows: list[dict[str, Any]] = []
        for row in reader:
            rows.append(
                {
                    "date": _parse_date(row.get("date")),
                    "nm_id": _parse_int(row.get("nm_id")),
                    "supplier_article": _parse_text(row.get("supplier_article")),
                    "impressions": _parse_decimal(row.get("impressions")),
                    "card_clicks": _parse_decimal(row.get("card_clicks")),
                    "cart_count": _parse_decimal(row.get("cart_count")),
                    "order_count": _parse_decimal(row.get("order_count")),
                    "order_sum": _parse_decimal(row.get("order_sum")),
                    "ctr": _parse_decimal(row.get("ctr")),
                    "add_to_cart_conversion": _parse_decimal(row.get("add_to_cart_conversion")),
                    "cart_to_order_conversion": _parse_decimal(row.get("cart_to_order_conversion")),
                    "local_orders_percent": _parse_decimal(row.get("local_orders_percent")),
                    "avg_delivery_time": _parse_decimal(row.get("avg_delivery_time")),
                }
            )
        return rows


def _row_has_useful_funnel_data(row: dict[str, Any]) -> bool:
    return any(
        row.get(field) is not None
        for field in ("card_clicks", "cart_count", "order_count", "ctr")
    )


def _split_insertable_rows_by_empty_guard(rows_to_insert: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    for row in rows_to_insert:
        if _row_has_useful_funnel_data(row):
            accepted_rows.append(row)
        else:
            skipped_rows.append(row)
    return accepted_rows, skipped_rows


def _build_insertable_by_date(rows_to_insert: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: dict[date, dict[str, Any]] = {}
    for row in rows_to_insert:
        row_date = row["date"]
        bucket = summary.setdefault(
            row_date,
            {"date": row_date.isoformat(), "rows_to_insert": 0, "nm_ids": set()},
        )
        bucket["rows_to_insert"] += 1
        bucket["nm_ids"].add(int(row["nm_id"]))
    return [
        {
            "date": item["date"],
            "rows_to_insert": item["rows_to_insert"],
            "nm_count": len(item["nm_ids"]),
        }
        for _row_date, item in sorted(summary.items(), key=lambda pair: pair[0])
    ]


def _build_insertable_by_nm_id(rows_to_insert: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: dict[int, dict[str, Any]] = {}
    for row in rows_to_insert:
        nm_id = int(row["nm_id"])
        row_date = row["date"]
        bucket = summary.setdefault(
            nm_id,
            {
                "nm_id": nm_id,
                "supplier_article": row.get("supplier_article"),
                "rows_to_insert": 0,
                "date_min": row_date,
                "date_max": row_date,
            },
        )
        bucket["rows_to_insert"] += 1
        if row_date < bucket["date_min"]:
            bucket["date_min"] = row_date
        if row_date > bucket["date_max"]:
            bucket["date_max"] = row_date
    return [
        {
            "nm_id": item["nm_id"],
            "supplier_article": item["supplier_article"],
            "rows_to_insert": item["rows_to_insert"],
            "date_min": item["date_min"].isoformat(),
            "date_max": item["date_max"].isoformat(),
        }
        for _nm_id, item in sorted(summary.items(), key=lambda pair: pair[0])
    ]


def _build_insertable_field_counts(rows_to_insert: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    field_names = [
        "card_clicks",
        "cart_count",
        "order_count",
        "order_sum",
        "ctr",
        "add_to_cart_conversion",
        "cart_to_order_conversion",
        "local_orders_percent",
        "avg_delivery_time",
    ]
    non_null_counts: dict[str, int] = {}
    null_counts: dict[str, int] = {}
    for field_name in field_names:
        non_null_counts[field_name] = sum(1 for row in rows_to_insert if row.get(field_name) is not None)
        null_counts[field_name] = sum(1 for row in rows_to_insert if row.get(field_name) is None)
    return non_null_counts, null_counts


def _write_list_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _json_safe(value) for key, value in row.items()})


def _build_fact_funnel_day_insert_row(row: dict[str, Any], *, loaded_at: datetime) -> dict[str, Any]:
    source_row = {
        "date": row.get("date"),
        "nm_id": row.get("nm_id"),
        "impressions": row.get("impressions"),
        "card_clicks": row.get("card_clicks"),
        "cartCount": row.get("cart_count"),
        "orderCount": row.get("order_count"),
        "orderSum": row.get("order_sum"),
        "ctr": row.get("ctr"),
        "addToCartConversion": row.get("add_to_cart_conversion"),
        "cartToOrderConversion": row.get("cart_to_order_conversion"),
        "avg_delivery_time": row.get("avg_delivery_time"),
        "local_orders_percent": row.get("local_orders_percent"),
        "data_status": IVAN_CURRENT_DATA_STATUS,
        "source_status": IVAN_CURRENT_IMPORT_SOURCE,
        "loaded_at": loaded_at,
    }
    return build_fact_funnel_day_db_row(source_row)


def _insert_fact_funnel_day_rows(session, rows: list[dict[str, Any]], *, batch_size: int = 500) -> int:
    if not rows:
        return 0
    total_inserted = 0
    for index in range(0, len(rows), batch_size):
        chunk = rows[index:index + batch_size]
        stmt = pg_insert(FactFunnelDay.__table__).values(chunk).on_conflict_do_nothing(
            index_elements=[FactFunnelDay.__table__.c.date, FactFunnelDay.__table__.c.nm_id]
        )
        result = session.execute(stmt)
        total_inserted += result.rowcount or 0
    return total_inserted


def _load_existing_funnel_keys(session, rows: list[dict[str, Any]]) -> set[tuple[date, int]]:
    keyed_rows = _build_keyed_rows(rows)
    if not keyed_rows:
        return set()
    requested_keys = set(keyed_rows)
    unique_dates = sorted({row_date for row_date, _nm_id in keyed_rows})
    unique_nm_ids = sorted({nm_id for _row_date, nm_id in keyed_rows})
    stmt = (
        select(FactFunnelDay.date, FactFunnelDay.nm_id)
        .where(FactFunnelDay.date >= unique_dates[0], FactFunnelDay.date <= unique_dates[-1])
        .where(FactFunnelDay.nm_id.in_(unique_nm_ids))
    )
    return {
        (row.date, int(row.nm_id))
        for row in session.execute(stmt).all()
        if (row.date, int(row.nm_id)) in requested_keys
    }


def build_ivan_current_import_dry_run_summary(
    *,
    source_dir: str | Path,
    only_active_products: bool,
    mode: str = "insert-missing",
) -> dict[str, Any]:
    if mode not in SUPPORTED_IMPORT_MODES:
        raise ValueError(f"Unsupported mode: {mode}")

    resolved_source_dir = Path(source_dir)
    funnel_rows = _read_normalized_csv(resolved_source_dir / "funnel_day.csv")
    ad_rows = _read_normalized_csv(resolved_source_dir / "ad_day.csv")

    active_products = _load_active_products() if only_active_products else {}
    active_nm_ids = set(active_products)
    if only_active_products:
        funnel_rows = [row for row in funnel_rows if row.get("nm_id") is not None and int(row["nm_id"]) in active_nm_ids]

    valid_funnel_rows = [row for row in funnel_rows if row.get("date") is not None and row.get("nm_id") is not None]
    keyed_rows = _build_keyed_rows(valid_funnel_rows)
    dates = sorted({row["date"] for row in valid_funnel_rows if row.get("date") is not None})
    nm_ids = sorted({int(row["nm_id"]) for row in valid_funnel_rows if row.get("nm_id") is not None})

    existing_keys: set[tuple[date, int]] = set()
    db_status = "ok"
    db_error = None
    if keyed_rows:
        try:
            with session_scope() as session:
                existing_keys = _load_existing_funnel_keys(session, valid_funnel_rows)
        except Exception as exc:
            db_status = "db_unavailable"
            db_error = str(exc)

    rows_to_insert_before_empty_guard = [row for row in valid_funnel_rows if (row["date"], int(row["nm_id"])) not in existing_keys]
    rows_to_insert, skipped_empty_rows = _split_insertable_rows_by_empty_guard(rows_to_insert_before_empty_guard)
    null_counts: dict[str, int] = {}
    for column in FUNNEL_EXPORT_COLUMNS:
        if column in {"date", "nm_id", "supplier_article"}:
            continue
        null_counts[column] = sum(1 for row in valid_funnel_rows if row.get(column) is None)
    insertable_dates = sorted({row["date"] for row in rows_to_insert if row.get("date") is not None})
    insertable_nm_ids = sorted({int(row["nm_id"]) for row in rows_to_insert if row.get("nm_id") is not None})
    insertable_by_date = _build_insertable_by_date(rows_to_insert)
    insertable_by_nm_id = _build_insertable_by_nm_id(rows_to_insert)
    insertable_field_non_null_counts, insertable_field_null_counts = _build_insertable_field_counts(rows_to_insert)
    insertable_rows_with_useful_data = sum(1 for row in rows_to_insert if _row_has_useful_funnel_data(row))
    insertable_rows_almost_empty = len(skipped_empty_rows)

    return {
        "mode": mode,
        "write_requested": False,
        "write_executed": False,
        "source_dir": str(resolved_source_dir),
        "only_active_products": only_active_products,
        "db_status": db_status,
        "db_error": db_error,
        "planned_tables": ["fact_funnel_day"] if valid_funnel_rows else [],
        "staged_only_files": ["ad_day.csv"] if ad_rows else [],
        "normalized_files_present": {
            "funnel_day": (resolved_source_dir / "funnel_day.csv").exists(),
            "ad_day": (resolved_source_dir / "ad_day.csv").exists(),
            "stock_day": (resolved_source_dir / "stock_day.csv").exists(),
            "price_day": (resolved_source_dir / "price_day.csv").exists(),
        },
        "rows_found_total": len(funnel_rows),
        "rows_with_valid_date_nm_id": len(keyed_rows),
        "rows_already_in_db": len(existing_keys),
        "rows_skipped_existing": len(existing_keys),
        "insertable_rows_before_empty_guard": len(rows_to_insert_before_empty_guard),
        "skipped_empty_rows": len(skipped_empty_rows),
        "skipped_empty_rows_preview": [_json_ready_row(row) for row in skipped_empty_rows[:10]],
        "rows_to_insert": len(rows_to_insert) if db_status == "ok" else 0,
        "rows_can_insert": len(rows_to_insert) if db_status == "ok" else 0,
        "conflicts_with_api_or_existing_rows": len(existing_keys),
        "covered_dates": [item.isoformat() for item in dates],
        "covered_nm_ids_count": len(nm_ids),
        "covered_nm_ids_preview": nm_ids[:100],
        "rows_with_impressions": sum(1 for row in valid_funnel_rows if row.get("impressions") is not None),
        "rows_with_ctr": sum(1 for row in valid_funnel_rows if row.get("ctr") is not None),
        "rows_with_order_count": sum(1 for row in valid_funnel_rows if row.get("order_count") is not None),
        "null_field_counts": null_counts,
        "insertable_date_min": insertable_dates[0].isoformat() if insertable_dates else None,
        "insertable_date_max": insertable_dates[-1].isoformat() if insertable_dates else None,
        "insertable_date_count": len(insertable_dates),
        "insertable_nm_id_count": len(insertable_nm_ids),
        "insertable_nm_ids_preview": insertable_nm_ids[:100],
        "insertable_by_date": insertable_by_date,
        "insertable_by_nm_id": insertable_by_nm_id,
        "insertable_field_non_null_counts": insertable_field_non_null_counts,
        "insertable_field_null_counts": insertable_field_null_counts,
        "insertable_rows_with_useful_data": insertable_rows_with_useful_data,
        "insertable_rows_almost_empty": insertable_rows_almost_empty,
    }


def persist_ivan_current_import_dry_run_report(
    summary: dict[str, Any],
    *,
    output_dir: str | Path,
) -> dict[str, Any]:
    resolved_output_dir = Path(output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    report_path = resolved_output_dir / "dry_run_insert_missing_report.json"
    by_date_path = resolved_output_dir / "dry_run_insert_missing_by_date.csv"
    by_nm_id_path = resolved_output_dir / "dry_run_insert_missing_by_nm_id.csv"

    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_safe), encoding="utf-8")
    _write_list_csv(by_date_path, list(summary.get("insertable_by_date", [])))
    _write_list_csv(by_nm_id_path, list(summary.get("insertable_by_nm_id", [])))

    persisted = dict(summary)
    persisted["dry_run_report_path"] = str(report_path)
    persisted["dry_run_by_date_path"] = str(by_date_path)
    persisted["dry_run_by_nm_id_path"] = str(by_nm_id_path)
    return persisted


def _build_post_apply_readback_summary(inserted_rows: list[dict[str, Any]], rows_inserted: int) -> dict[str, Any]:
    if not inserted_rows:
        return {
            "rows_inserted": rows_inserted,
            "inserted_date_min": None,
            "inserted_date_max": None,
            "inserted_nm_id_count": 0,
            "duplicate_date_nm_id_keys": 0,
            "existing_api_rows_overwritten": 0,
            "fact_rows_in_inserted_ranges": 0,
        }
    inserted_dates = sorted({row["date"] for row in inserted_rows if row.get("date") is not None})
    inserted_nm_ids = sorted({int(row["nm_id"]) for row in inserted_rows if row.get("nm_id") is not None})
    date_from = inserted_dates[0]
    date_to = inserted_dates[-1]
    with session_scope() as session:
        duplicate_stmt = (
            select(func.count())
            .select_from(
                select(FactFunnelDay.date, FactFunnelDay.nm_id)
                .where(FactFunnelDay.date >= date_from, FactFunnelDay.date <= date_to)
                .where(FactFunnelDay.nm_id.in_(inserted_nm_ids))
                .group_by(FactFunnelDay.date, FactFunnelDay.nm_id)
                .having(func.count() > 1)
                .subquery()
            )
        )
        fact_count_stmt = (
            select(func.count())
            .select_from(FactFunnelDay)
            .where(FactFunnelDay.date >= date_from, FactFunnelDay.date <= date_to)
            .where(FactFunnelDay.nm_id.in_(inserted_nm_ids))
        )
        duplicate_keys = int(session.execute(duplicate_stmt).scalar_one() or 0)
        fact_rows_in_range = int(session.execute(fact_count_stmt).scalar_one() or 0)
    return {
        "rows_inserted": rows_inserted,
        "inserted_date_min": date_from.isoformat(),
        "inserted_date_max": date_to.isoformat(),
        "inserted_nm_id_count": len(inserted_nm_ids),
        "duplicate_date_nm_id_keys": duplicate_keys,
        "existing_api_rows_overwritten": 0,
        "fact_rows_in_inserted_ranges": fact_rows_in_range,
    }


def apply_ivan_current_insert_missing(
    *,
    source_dir: str | Path,
    only_active_products: bool,
    mode: str = "insert-missing",
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    summary = build_ivan_current_import_dry_run_summary(
        source_dir=source_dir,
        only_active_products=only_active_products,
        mode=mode,
    )
    summary["write_requested"] = True
    summary["write_executed"] = False

    if summary.get("db_status") != "ok":
        summary["write_blocked_reason"] = "db_not_ready"
        return persist_ivan_current_import_dry_run_report(summary, output_dir=output_dir or Path(source_dir).parent)

    resolved_source_dir = Path(source_dir)
    funnel_rows = _read_normalized_csv(resolved_source_dir / "funnel_day.csv")
    active_products = _load_active_products() if only_active_products else {}
    active_nm_ids = set(active_products)
    if only_active_products:
        funnel_rows = [row for row in funnel_rows if row.get("nm_id") is not None and int(row["nm_id"]) in active_nm_ids]
    valid_funnel_rows = [row for row in funnel_rows if row.get("date") is not None and row.get("nm_id") is not None]

    with session_scope() as session:
        existing_keys = _load_existing_funnel_keys(session, valid_funnel_rows)
        rows_to_insert_before_empty_guard = [row for row in valid_funnel_rows if (row["date"], int(row["nm_id"])) not in existing_keys]
        rows_to_insert, skipped_empty_rows = _split_insertable_rows_by_empty_guard(rows_to_insert_before_empty_guard)
        loaded_at = datetime.now(timezone.utc)
        insert_rows = [_build_fact_funnel_day_insert_row(row, loaded_at=loaded_at) for row in rows_to_insert]
        rows_inserted = _insert_fact_funnel_day_rows(session, insert_rows)

    if rows_to_insert:
        date_from = min(row["date"] for row in rows_to_insert)
        date_to = max(row["date"] for row in rows_to_insert)
        mart_summary = build_mart_total_report(date_from, date_to, version="v2")
        export_summary = export_streamlit_v1_dataset(date_from, date_to)
    else:
        mart_summary = None
        export_summary = None

    summary.update(
        {
            "insertable_rows_before_empty_guard": len(rows_to_insert_before_empty_guard),
            "skipped_empty_rows": len(skipped_empty_rows),
            "skipped_empty_rows_preview": [_json_ready_row(row) for row in skipped_empty_rows[:10]],
            "rows_to_insert": len(rows_to_insert),
            "rows_can_insert": len(rows_to_insert),
            "write_executed": True,
            "rows_inserted": rows_inserted,
            "mart_rebuild_summary": mart_summary,
            "streamlit_export_summary": export_summary,
            "post_apply_readback": _build_post_apply_readback_summary(rows_to_insert, rows_inserted),
        }
    )
    if output_dir is not None:
        summary = persist_ivan_current_import_dry_run_report(summary, output_dir=output_dir)
    return summary
