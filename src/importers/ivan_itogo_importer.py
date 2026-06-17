from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select

from scripts.export_streamlit_v1_dataset import export_streamlit_v1_dataset
from src.db.models import FactFunnelDay
from src.db.models import DimProduct
from src.db.session import session_scope
from src.db.funnel_loader import build_fact_funnel_day_db_row
from src.db.mart_total_report_builder import build_mart_total_report
from src.importers.common import normalize_header
from src.tracked_products import get_tracked_nm_ids


CSV_CANDIDATE_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251")
CSV_CANDIDATE_DELIMITERS = ",;\t"
IVAN_ITOGO_SOURCE_STATUS = "CSV_EXPORT"
IVAN_ITOGO_DATA_STATUS = "REAL_FILE"
IVAN_ITOGO_IMPORT_SOURCE = "IVAN_ITOGO_IMPORT"


@dataclass(frozen=True)
class SafeFieldSpec:
    target_field: str
    aliases: tuple[str, ...]
    parser: Callable[[str | None], Any]


@dataclass(frozen=True)
class ParsedIvanItogoCsv:
    file_path: Path
    encoding: str
    delimiter: str
    rows_read: int
    column_count: int
    raw_headers: tuple[str, ...]
    normalized_headers: tuple[str, ...]
    safe_field_indexes: dict[str, tuple[int, ...]]
    mapped_columns: dict[str, dict[str, Any]]
    rows_normalized: tuple[dict[str, Any], ...]
    duplicate_key_count: int
    duplicate_key_examples: tuple[dict[str, Any], ...]
    blank_header_count: int
    duplicate_header_counts: dict[str, int]
    non_importable_columns: tuple[str, ...]


SAFE_FIELD_SPECS: tuple[SafeFieldSpec, ...] = (
    SafeFieldSpec("supplier_article", ("Артикул продавца",), lambda value: _parse_text(value)),
    SafeFieldSpec("nm_id", ("Артикул WB",), lambda value: _parse_int(value)),
    SafeFieldSpec("date", ("Дата",), lambda value: _parse_date(value)),
    SafeFieldSpec("impressions", ("Показы",), lambda value: _parse_decimal(value)),
    SafeFieldSpec("card_clicks", ("Переходы в карточку",), lambda value: _parse_decimal(value)),
    SafeFieldSpec("cart_count", ("Положили в корзину",), lambda value: _parse_decimal(value)),
    SafeFieldSpec("order_count", ("Заказали, шт",), lambda value: _parse_decimal(value)),
    SafeFieldSpec("ctr", ("CTR", "СиТиАр"), lambda value: _parse_decimal(value)),
    SafeFieldSpec("add_to_cart_conversion", ("Конверсия в корзину, %",), lambda value: _parse_decimal(value)),
    SafeFieldSpec("cart_to_order_conversion", ("Конверсия в заказ, %",), lambda value: _parse_decimal(value)),
    SafeFieldSpec("order_sum", ("Заказали на сумму, ₽",), lambda value: _parse_decimal(value)),
    SafeFieldSpec("local_orders_percent", ("Локальные заказы, %",), lambda value: _parse_decimal(value)),
    SafeFieldSpec("avg_delivery_time", ("Среднее время доставки", "Время доставки"), lambda value: _parse_decimal(value)),
)


SAFE_TARGET_FIELDS = tuple(spec.target_field for spec in SAFE_FIELD_SPECS)
SUPPORTED_IMPORT_SCOPES = ("tracked", "all")


def _parse_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\xa0", " ").replace("\u202f", " ").strip()
    return text or None


def _parse_decimal(value: str | None) -> Decimal | None:
    text = _parse_text(value)
    if text in (None, "-", "—"):
        return None
    normalized = (
        text.replace("&nbsp;", "")
        .replace("\xa0", "")
        .replace("\u202f", "")
        .replace(" ", "")
        .replace("%", "")
        .replace("₽", "")
        .replace(",", ".")
    )
    if not normalized:
        return None
    try:
        return Decimal(normalized)
    except (ArithmeticError, InvalidOperation, ValueError):
        return None


def _parse_int(value: str | None) -> int | None:
    decimal_value = _parse_decimal(value)
    if decimal_value is None:
        return None
    try:
        return int(decimal_value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: str | None) -> date | None:
    text = _parse_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _detect_csv_format(file_path: str | Path) -> tuple[str, str]:
    path = Path(file_path)
    for encoding in CSV_CANDIDATE_ENCODINGS:
        try:
            text = path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        sample = text[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=CSV_CANDIDATE_DELIMITERS)
            return encoding, dialect.delimiter
        except csv.Error:
            return encoding, ","
    raise UnicodeDecodeError("utf-8", b"", 0, 1, "unable to decode CSV with supported encodings")


def _normalize_headers(headers: list[str]) -> tuple[str, ...]:
    return tuple(normalize_header(header) for header in headers)


def _resolve_safe_field_indexes(normalized_headers: tuple[str, ...]) -> tuple[dict[str, tuple[int, ...]], dict[str, dict[str, Any]]]:
    header_positions: dict[str, list[int]] = defaultdict(list)
    for index, header in enumerate(normalized_headers):
        header_positions[header].append(index)

    safe_field_indexes: dict[str, tuple[int, ...]] = {}
    mapped_columns: dict[str, dict[str, Any]] = {}
    for spec in SAFE_FIELD_SPECS:
        indexes: list[int] = []
        matched_aliases: list[str] = []
        for alias in spec.aliases:
            alias_indexes = header_positions.get(alias, [])
            if alias_indexes:
                matched_aliases.append(alias)
                indexes.extend(alias_indexes)
        safe_field_indexes[spec.target_field] = tuple(indexes)
        mapped_columns[spec.target_field] = {
            "aliases": list(spec.aliases),
            "matched_aliases": matched_aliases,
            "indexes": [index + 1 for index in indexes],
            "found": bool(indexes),
        }
    return safe_field_indexes, mapped_columns


def _pick_first_parsed_value(row: list[str], indexes: tuple[int, ...], parser: Callable[[str | None], Any]) -> Any:
    for index in indexes:
        if index >= len(row):
            continue
        parsed = parser(row[index])
        if parsed is not None:
            return parsed
    return None


def _normalize_csv_row(row: list[str], safe_field_indexes: dict[str, tuple[int, ...]]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for spec in SAFE_FIELD_SPECS:
        normalized[spec.target_field] = _pick_first_parsed_value(
            row=row,
            indexes=safe_field_indexes.get(spec.target_field, ()),
            parser=spec.parser,
        )
    normalized["source_file_name"] = None
    normalized["data_status"] = IVAN_ITOGO_DATA_STATUS
    normalized["source_status"] = IVAN_ITOGO_SOURCE_STATUS
    return normalized


def parse_ivan_itogo_csv(file_path: str | Path) -> ParsedIvanItogoCsv:
    resolved_path = Path(file_path)
    encoding, delimiter = _detect_csv_format(resolved_path)
    with resolved_path.open("r", encoding=encoding, newline="") as file_handle:
        reader = csv.reader(file_handle, delimiter=delimiter)
        raw_headers = next(reader, [])
        normalized_headers = _normalize_headers(raw_headers)
        safe_field_indexes, mapped_columns = _resolve_safe_field_indexes(normalized_headers)

        rows_normalized: list[dict[str, Any]] = []
        key_counts: Counter[tuple[date | None, int | None]] = Counter()
        rows_read = 0
        for row in reader:
            if not any(_parse_text(value) is not None for value in row):
                continue
            rows_read += 1
            normalized_row = _normalize_csv_row(row, safe_field_indexes)
            normalized_row["source_file_name"] = resolved_path.name
            rows_normalized.append(normalized_row)
            key_counts[(normalized_row.get("date"), normalized_row.get("nm_id"))] += 1

    duplicate_examples: list[dict[str, Any]] = []
    duplicate_key_count = 0
    for (row_date, nm_id), count in key_counts.items():
        if row_date is None or nm_id is None or count <= 1:
            continue
        duplicate_key_count += 1
        if len(duplicate_examples) < 10:
            duplicate_examples.append(
                {
                    "date": row_date.isoformat(),
                    "nm_id": nm_id,
                    "rows_count": count,
                }
            )

    blank_header_count = sum(1 for header in normalized_headers if not header)
    duplicate_header_counts = {
        header: count
        for header, count in Counter(header for header in normalized_headers if header).items()
        if count > 1
    }
    safe_aliases = {alias for spec in SAFE_FIELD_SPECS for alias in spec.aliases}
    non_importable_columns = tuple(
        sorted(
            {
                header
                for header in normalized_headers
                if header and header not in safe_aliases
            }
        )
    )

    return ParsedIvanItogoCsv(
        file_path=resolved_path,
        encoding=encoding,
        delimiter=delimiter,
        rows_read=rows_read,
        column_count=len(raw_headers),
        raw_headers=tuple(raw_headers),
        normalized_headers=normalized_headers,
        safe_field_indexes=safe_field_indexes,
        mapped_columns=mapped_columns,
        rows_normalized=tuple(rows_normalized),
        duplicate_key_count=duplicate_key_count,
        duplicate_key_examples=tuple(duplicate_examples),
        blank_header_count=blank_header_count,
        duplicate_header_counts=duplicate_header_counts,
        non_importable_columns=non_importable_columns,
    )


def _decimal_to_string(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _json_ready_row(row: dict[str, Any]) -> dict[str, Any]:
    rendered: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, date):
            rendered[key] = value.isoformat()
        elif isinstance(value, Decimal):
            rendered[key] = _decimal_to_string(value)
        else:
            rendered[key] = value
    return rendered


def _build_keyed_rows(rows: tuple[dict[str, Any], ...]) -> dict[tuple[date, int], dict[str, Any]]:
    keyed: dict[tuple[date, int], dict[str, Any]] = {}
    for row in rows:
        row_date = row.get("date")
        nm_id = row.get("nm_id")
        if row_date is None or nm_id is None:
            continue
        keyed[(row_date, nm_id)] = row
    return keyed


def _resolve_scope_nm_ids(scope: str) -> set[int] | None:
    if scope == "all":
        return None
    if scope == "tracked":
        return set(get_tracked_nm_ids())
    raise ValueError(f"Unsupported import scope: {scope}")


def _scope_rows(parsed: ParsedIvanItogoCsv, scope: str) -> dict[str, Any]:
    valid_rows = [
        row
        for row in parsed.rows_normalized
        if row.get("date") is not None and row.get("nm_id") is not None
    ]
    allowed_nm_ids = _resolve_scope_nm_ids(scope)
    if allowed_nm_ids is None:
        scoped_rows = list(valid_rows)
        skipped_rows = []
    else:
        scoped_rows = [row for row in valid_rows if int(row["nm_id"]) in allowed_nm_ids]
        skipped_rows = [row for row in valid_rows if int(row["nm_id"]) not in allowed_nm_ids]

    skipped_nm_ids = sorted({int(row["nm_id"]) for row in skipped_rows if row.get("nm_id") is not None})
    return {
        "scope": scope,
        "valid_rows": valid_rows,
        "scoped_rows": scoped_rows,
        "skipped_rows": skipped_rows,
        "skipped_nm_ids": skipped_nm_ids,
    }


def _build_db_fill_coverage(parsed: ParsedIvanItogoCsv, *, scope_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    keyed_rows = _build_keyed_rows(tuple(scope_rows) if scope_rows is not None else parsed.rows_normalized)
    if not keyed_rows:
        return {
            "db_check_status": "no_valid_keys",
            "potential_fill_impressions": 0,
            "potential_fill_ctr": 0,
        }

    unique_dates = sorted({row_date for row_date, _nm_id in keyed_rows})
    unique_nm_ids = sorted({nm_id for _row_date, nm_id in keyed_rows})

    try:
        with session_scope() as session:
            stmt = (
                select(FactFunnelDay.date, FactFunnelDay.nm_id, FactFunnelDay.impressions, FactFunnelDay.ctr)
                .where(FactFunnelDay.date >= unique_dates[0], FactFunnelDay.date <= unique_dates[-1])
                .where(FactFunnelDay.nm_id.in_(unique_nm_ids))
            )
            db_rows = {
                (row.date, row.nm_id): row
                for row in session.execute(stmt).all()
            }
    except Exception as exc:
        return {
            "db_check_status": "db_unavailable",
            "db_error": str(exc),
            "potential_fill_impressions": 0,
            "potential_fill_ctr": 0,
        }

    potential_fill_impressions = 0
    potential_fill_ctr = 0
    matched_db_rows = 0
    for key, parsed_row in keyed_rows.items():
        db_row = db_rows.get(key)
        if db_row is None:
            continue
        matched_db_rows += 1
        if parsed_row.get("impressions") is not None and db_row.impressions is None:
            potential_fill_impressions += 1
        if parsed_row.get("ctr") is not None and db_row.ctr is None:
            potential_fill_ctr += 1

    return {
        "db_check_status": "ok",
        "matched_db_rows": matched_db_rows,
        "potential_fill_impressions": potential_fill_impressions,
        "potential_fill_ctr": potential_fill_ctr,
    }


def build_ivan_itogo_audit_summary(parsed: ParsedIvanItogoCsv) -> dict[str, Any]:
    keyed_rows = _build_keyed_rows(parsed.rows_normalized)
    valid_dates = sorted({row["date"] for row in parsed.rows_normalized if row.get("date") is not None})
    valid_nm_ids = {row["nm_id"] for row in parsed.rows_normalized if row.get("nm_id") is not None}
    valid_supplier_articles = {
        row["supplier_article"]
        for row in parsed.rows_normalized
        if row.get("supplier_article") is not None
    }
    rows_with_impressions = sum(1 for row in parsed.rows_normalized if row.get("impressions") is not None)
    rows_with_ctr = sum(1 for row in parsed.rows_normalized if row.get("ctr") is not None)
    rows_with_orders = sum(1 for row in parsed.rows_normalized if row.get("order_count") is not None)
    rows_missing_key = sum(
        1
        for row in parsed.rows_normalized
        if row.get("date") is None or row.get("nm_id") is None
    )
    safe_import_fields = [
        {
            "target_field": spec.target_field,
            "aliases": list(spec.aliases),
            "mapped": parsed.mapped_columns[spec.target_field]["found"],
        }
        for spec in SAFE_FIELD_SPECS
    ]

    return {
        "file_path": str(parsed.file_path),
        "encoding": parsed.encoding,
        "delimiter": parsed.delimiter,
        "rows_read": parsed.rows_read,
        "column_count": parsed.column_count,
        "date_values": [item.isoformat() for item in valid_dates],
        "min_date": valid_dates[0].isoformat() if valid_dates else None,
        "max_date": valid_dates[-1].isoformat() if valid_dates else None,
        "unique_date_count": len(valid_dates),
        "unique_nm_id_count": len(valid_nm_ids),
        "unique_supplier_article_count": len(valid_supplier_articles),
        "valid_date_nm_id_rows": len(keyed_rows),
        "rows_missing_key": rows_missing_key,
        "duplicate_date_nm_id_keys": parsed.duplicate_key_count,
        "duplicate_date_nm_id_examples": list(parsed.duplicate_key_examples),
        "rows_with_impressions": rows_with_impressions,
        "rows_with_ctr": rows_with_ctr,
        "rows_with_order_count": rows_with_orders,
        "mapped_columns": parsed.mapped_columns,
        "safe_import_fields": safe_import_fields,
        "non_importable_columns": list(parsed.non_importable_columns),
        "blank_header_count": parsed.blank_header_count,
        "duplicate_header_counts": parsed.duplicate_header_counts,
        "potentially_importable_rows": len(keyed_rows),
        "preview_rows": [_json_ready_row(row) for row in parsed.rows_normalized[:5]],
    }


def _build_ctr_validation(parsed: ParsedIvanItogoCsv) -> dict[str, Any]:
    warnings_preview: list[dict[str, Any]] = []
    warning_count = 0
    checked_rows = 0
    for row in parsed.rows_normalized:
        impressions = row.get("impressions")
        card_clicks = row.get("card_clicks")
        ctr = row.get("ctr")
        if impressions in (None, Decimal("0")) or card_clicks is None or ctr is None:
            continue
        checked_rows += 1
        expected_ctr = (card_clicks / impressions) * Decimal("100")
        if abs(expected_ctr - ctr) > Decimal("1"):
            warning_count += 1
            if len(warnings_preview) < 10:
                warnings_preview.append(
                    {
                        "date": row["date"].isoformat() if row.get("date") else None,
                        "nm_id": row.get("nm_id"),
                        "impressions": _decimal_to_string(impressions),
                        "card_clicks": _decimal_to_string(card_clicks),
                        "ctr": _decimal_to_string(ctr),
                        "expected_ctr": _decimal_to_string(expected_ctr.quantize(Decimal("0.0001"))),
                    }
                )
    return {
        "ctr_validation_rows_checked": checked_rows,
        "ctr_validation_warning_count": warning_count,
        "ctr_validation_warning_examples": warnings_preview,
    }


def build_ivan_itogo_import_dry_run_summary(parsed: ParsedIvanItogoCsv) -> dict[str, Any]:
    audit_summary = build_ivan_itogo_audit_summary(parsed)
    audit_summary.update(
        {
            "mode": "dry-run",
            "target_table": "fact_funnel_day",
            "write_requested": False,
            "write_executed": False,
            "write_guard": "apply_flag_required",
            "import_source": IVAN_ITOGO_IMPORT_SOURCE,
            "field_scope": list(SAFE_TARGET_FIELDS),
            "db_persisted_fields": [
                "date",
                "nm_id",
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
                "data_status",
                "source_status",
                "loaded_at",
            ],
            "metadata_only_fields": ["supplier_article", "source_file_name"],
        }
    )
    audit_summary.update(_build_ctr_validation(parsed))
    audit_summary.update(_build_db_fill_coverage(parsed))
    return audit_summary


def _build_fact_funnel_day_insert_row(parsed_row: dict[str, Any], *, loaded_at) -> dict[str, Any]:
    source_row = {
        "date": parsed_row.get("date"),
        "nm_id": parsed_row.get("nm_id"),
        "impressions": parsed_row.get("impressions"),
        "card_clicks": parsed_row.get("card_clicks"),
        "cartCount": parsed_row.get("cart_count"),
        "orderCount": parsed_row.get("order_count"),
        "orderSum": parsed_row.get("order_sum"),
        "ctr": parsed_row.get("ctr"),
        "addToCartConversion": parsed_row.get("add_to_cart_conversion"),
        "cartToOrderConversion": parsed_row.get("cart_to_order_conversion"),
        "avg_delivery_time": parsed_row.get("avg_delivery_time"),
        "local_orders_percent": parsed_row.get("local_orders_percent"),
        "data_status": "MANUAL_UPLOAD",
        "source_status": IVAN_ITOGO_IMPORT_SOURCE,
        "loaded_at": loaded_at,
    }
    return build_fact_funnel_day_db_row(source_row)


def _load_existing_funnel_keys(session, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> set[tuple[date, int]]:
    keyed_rows = _build_keyed_rows(tuple(rows))
    if not keyed_rows:
        return set()
    unique_dates = sorted({row_date for row_date, _nm_id in keyed_rows})
    unique_nm_ids = sorted({nm_id for _row_date, nm_id in keyed_rows})
    stmt = (
        select(FactFunnelDay.date, FactFunnelDay.nm_id)
        .where(FactFunnelDay.date >= unique_dates[0], FactFunnelDay.date <= unique_dates[-1])
        .where(FactFunnelDay.nm_id.in_(unique_nm_ids))
    )
    return {(row.date, int(row.nm_id)) for row in session.execute(stmt).all()}


def _load_known_dim_product_nm_ids(session, nm_ids: set[int]) -> set[int]:
    if not nm_ids:
        return set()
    stmt = select(DimProduct.nm_id).where(DimProduct.nm_id.in_(sorted(nm_ids)))
    return {int(row[0]) for row in session.execute(stmt).all() if row and row[0] is not None}


def _plan_insert_missing(
    parsed: ParsedIvanItogoCsv,
    existing_keys: set[tuple[date, int]],
    known_dim_product_nm_ids: set[int],
    *,
    scope: str,
) -> dict[str, Any]:
    scope_data = _scope_rows(parsed, scope)
    scoped_rows = scope_data["scoped_rows"]
    rows_to_insert = [row for row in scoped_rows if (row["date"], row["nm_id"]) not in existing_keys]
    skipped_existing_rows = len(scoped_rows) - len(rows_to_insert)
    missing_dim_product_nm_ids = sorted({int(row["nm_id"]) for row in rows_to_insert if int(row["nm_id"]) not in known_dim_product_nm_ids})
    insert_dates = sorted({row["date"] for row in rows_to_insert})

    return {
        "scope_rows": scoped_rows,
        "rows_to_insert": rows_to_insert,
        "plan_summary": {
            "scope": scope,
            "mode": "insert-missing",
            "valid_date_nm_id_rows": len(_build_keyed_rows(parsed.rows_normalized)),
            "scope_valid_date_nm_id_rows": len(_build_keyed_rows(tuple(scoped_rows))),
            "rows_skipped_out_of_scope": len(scope_data["skipped_rows"]),
            "skipped_scope_nm_ids": scope_data["skipped_nm_ids"],
            "rows_planned_for_insert": len(rows_to_insert),
            "rows_skipped_existing_keys": skipped_existing_rows,
            "rows_skipped_missing_key": sum(
                1 for row in parsed.rows_normalized if row.get("date") is None or row.get("nm_id") is None
            ),
            "rows_with_impressions_planned": sum(1 for row in rows_to_insert if row.get("impressions") is not None),
            "rows_with_ctr_planned": sum(1 for row in rows_to_insert if row.get("ctr") is not None),
            "rows_with_order_count_planned": sum(1 for row in rows_to_insert if row.get("order_count") is not None),
            "insert_dates": [item.isoformat() for item in insert_dates],
            "insert_date_count": len(insert_dates),
            "nm_id_not_found_in_dim_product_count": len(missing_dim_product_nm_ids),
            "nm_id_not_found_in_dim_product": missing_dim_product_nm_ids[:100],
        },
    }


def build_ivan_itogo_insert_missing_summary(parsed: ParsedIvanItogoCsv, *, scope: str = "tracked") -> dict[str, Any]:
    summary = build_ivan_itogo_import_dry_run_summary(parsed)
    summary["mode"] = "insert-missing"
    summary["scope"] = scope

    scope_data = _scope_rows(parsed, scope)
    keyed_rows = _build_keyed_rows(tuple(scope_data["scoped_rows"]))
    summary["rows_skipped_out_of_scope"] = len(scope_data["skipped_rows"])
    summary["skipped_scope_nm_ids"] = scope_data["skipped_nm_ids"]
    summary["scope_valid_date_nm_id_rows"] = len(keyed_rows)
    summary.update(_build_db_fill_coverage(parsed, scope_rows=scope_data["scoped_rows"]))
    if not keyed_rows:
        summary.update(
            {
                "db_check_status": summary.get("db_check_status") or "no_valid_keys",
                "rows_planned_for_insert": 0,
                "rows_skipped_existing_keys": 0,
                "rows_skipped_missing_key": summary.get("rows_missing_key", 0),
                "rows_with_impressions_planned": 0,
                "rows_with_ctr_planned": 0,
                "rows_with_order_count_planned": 0,
                "insert_dates": [],
                "insert_date_count": 0,
                "nm_id_not_found_in_dim_product_count": 0,
                "nm_id_not_found_in_dim_product": [],
            }
        )
        return summary

    try:
        with session_scope() as session:
            existing_keys = _load_existing_funnel_keys(session, scope_data["scoped_rows"])
            known_dim_product_nm_ids = _load_known_dim_product_nm_ids(
                session,
                {int(nm_id) for _row_date, nm_id in keyed_rows},
            )
    except Exception as exc:
        summary.update(
            {
                "db_check_status": "db_unavailable",
                "db_error": str(exc),
                "rows_planned_for_insert": 0,
                "rows_skipped_existing_keys": 0,
                "rows_skipped_missing_key": summary.get("rows_missing_key", 0),
                "rows_with_impressions_planned": 0,
                "rows_with_ctr_planned": 0,
                "rows_with_order_count_planned": 0,
                "insert_dates": [],
                "insert_date_count": 0,
                "nm_id_not_found_in_dim_product_count": 0,
                "nm_id_not_found_in_dim_product": [],
            }
        )
        return summary

    plan = _plan_insert_missing(parsed, existing_keys, known_dim_product_nm_ids, scope=scope)
    summary.update(plan["plan_summary"])
    return summary


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


def apply_ivan_itogo_insert_missing(parsed: ParsedIvanItogoCsv, *, scope: str = "tracked") -> dict[str, Any]:
    summary = build_ivan_itogo_insert_missing_summary(parsed, scope=scope)
    summary["write_requested"] = True
    summary["write_executed"] = False

    if summary.get("db_check_status") != "ok":
        summary["write_blocked_reason"] = "db_check_not_ready"
        return summary

    scope_data = _scope_rows(parsed, scope)
    keyed_rows = _build_keyed_rows(tuple(scope_data["scoped_rows"]))
    with session_scope() as session:
        existing_keys = _load_existing_funnel_keys(session, scope_data["scoped_rows"])
        known_dim_product_nm_ids = _load_known_dim_product_nm_ids(
            session,
            {int(nm_id) for _row_date, nm_id in keyed_rows},
        )
        plan = _plan_insert_missing(parsed, existing_keys, known_dim_product_nm_ids, scope=scope)
        loaded_at = datetime.now(timezone.utc)
        rows_to_insert = [
            _build_fact_funnel_day_insert_row(row, loaded_at=loaded_at)
            for row in plan["rows_to_insert"]
        ]
        rows_inserted = _insert_fact_funnel_day_rows(session, rows_to_insert)

    if plan["rows_to_insert"]:
        date_from = min(row["date"] for row in plan["rows_to_insert"])
        date_to = max(row["date"] for row in plan["rows_to_insert"])
        mart_summary = build_mart_total_report(date_from, date_to, version="v2")
        export_summary = export_streamlit_v1_dataset(date_from, date_to)
    else:
        mart_summary = None
        export_summary = None

    summary.update(plan["plan_summary"])
    summary.update(
        {
            "write_executed": True,
            "rows_inserted": rows_inserted,
            "mart_rebuild_summary": mart_summary,
            "streamlit_export_summary": export_summary,
        }
    )
    return summary
