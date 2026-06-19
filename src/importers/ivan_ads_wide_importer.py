from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.db.models import FactIvanAdsWideDay
from src.db.session import session_scope
from src.importers.common import normalize_header


CSV_CANDIDATE_ENCODINGS = ("utf-8-sig", "utf-8", "cp1251")
CSV_CANDIDATE_DELIMITERS = ",;\t"
IVAN_ADS_WIDE_IMPORT_SOURCE = "IVAN_ADS_WIDE_IMPORT"
IVAN_ADS_WIDE_DATA_STATUS = "MANUAL_UPLOAD"
TARGET_TABLE_NAME = "fact_ivan_ads_wide_day"
DATE_HEADER = "Дата"
GLOBAL_NM_ID_HEADER = "Артикул WB"
GROUP_ARTICLE_ALIASES = ("Артикул WB", "Артикул")

GROUP_METRIC_HEADERS: tuple[tuple[str, str], ...] = (
    ("ad_spend", "Затраты РК/Раньше было (Реальная корзина)"),
    ("ad_atbs", "корзин от этой РК (эффективность РК)"),
    ("ad_cart_ctr", "CTR корзины"),
    ("ad_cost_per_cart", "цена корзин от этой РК (эффективность РК)"),
    ("ad_views", "Показы РК этого артикула"),
    ("ad_cpm", "CPM"),
)
AD_METRIC_FIELDS = tuple(field_name for field_name, _header in GROUP_METRIC_HEADERS)


@dataclass(frozen=True)
class WideGroupDefinition:
    group_index: int
    article_column_index: int
    metric_column_indexes: dict[str, int]


@dataclass(frozen=True)
class ParsedIvanAdsWideCsv:
    file_path: Path
    encoding: str
    delimiter: str
    rows_read: int
    column_count: int
    raw_headers: tuple[str, ...]
    normalized_headers: tuple[str, ...]
    group_count: int
    group_definitions: tuple[WideGroupDefinition, ...]
    rows_long: tuple[dict[str, Any], ...]
    duplicate_key_count: int
    duplicate_key_examples: tuple[dict[str, Any], ...]
    found_date_column: bool
    found_nm_id_column: bool
    found_group_article_alias: bool
    section_count: int


def _parse_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("&nbsp;", " ").replace("\xa0", " ").replace("\u202f", " ").strip()
    return text or None


def _normalize_numeric_text(text: str) -> str:
    cleaned = (
        text.replace("&nbsp;", "")
        .replace("\xa0", "")
        .replace("\u202f", "")
        .replace(" ", "")
        .replace("₽", "")
        .replace("%", "")
        .replace("?", "")
        .replace("�", "")
        .replace(",", ".")
    )
    return "".join(char for char in cleaned if char.isdigit() or char in {".", "-"})


def _parse_decimal(value: Any) -> Decimal | None:
    text = _parse_text(value)
    if text in (None, "-", "—"):
        return None
    normalized = _normalize_numeric_text(text)
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
        integer_value = int(decimal_value)
    except (TypeError, ValueError):
        return None
    return integer_value if integer_value > 0 else None


def _parse_date(value: Any) -> date | None:
    text = _parse_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    for pattern in ("%d.%m.%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
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


def _normalize_headers(headers: list[Any]) -> tuple[str, ...]:
    return tuple(normalize_header(header) for header in headers)


def _is_header_row(raw_row: list[Any]) -> bool:
    normalized = _normalize_headers(raw_row)
    if not normalized:
        return False
    if normalized[0] != DATE_HEADER:
        return False
    return any(header in GROUP_ARTICLE_ALIASES for header in normalized[1:])


def _build_group_definitions(normalized_headers: tuple[str, ...]) -> tuple[WideGroupDefinition, ...]:
    if not normalized_headers or normalized_headers[0] != DATE_HEADER:
        raise ValueError("В файле не найдена ключевая колонка 'Дата'.")

    definitions: list[WideGroupDefinition] = []
    group_index = 0
    for index, header in enumerate(normalized_headers[1:], start=1):
        if header not in GROUP_ARTICLE_ALIASES:
            continue
        metric_indexes: dict[str, int] = {}
        for offset, (field_name, expected_header) in enumerate(GROUP_METRIC_HEADERS, start=1):
            metric_index = index + offset
            if metric_index >= len(normalized_headers):
                metric_indexes = {}
                break
            if normalized_headers[metric_index] != expected_header:
                metric_indexes = {}
                break
            metric_indexes[field_name] = metric_index
        if metric_indexes:
            group_index += 1
            definitions.append(
                WideGroupDefinition(
                    group_index=group_index,
                    article_column_index=index,
                    metric_column_indexes=metric_indexes,
                )
            )
    if not definitions:
        raise ValueError("В файле не найдены repeated wide-группы с колонкой 'Артикул'.")
    return tuple(definitions)


def _row_has_useful_metrics(row: dict[str, Any]) -> bool:
    return any(row.get(field_name) is not None for field_name in AD_METRIC_FIELDS)


def _build_duplicate_examples(rows_long: tuple[dict[str, Any], ...]) -> tuple[int, tuple[dict[str, Any], ...]]:
    key_counts: Counter[tuple[date, int, str]] = Counter()
    for row in rows_long:
        key_counts[(row["date"], int(row["nm_id"]), str(row["campaign_ref"]))] += 1

    duplicate_key_count = 0
    examples: list[dict[str, Any]] = []
    for (row_date, nm_id, campaign_ref), count in key_counts.items():
        if count <= 1:
            continue
        duplicate_key_count += 1
        if len(examples) < 10:
            examples.append(
                {
                    "date": row_date.isoformat(),
                    "nm_id": nm_id,
                    "campaign_ref": campaign_ref,
                    "rows_count": count,
                }
            )
    return duplicate_key_count, tuple(examples)


def parse_ivan_ads_wide_csv(file_path: str | Path) -> ParsedIvanAdsWideCsv:
    resolved_path = Path(file_path)
    encoding, delimiter = _detect_csv_format(resolved_path)
    with resolved_path.open("r", encoding=encoding, newline="") as file_handle:
        rows = list(csv.reader(file_handle, delimiter=delimiter))
    if not rows:
        raise ValueError(f"Input file is empty: {resolved_path}")

    header_row = next((row for row in rows if any(_parse_text(cell) is not None for cell in row)), None)
    if header_row is None:
        raise ValueError(f"Input file is empty: {resolved_path}")

    raw_headers = ["" if value is None else str(value) for value in header_row]
    normalized_headers = _normalize_headers(raw_headers)
    group_definitions = _build_group_definitions(normalized_headers)

    rows_long: list[dict[str, Any]] = []
    rows_read = 0
    section_index = 1
    for raw_row in rows[1:]:
        if not any(_parse_text(cell) is not None for cell in raw_row):
            continue
        if _is_header_row(raw_row):
            section_index += 1
            continue
        row_date = _parse_date(raw_row[0] if raw_row else None)
        if row_date is None:
            continue
        rows_read += 1
        row_values = list(raw_row)
        for group_definition in group_definitions:
            if group_definition.article_column_index >= len(row_values):
                continue
            nm_id = _parse_int(row_values[group_definition.article_column_index])
            if nm_id is None:
                continue
            normalized_row: dict[str, Any] = {
                "date": row_date,
                "nm_id": nm_id,
                "supplier_article": None,
                "title": None,
                "campaign_ref": f"section_{section_index}_group_{group_definition.group_index}",
                "campaign_name": None,
                "data_status": IVAN_ADS_WIDE_DATA_STATUS,
                "source_status": IVAN_ADS_WIDE_IMPORT_SOURCE,
                "source_file_name": resolved_path.name,
            }
            for field_name, metric_index in group_definition.metric_column_indexes.items():
                cell_value = row_values[metric_index] if metric_index < len(row_values) else None
                normalized_row[field_name] = _parse_decimal(cell_value)
            if _row_has_useful_metrics(normalized_row):
                rows_long.append(normalized_row)

    rows_long_tuple = tuple(rows_long)
    duplicate_key_count, duplicate_key_examples = _build_duplicate_examples(rows_long_tuple)
    return ParsedIvanAdsWideCsv(
        file_path=resolved_path,
        encoding=encoding,
        delimiter=delimiter,
        rows_read=rows_read,
        column_count=len(raw_headers),
        raw_headers=tuple(raw_headers),
        normalized_headers=normalized_headers,
        group_count=len(group_definitions),
        group_definitions=group_definitions,
        rows_long=rows_long_tuple,
        duplicate_key_count=duplicate_key_count,
        duplicate_key_examples=duplicate_key_examples,
        found_date_column=normalized_headers[0] == DATE_HEADER,
        found_nm_id_column=GLOBAL_NM_ID_HEADER in normalized_headers,
        found_group_article_alias=any(header in GROUP_ARTICLE_ALIASES for header in normalized_headers[1:]),
        section_count=section_index,
    )


def build_ivan_ads_wide_audit_summary(parsed: ParsedIvanAdsWideCsv) -> dict[str, Any]:
    valid_dates = sorted({row["date"] for row in parsed.rows_long if row.get("date") is not None})
    valid_nm_ids = sorted({int(row["nm_id"]) for row in parsed.rows_long if row.get("nm_id") is not None})
    campaign_refs = sorted({str(row["campaign_ref"]) for row in parsed.rows_long if row.get("campaign_ref")})
    rows_with_non_zero_ad_metrics = sum(
        1
        for row in parsed.rows_long
        if any(row.get(field_name) not in (None, Decimal("0"), Decimal("0.00"), Decimal("0.000000")) for field_name in AD_METRIC_FIELDS)
    )
    return {
        "file_path": str(parsed.file_path),
        "encoding": parsed.encoding,
        "delimiter": parsed.delimiter,
        "found_date_column": parsed.found_date_column,
        "found_nm_id_column": parsed.found_nm_id_column,
        "found_group_article_alias": parsed.found_group_article_alias,
        "rows_read": parsed.rows_read,
        "column_count": parsed.column_count,
        "min_date": valid_dates[0].isoformat() if valid_dates else None,
        "max_date": valid_dates[-1].isoformat() if valid_dates else None,
        "unique_nm_id_count": len(valid_nm_ids),
        "wide_groups_found": parsed.group_count,
        "wide_sections_found": parsed.section_count,
        "campaign_ref_count": len(campaign_refs),
        "rows_with_useful_ad_metrics": len(parsed.rows_long),
        "rows_with_non_zero_ad_metrics": rows_with_non_zero_ad_metrics,
        "duplicate_key_count": parsed.duplicate_key_count,
        "duplicate_key_examples": list(parsed.duplicate_key_examples),
        "preview_rows": [
            {
                key: (value.isoformat() if isinstance(value, date) else format(value, "f") if isinstance(value, Decimal) else value)
                for key, value in row.items()
            }
            for row in parsed.rows_long[:5]
        ],
    }


def _load_existing_ads_wide_keys(session, rows: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> set[tuple[date, int, str]]:
    if not rows:
        return set()
    requested_keys = {(row["date"], int(row["nm_id"]), str(row["campaign_ref"])) for row in rows}
    unique_dates = sorted({row_date for row_date, _nm_id, _campaign_ref in requested_keys})
    unique_nm_ids = sorted({nm_id for _row_date, nm_id, _campaign_ref in requested_keys})
    unique_campaign_refs = sorted({campaign_ref for _row_date, _nm_id, campaign_ref in requested_keys})
    stmt = (
        select(FactIvanAdsWideDay.date, FactIvanAdsWideDay.nm_id, FactIvanAdsWideDay.campaign_ref)
        .where(FactIvanAdsWideDay.date >= unique_dates[0], FactIvanAdsWideDay.date <= unique_dates[-1])
        .where(FactIvanAdsWideDay.nm_id.in_(unique_nm_ids))
        .where(FactIvanAdsWideDay.campaign_ref.in_(unique_campaign_refs))
    )
    return {
        (row.date, int(row.nm_id), str(row.campaign_ref))
        for row in session.execute(stmt).all()
        if (row.date, int(row.nm_id), str(row.campaign_ref)) in requested_keys
    }


def build_ivan_ads_wide_import_dry_run_summary(parsed: ParsedIvanAdsWideCsv) -> dict[str, Any]:
    if not parsed.found_date_column:
        raise ValueError("В файле не найдена ключевая колонка 'Дата'.")
    if not parsed.found_group_article_alias:
        raise ValueError("В файле не найдена ключевая колонка 'Артикул' / 'Артикул WB' внутри wide-групп.")
    if parsed.group_count == 0:
        raise ValueError("В файле не найдены рекламные wide-группы.")
    if not parsed.rows_long:
        raise ValueError("В файле нет ни одной строки с полезными рекламными метриками.")

    try:
        with session_scope() as session:
            existing_keys = _load_existing_ads_wide_keys(session, parsed.rows_long)
        db_status = "ok"
        db_error = None
    except Exception as exc:
        existing_keys = set()
        db_status = "db_unavailable"
        db_error = str(exc)

    campaign_ref_counts = Counter(str(row["campaign_ref"]) for row in parsed.rows_long)
    return {
        "mode": "dry-run",
        "write_requested": False,
        "write_executed": False,
        "target_table": TARGET_TABLE_NAME,
        "tables_affected": [TARGET_TABLE_NAME],
        "import_source": IVAN_ADS_WIDE_IMPORT_SOURCE,
        "data_status": IVAN_ADS_WIDE_DATA_STATUS,
        "db_status": db_status,
        "db_error": db_error,
        "rows_found_total": len(parsed.rows_long),
        "rows_planned_for_import": len(parsed.rows_long),
        "rows_already_in_db": len(existing_keys),
        "duplicate_key_count": parsed.duplicate_key_count,
        "duplicate_key_examples": list(parsed.duplicate_key_examples),
        "period_min": min(row["date"] for row in parsed.rows_long).isoformat(),
        "period_max": max(row["date"] for row in parsed.rows_long).isoformat(),
        "unique_nm_id_count": len({int(row["nm_id"]) for row in parsed.rows_long}),
        "wide_groups_found": parsed.group_count,
        "top_campaign_refs": [
            {"campaign_ref": campaign_ref, "rows_count": count}
            for campaign_ref, count in campaign_ref_counts.most_common(10)
        ],
        "rows_missing_key": 0,
        "rows_with_non_zero_ad_metrics": sum(
            1
            for row in parsed.rows_long
            if any(row.get(field_name) not in (None, Decimal("0"), Decimal("0.00"), Decimal("0.000000")) for field_name in AD_METRIC_FIELDS)
        ),
        "can_apply": parsed.duplicate_key_count == 0 and bool(parsed.rows_long),
    }


def _build_insert_row(row: dict[str, Any], *, loaded_at: datetime) -> dict[str, Any]:
    return {
        "date": row["date"],
        "nm_id": int(row["nm_id"]),
        "supplier_article": row.get("supplier_article"),
        "title": row.get("title"),
        "campaign_ref": str(row["campaign_ref"]),
        "campaign_name": row.get("campaign_name"),
        "ad_spend": row.get("ad_spend"),
        "ad_atbs": row.get("ad_atbs"),
        "ad_cart_ctr": row.get("ad_cart_ctr"),
        "ad_cost_per_cart": row.get("ad_cost_per_cart"),
        "ad_views": row.get("ad_views"),
        "ad_cpm": row.get("ad_cpm"),
        "source_file_name": row.get("source_file_name"),
        "data_status": IVAN_ADS_WIDE_DATA_STATUS,
        "source_status": IVAN_ADS_WIDE_IMPORT_SOURCE,
        "loaded_at": loaded_at,
    }


def _upsert_fact_ivan_ads_wide_rows(session, rows: list[dict[str, Any]], *, batch_size: int = 500) -> int:
    if not rows:
        return 0
    total_upserted = 0
    for index in range(0, len(rows), batch_size):
        chunk = rows[index:index + batch_size]
        stmt = pg_insert(FactIvanAdsWideDay.__table__).values(chunk)
        update_fields = {
            "supplier_article": stmt.excluded.supplier_article,
            "title": stmt.excluded.title,
            "campaign_name": stmt.excluded.campaign_name,
            "ad_spend": stmt.excluded.ad_spend,
            "ad_atbs": stmt.excluded.ad_atbs,
            "ad_cart_ctr": stmt.excluded.ad_cart_ctr,
            "ad_cost_per_cart": stmt.excluded.ad_cost_per_cart,
            "ad_views": stmt.excluded.ad_views,
            "ad_cpm": stmt.excluded.ad_cpm,
            "source_file_name": stmt.excluded.source_file_name,
            "data_status": stmt.excluded.data_status,
            "source_status": stmt.excluded.source_status,
            "loaded_at": stmt.excluded.loaded_at,
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                FactIvanAdsWideDay.__table__.c.date,
                FactIvanAdsWideDay.__table__.c.nm_id,
                FactIvanAdsWideDay.__table__.c.campaign_ref,
            ],
            set_=update_fields,
        )
        result = session.execute(stmt)
        total_upserted += result.rowcount or 0
    return total_upserted


def apply_ivan_ads_wide_import(parsed: ParsedIvanAdsWideCsv) -> dict[str, Any]:
    summary = build_ivan_ads_wide_import_dry_run_summary(parsed)
    summary["write_requested"] = True
    summary["write_executed"] = False
    if parsed.duplicate_key_count > 0:
        summary["write_blocked_reason"] = "duplicate_keys_in_file"
        return summary

    with session_scope() as session:
        loaded_at = datetime.now(timezone.utc)
        insert_rows = [_build_insert_row(row, loaded_at=loaded_at) for row in parsed.rows_long]
        rows_upserted = _upsert_fact_ivan_ads_wide_rows(session, insert_rows)

    summary["write_executed"] = True
    summary["rows_upserted"] = rows_upserted
    return summary
