from __future__ import annotations

import csv
import json
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
DEFAULT_DUPLICATE_REPORT_DIR = Path("data/manual_imports/ivan_ads_wide/reports")
DEFAULT_SKIPPED_CONFLICTS_REPORT_DIR = DEFAULT_DUPLICATE_REPORT_DIR
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
DUPLICATE_REPORT_COLUMNS = (
    "date",
    "nm_id",
    "supplier_article",
    "campaign_ref",
    "duplicate_count",
    "ad_spend",
    "ad_atbs",
    "ad_cart_ctr",
    "ad_cost_per_cart",
    "ad_views",
    "ad_cpm",
    "ad_spend_values",
    "ad_atbs_values",
    "ad_cart_ctr_values",
    "ad_cost_per_cart_values",
    "ad_views_values",
    "ad_cpm_values",
    "rows_identical",
    "source_row_number",
    "source_section",
    "source_group_index",
    "source_column_start",
    "raw_campaign_header",
    "raw_archive_header",
    "raw_date",
    "raw_nm_id",
    "raw_supplier_article",
    "raw_values_json",
)


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


def _normalize_dedupe_mode(dedupe_mode: str | None) -> str | None:
    if dedupe_mode is None:
        return None
    normalized = dedupe_mode.strip().lower()
    if normalized != "exact":
        raise ValueError(f"Unsupported dedupe mode: {dedupe_mode}")
    return normalized


def _serialize_decimal_list(rows: list[dict[str, Any]], field_name: str) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for row in rows:
        value = row.get(field_name)
        serialized = "null" if value is None else format(value, "f") if isinstance(value, Decimal) else str(value)
        if serialized in seen:
            continue
        seen.add(serialized)
        values.append(serialized)
    return " | ".join(values)


def _serialize_scalar(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _build_raw_values_json(
    *,
    group_definition: WideGroupDefinition,
    row_values: list[Any],
    raw_headers: tuple[str, ...],
) -> str:
    payload: dict[str, Any] = {
        "article_cell": row_values[group_definition.article_column_index] if group_definition.article_column_index < len(row_values) else None,
        "metric_cells": {},
    }
    for field_name, metric_index in group_definition.metric_column_indexes.items():
        payload["metric_cells"][field_name] = {
            "header": raw_headers[metric_index] if metric_index < len(raw_headers) else None,
            "value": row_values[metric_index] if metric_index < len(row_values) else None,
        }
    return json.dumps(payload, ensure_ascii=False)


def _duplicate_exact_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("supplier_article"),
        row.get("title"),
        row.get("campaign_name"),
        *(row.get(field_name) for field_name in AD_METRIC_FIELDS),
    )


def _group_rows_by_duplicate_key(
    rows_long: tuple[dict[str, Any], ...],
) -> dict[tuple[date, int, str], list[tuple[int, dict[str, Any]]]]:
    groups: dict[tuple[date, int, str], list[tuple[int, dict[str, Any]]]] = {}
    for index, row in enumerate(rows_long):
        key = (row["date"], int(row["nm_id"]), str(row["campaign_ref"]))
        groups.setdefault(key, []).append((index, row))
    return {key: grouped_rows for key, grouped_rows in groups.items() if len(grouped_rows) > 1}


def _build_candidate_key_expansion_analysis(
    duplicate_groups: dict[tuple[date, int, str], list[tuple[int, dict[str, Any]]]],
) -> dict[str, dict[str, int]]:
    candidate_fields = (
        ("date+nm_id+campaign_ref+source_section", ("source_section",)),
        ("date+nm_id+campaign_ref+source_group_index", ("source_group_index",)),
        ("date+nm_id+campaign_ref+source_column_start", ("source_column_start",)),
        ("date+nm_id+campaign_ref+raw_campaign_header", ("raw_campaign_header",)),
        ("date+nm_id+campaign_ref+raw_archive_header", ("raw_archive_header",)),
        (
            "date+nm_id+campaign_ref+source_section+source_group_index+source_column_start",
            ("source_section", "source_group_index", "source_column_start"),
        ),
    )
    analysis: dict[str, dict[str, int]] = {}
    for label, fields in candidate_fields:
        remaining_conflicting = 0
        remaining_duplicate = 0
        for grouped_rows in duplicate_groups.values():
            expanded: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
            for _index, row in grouped_rows:
                suffix_key = tuple(row.get(field_name) for field_name in fields)
                expanded.setdefault(suffix_key, []).append(row)
            subgroup_duplicates = [rows for rows in expanded.values() if len(rows) > 1]
            if subgroup_duplicates:
                remaining_duplicate += 1
            if any(len({_duplicate_exact_signature(row) for row in rows}) > 1 for rows in subgroup_duplicates):
                remaining_conflicting += 1
        analysis[label] = {
            "remaining_duplicate_keys": remaining_duplicate,
            "remaining_conflicting_duplicate_keys": remaining_conflicting,
        }
    return analysis


def build_ivan_ads_wide_duplicate_report(parsed: ParsedIvanAdsWideCsv) -> dict[str, Any]:
    duplicate_groups = _group_rows_by_duplicate_key(parsed.rows_long)
    top_dates: Counter[str] = Counter()
    top_nm_ids: Counter[int] = Counter()
    top_campaign_refs: Counter[str] = Counter()
    duplicate_group_rows: list[dict[str, Any]] = []
    duplicate_source_rows: list[dict[str, Any]] = []
    exact_key_count = 0
    conflicting_key_count = 0
    duplicate_extra_row_count = 0

    for (row_date, nm_id, campaign_ref), grouped_rows in sorted(
        duplicate_groups.items(),
        key=lambda item: (item[0][0], item[0][1], item[0][2]),
    ):
        rows_only = [row for _index, row in grouped_rows]
        rows_identical = len({_duplicate_exact_signature(row) for row in rows_only}) == 1
        if rows_identical:
            exact_key_count += 1
        else:
            conflicting_key_count += 1
        duplicate_extra_row_count += len(rows_only) - 1
        top_dates[row_date.isoformat()] += 1
        top_nm_ids[nm_id] += 1
        top_campaign_refs[campaign_ref] += 1
        group_summary = {
            "date": row_date.isoformat(),
            "nm_id": nm_id,
            "supplier_article": next((row.get("supplier_article") for row in rows_only if row.get("supplier_article")), None),
            "campaign_ref": campaign_ref,
            "duplicate_count": len(rows_only),
            "ad_spend_values": _serialize_decimal_list(rows_only, "ad_spend"),
            "ad_atbs_values": _serialize_decimal_list(rows_only, "ad_atbs"),
            "ad_cart_ctr_values": _serialize_decimal_list(rows_only, "ad_cart_ctr"),
            "ad_cost_per_cart_values": _serialize_decimal_list(rows_only, "ad_cost_per_cart"),
            "ad_views_values": _serialize_decimal_list(rows_only, "ad_views"),
            "ad_cpm_values": _serialize_decimal_list(rows_only, "ad_cpm"),
            "rows_identical": rows_identical,
        }
        duplicate_group_rows.append(group_summary)
        for _index, row in grouped_rows:
            duplicate_source_rows.append(
                {
                    **group_summary,
                    "ad_spend": _serialize_scalar(row.get("ad_spend")),
                    "ad_atbs": _serialize_scalar(row.get("ad_atbs")),
                    "ad_cart_ctr": _serialize_scalar(row.get("ad_cart_ctr")),
                    "ad_cost_per_cart": _serialize_scalar(row.get("ad_cost_per_cart")),
                    "ad_views": _serialize_scalar(row.get("ad_views")),
                    "ad_cpm": _serialize_scalar(row.get("ad_cpm")),
                    "source_row_number": row.get("source_row_number"),
                    "source_section": row.get("source_section"),
                    "source_group_index": row.get("source_group_index"),
                    "source_column_start": row.get("source_column_start"),
                    "raw_campaign_header": row.get("raw_campaign_header"),
                    "raw_archive_header": row.get("raw_archive_header"),
                    "raw_date": row.get("raw_date"),
                    "raw_nm_id": row.get("raw_nm_id"),
                    "raw_supplier_article": row.get("raw_supplier_article"),
                    "raw_values_json": row.get("raw_values_json"),
                }
            )

    return {
        "duplicate_key_count": len(duplicate_group_rows),
        "duplicate_exact_key_count": exact_key_count,
        "duplicate_conflicting_key_count": conflicting_key_count,
        "duplicate_extra_row_count": duplicate_extra_row_count,
        "top_dates_with_duplicates": [
            {"date": duplicate_date, "duplicate_keys": count}
            for duplicate_date, count in top_dates.most_common(10)
        ],
        "top_nm_ids_with_duplicates": [
            {"nm_id": duplicate_nm_id, "duplicate_keys": count}
            for duplicate_nm_id, count in top_nm_ids.most_common(10)
        ],
        "top_campaign_refs_with_duplicates": [
            {"campaign_ref": duplicate_campaign_ref, "duplicate_keys": count}
            for duplicate_campaign_ref, count in top_campaign_refs.most_common(10)
        ],
        "candidate_key_expansion_analysis": _build_candidate_key_expansion_analysis(duplicate_groups),
        "duplicate_examples": duplicate_group_rows[:30],
        "duplicate_groups": duplicate_group_rows,
        "duplicate_rows": duplicate_source_rows,
    }


def write_ivan_ads_wide_duplicate_report(
    parsed: ParsedIvanAdsWideCsv,
    *,
    output_path: str | Path | None = None,
) -> Path:
    duplicate_report = build_ivan_ads_wide_duplicate_report(parsed)
    report_path = Path(output_path) if output_path is not None else (
        DEFAULT_DUPLICATE_REPORT_DIR / f"ivan_ads_wide_duplicates_{date.today().isoformat()}.csv"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=DUPLICATE_REPORT_COLUMNS)
        writer.writeheader()
        for row in duplicate_report["duplicate_rows"]:
            writer.writerow({column: row.get(column) for column in DUPLICATE_REPORT_COLUMNS})
    return report_path


def write_ivan_ads_wide_skipped_conflicts_report(
    parsed: ParsedIvanAdsWideCsv,
    *,
    dedupe_mode: str | None,
    output_path: str | Path | None = None,
) -> Path:
    prepared_rows = _prepare_rows_for_import(parsed, dedupe_mode=dedupe_mode, skip_conflicts=True)
    report_path = Path(output_path) if output_path is not None else (
        DEFAULT_SKIPPED_CONFLICTS_REPORT_DIR / f"ivan_ads_wide_skipped_conflicts_{date.today().isoformat()}.csv"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=DUPLICATE_REPORT_COLUMNS)
        writer.writeheader()
        for row in prepared_rows["conflicting_rows"]:
            writer.writerow(
                {
                    "date": row["date"].isoformat(),
                    "nm_id": row["nm_id"],
                    "supplier_article": row.get("supplier_article"),
                    "campaign_ref": row.get("campaign_ref"),
                    "duplicate_count": None,
                    "ad_spend": _serialize_scalar(row.get("ad_spend")),
                    "ad_atbs": _serialize_scalar(row.get("ad_atbs")),
                    "ad_cart_ctr": _serialize_scalar(row.get("ad_cart_ctr")),
                    "ad_cost_per_cart": _serialize_scalar(row.get("ad_cost_per_cart")),
                    "ad_views": _serialize_scalar(row.get("ad_views")),
                    "ad_cpm": _serialize_scalar(row.get("ad_cpm")),
                    "ad_spend_values": None,
                    "ad_atbs_values": None,
                    "ad_cart_ctr_values": None,
                    "ad_cost_per_cart_values": None,
                    "ad_views_values": None,
                    "ad_cpm_values": None,
                    "rows_identical": False,
                    "source_row_number": row.get("source_row_number"),
                    "source_section": row.get("source_section"),
                    "source_group_index": row.get("source_group_index"),
                    "source_column_start": row.get("source_column_start"),
                    "raw_campaign_header": row.get("raw_campaign_header"),
                    "raw_archive_header": row.get("raw_archive_header"),
                    "raw_date": row.get("raw_date"),
                    "raw_nm_id": row.get("raw_nm_id"),
                    "raw_supplier_article": row.get("raw_supplier_article"),
                    "raw_values_json": row.get("raw_values_json"),
                }
            )
    return report_path


def _prepare_rows_for_import(
    parsed: ParsedIvanAdsWideCsv,
    *,
    dedupe_mode: str | None,
    skip_conflicts: bool = False,
) -> dict[str, Any]:
    normalized_dedupe_mode = _normalize_dedupe_mode(dedupe_mode)
    if skip_conflicts and normalized_dedupe_mode != "exact":
        raise ValueError("--skip-conflicts requires --dedupe exact")
    duplicate_groups = _group_rows_by_duplicate_key(parsed.rows_long)
    exact_duplicate_indexes_to_drop: set[int] = set()
    conflicting_duplicate_indexes_to_drop: set[int] = set()
    conflicting_duplicate_key_count = 0
    conflicting_duplicate_rows: list[dict[str, Any]] = []
    conflicting_dates: Counter[str] = Counter()
    conflicting_nm_ids: Counter[int] = Counter()
    conflicting_campaign_refs: Counter[str] = Counter()

    for (row_date, nm_id, campaign_ref), grouped_rows in duplicate_groups.items():
        rows_only = [row for _index, row in grouped_rows]
        if len({_duplicate_exact_signature(row) for row in rows_only}) == 1:
            if normalized_dedupe_mode == "exact":
                exact_duplicate_indexes_to_drop.update(index for index, _row in grouped_rows[1:])
        else:
            conflicting_duplicate_key_count += 1
            if skip_conflicts:
                for index, row in grouped_rows:
                    if index in exact_duplicate_indexes_to_drop:
                        continue
                    conflicting_duplicate_indexes_to_drop.add(index)
                    conflicting_duplicate_rows.append(row)
                conflicting_dates[row_date.isoformat()] += len(grouped_rows)
                conflicting_nm_ids[nm_id] += len(grouped_rows)
                conflicting_campaign_refs[campaign_ref] += len(grouped_rows)

    rows_after_exact_dedupe = tuple(
        row for index, row in enumerate(parsed.rows_long) if index not in exact_duplicate_indexes_to_drop
    )
    selected_rows = tuple(
        row
        for index, row in enumerate(parsed.rows_long)
        if index not in exact_duplicate_indexes_to_drop and index not in conflicting_duplicate_indexes_to_drop
    )
    return {
        "dedupe_mode": normalized_dedupe_mode,
        "skip_conflicts": skip_conflicts,
        "rows_selected": selected_rows,
        "rows_after_exact_dedupe": rows_after_exact_dedupe,
        "rows_dropped_by_exact_dedupe": len(exact_duplicate_indexes_to_drop),
        "conflicting_duplicate_key_count": conflicting_duplicate_key_count,
        "conflicting_rows_skipped": len(conflicting_duplicate_indexes_to_drop),
        "conflicting_rows": tuple(conflicting_duplicate_rows),
        "import_quality": "PARTIAL_CONFLICTS_SKIPPED" if skip_conflicts and conflicting_duplicate_indexes_to_drop else "FULL",
        "conflicting_dates": [
            {"date": duplicate_date, "rows_skipped": count}
            for duplicate_date, count in conflicting_dates.most_common(10)
        ],
        "conflicting_nm_ids": [
            {"nm_id": duplicate_nm_id, "rows_skipped": count}
            for duplicate_nm_id, count in conflicting_nm_ids.most_common(10)
        ],
        "conflicting_campaign_refs": [
            {"campaign_ref": duplicate_campaign_ref, "rows_skipped": count}
            for duplicate_campaign_ref, count in conflicting_campaign_refs.most_common(10)
        ],
    }


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
    current_archive_header: str | None = None
    for source_row_number, raw_row in enumerate(rows[1:], start=2):
        if not any(_parse_text(cell) is not None for cell in raw_row):
            continue
        if _is_header_row(raw_row):
            section_index += 1
            continue
        row_date = _parse_date(raw_row[0] if raw_row else None)
        if row_date is None:
            non_empty_cells = [_parse_text(cell) for cell in raw_row]
            current_archive_header = " | ".join(cell for cell in non_empty_cells if cell) or current_archive_header
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
                "source_row_number": source_row_number,
                "source_section": section_index,
                "source_group_index": group_definition.group_index,
                "source_column_start": group_definition.article_column_index + 1,
                "raw_campaign_header": raw_headers[group_definition.article_column_index] if group_definition.article_column_index < len(raw_headers) else None,
                "raw_archive_header": current_archive_header,
                "raw_date": row_values[0] if row_values else None,
                "raw_nm_id": row_values[group_definition.article_column_index] if group_definition.article_column_index < len(row_values) else None,
                "raw_supplier_article": None,
                "raw_values_json": _build_raw_values_json(
                    group_definition=group_definition,
                    row_values=row_values,
                    raw_headers=tuple(raw_headers),
                ),
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
    duplicate_report = build_ivan_ads_wide_duplicate_report(parsed)
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
        "duplicate_key_count": duplicate_report["duplicate_key_count"],
        "duplicate_exact_key_count": duplicate_report["duplicate_exact_key_count"],
        "duplicate_conflicting_key_count": duplicate_report["duplicate_conflicting_key_count"],
        "top_dates_with_duplicates": duplicate_report["top_dates_with_duplicates"],
        "top_nm_ids_with_duplicates": duplicate_report["top_nm_ids_with_duplicates"],
        "top_campaign_refs_with_duplicates": duplicate_report["top_campaign_refs_with_duplicates"],
        "candidate_key_expansion_analysis": duplicate_report["candidate_key_expansion_analysis"],
        "duplicate_key_examples": duplicate_report["duplicate_examples"],
        "can_apply_with_dedupe_exact": duplicate_report["duplicate_conflicting_key_count"] == 0 and bool(parsed.rows_long),
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


def build_ivan_ads_wide_import_dry_run_summary(
    parsed: ParsedIvanAdsWideCsv,
    *,
    dedupe_mode: str | None = None,
    skip_conflicts: bool = False,
) -> dict[str, Any]:
    if not parsed.found_date_column:
        raise ValueError("В файле не найдена ключевая колонка 'Дата'.")
    if not parsed.found_group_article_alias:
        raise ValueError("В файле не найдена ключевая колонка 'Артикул' / 'Артикул WB' внутри wide-групп.")
    if parsed.group_count == 0:
        raise ValueError("В файле не найдены рекламные wide-группы.")
    if not parsed.rows_long:
        raise ValueError("В файле нет ни одной строки с полезными рекламными метриками.")

    duplicate_report = build_ivan_ads_wide_duplicate_report(parsed)
    prepared_rows = _prepare_rows_for_import(parsed, dedupe_mode=dedupe_mode, skip_conflicts=skip_conflicts)
    selected_rows = prepared_rows["rows_selected"]

    try:
        with session_scope() as session:
            existing_keys = _load_existing_ads_wide_keys(session, selected_rows)
        db_status = "ok"
        db_error = None
    except Exception as exc:
        existing_keys = set()
        db_status = "db_unavailable"
        db_error = str(exc)

    campaign_ref_counts = Counter(str(row["campaign_ref"]) for row in selected_rows)
    can_apply_with_dedupe_exact = duplicate_report["duplicate_conflicting_key_count"] == 0 and bool(selected_rows)
    can_apply = bool(selected_rows) and (
        duplicate_report["duplicate_key_count"] == 0
        or (
            prepared_rows["dedupe_mode"] == "exact"
            and (
                duplicate_report["duplicate_conflicting_key_count"] == 0
                or prepared_rows["skip_conflicts"] is True
            )
        )
    )
    return {
        "mode": "dry-run",
        "write_requested": False,
        "write_executed": False,
        "dedupe_mode": prepared_rows["dedupe_mode"] or "off",
        "skip_conflicts": prepared_rows["skip_conflicts"],
        "target_table": TARGET_TABLE_NAME,
        "tables_affected": [TARGET_TABLE_NAME],
        "import_source": IVAN_ADS_WIDE_IMPORT_SOURCE,
        "data_status": IVAN_ADS_WIDE_DATA_STATUS,
        "source_status": IVAN_ADS_WIDE_IMPORT_SOURCE,
        "import_quality": prepared_rows["import_quality"],
        "db_status": db_status,
        "db_error": db_error,
        "original_long_rows": len(parsed.rows_long),
        "after_exact_dedupe_rows": len(prepared_rows["rows_after_exact_dedupe"]),
        "conflicting_keys_count": duplicate_report["duplicate_conflicting_key_count"],
        "conflicting_rows_skipped": prepared_rows["conflicting_rows_skipped"],
        "clean_rows_to_import": len(selected_rows),
        "rows_found_total": len(parsed.rows_long),
        "rows_planned_for_import": len(selected_rows),
        "rows_already_in_db": len(existing_keys),
        "rows_dropped_by_exact_dedupe": prepared_rows["rows_dropped_by_exact_dedupe"],
        "duplicate_key_count": duplicate_report["duplicate_key_count"],
        "duplicate_exact_key_count": duplicate_report["duplicate_exact_key_count"],
        "duplicate_conflicting_key_count": duplicate_report["duplicate_conflicting_key_count"],
        "top_dates_with_duplicates": duplicate_report["top_dates_with_duplicates"],
        "top_nm_ids_with_duplicates": duplicate_report["top_nm_ids_with_duplicates"],
        "top_campaign_refs_with_duplicates": duplicate_report["top_campaign_refs_with_duplicates"],
        "candidate_key_expansion_analysis": duplicate_report["candidate_key_expansion_analysis"],
        "duplicate_key_examples": duplicate_report["duplicate_examples"],
        "conflicting_dates": prepared_rows["conflicting_dates"],
        "conflicting_nm_ids": prepared_rows["conflicting_nm_ids"],
        "conflicting_campaign_refs": prepared_rows["conflicting_campaign_refs"],
        "period_min": min((row["date"] for row in selected_rows), default=None).isoformat() if selected_rows else None,
        "period_max": max((row["date"] for row in selected_rows), default=None).isoformat() if selected_rows else None,
        "unique_nm_id_count": len({int(row["nm_id"]) for row in selected_rows}) if selected_rows else 0,
        "wide_groups_found": parsed.group_count,
        "top_campaign_refs": [
            {"campaign_ref": campaign_ref, "rows_count": count}
            for campaign_ref, count in campaign_ref_counts.most_common(10)
        ],
        "rows_missing_key": 0,
        "rows_with_non_zero_ad_metrics": sum(
            1
            for row in selected_rows
            if any(row.get(field_name) not in (None, Decimal("0"), Decimal("0.00"), Decimal("0.000000")) for field_name in AD_METRIC_FIELDS)
        ),
        "can_apply": can_apply,
        "can_apply_with_dedupe_exact": can_apply_with_dedupe_exact,
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


def apply_ivan_ads_wide_import(
    parsed: ParsedIvanAdsWideCsv,
    *,
    dedupe_mode: str | None = None,
    skip_conflicts: bool = False,
) -> dict[str, Any]:
    summary = build_ivan_ads_wide_import_dry_run_summary(
        parsed,
        dedupe_mode=dedupe_mode,
        skip_conflicts=skip_conflicts,
    )
    summary["write_requested"] = True
    summary["write_executed"] = False
    if summary["can_apply"] is not True:
        summary["write_blocked_reason"] = (
            "conflicting_duplicate_keys_in_file"
            if summary["duplicate_conflicting_key_count"] > 0 and not skip_conflicts
            else "no_clean_rows_to_import"
            if summary["clean_rows_to_import"] == 0
            else "duplicate_keys_require_dedupe_exact"
        )
        return summary

    prepared_rows = _prepare_rows_for_import(
        parsed,
        dedupe_mode=dedupe_mode,
        skip_conflicts=skip_conflicts,
    )
    with session_scope() as session:
        loaded_at = datetime.now(timezone.utc)
        insert_rows = [_build_insert_row(row, loaded_at=loaded_at) for row in prepared_rows["rows_selected"]]
        existing_keys_before = _load_existing_ads_wide_keys(session, prepared_rows["rows_selected"])
        _upsert_fact_ivan_ads_wide_rows(session, insert_rows)
        existing_keys_after = _load_existing_ads_wide_keys(session, prepared_rows["rows_selected"])
        if len(existing_keys_after) != len(prepared_rows["rows_selected"]):
            raise RuntimeError(
                "fact_ivan_ads_wide_day read-back mismatch after upsert: "
                f"expected {len(prepared_rows['rows_selected'])} keys, got {len(existing_keys_after)}"
            )

    rows_updated = len(existing_keys_before)
    rows_inserted = len(existing_keys_after - existing_keys_before)
    rows_upserted = rows_inserted + rows_updated

    summary["write_executed"] = True
    summary["rows_inserted"] = rows_inserted
    summary["rows_updated"] = rows_updated
    summary["rows_upserted"] = rows_upserted
    return summary
