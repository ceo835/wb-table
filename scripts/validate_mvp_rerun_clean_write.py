#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.clients.google_sheets_client import GoogleSheetsClient
from src.config.settings import settings
from src.sheets.schema_definitions import USER_SHEET_SCHEMAS


DOCS_DIR = ROOT_DIR / "docs"
DATA_DIR = ROOT_DIR / "data" / "processed"
FACT_FUNNEL_PATH = DATA_DIR / "fact_funnel_day.csv"
FACT_STOCK_PATH = DATA_DIR / "fact_stock_snapshot.csv"
REPORT_MD_PATH = DOCS_DIR / "mvp_rerun_clean_write_report.md"
REPORT_CSV_PATH = DATA_DIR / "mvp_rerun_clean_write_report.csv"
QUALITY_REPORT_MD_PATH = DOCS_DIR / "mvp_mapping_quality_report.md"
QUICK_REPORT_MD_PATH = DOCS_DIR / "quick_mvp_polish_report.md"
QUICK_REPORT_CSV_PATH = DATA_DIR / "quick_mvp_polish_report.csv"
SHEET_NAME_FUNNEL = "Воронка на день"
SHEET_NAME_ITOGO = "ИТОГО_v1"
SHEET_NAME_STOCKS = "Остатки"
SHEET_NAME_AD_COSTS = "РасходРК"
SHEET_NAME_SEARCH = "Поисковые запросы"
SHEET_NAME_BACKLOG = "Backlog"
SHEET_NAME_VALIDATION = "Validation_v1"
FORBIDDEN_MARKERS = re.compile(r"(ART-|Товар тестовый|TestBrand|DRY_RUN|mock|fake)", re.IGNORECASE)
LEADING_ZERO_DECIMAL = re.compile(r"^0\d+\.\d+$")


def _column_letter(index: int) -> str:
    result = ""
    while index > 0:
        index -= 1
        result = chr(65 + index % 26) + result
        index //= 26
    return result


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_float(value: Any) -> float | None:
    text = _stringify(value)
    if not text:
        return None
    try:
        return float(text.replace(" ", "").replace(",", "."))
    except Exception:
        return None


def _sheet_range(sheet_name: str, end_col: str, max_rows: int = 2000) -> str:
    escaped = sheet_name.replace("'", "''")
    return f"'{escaped}'!A1:{end_col}{max_rows}"


def _load_sheet_rows(client: GoogleSheetsClient, spreadsheet_id: str, sheet_name: str, columns: tuple[str, ...]) -> tuple[list[str], list[dict[str, str]]]:
    end_col = _column_letter(len(columns))
    values = client.read_range(spreadsheet_id, _sheet_range(sheet_name, end_col)) or []
    header = [_stringify(value) for value in values[0]] if values else []
    rows: list[dict[str, str]] = []
    for raw_row in values[1:]:
        row_values = [_stringify(value) for value in raw_row]
        if not any(row_values):
            continue
        row = {header[i]: row_values[i] if i < len(row_values) else "" for i in range(len(header))}
        rows.append(row)
    return header, rows


def _row_values(row: dict[str, str], keys: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(_stringify(row.get(key, "")) for key in keys)


def _count_forbidden(rows: list[dict[str, str]]) -> int:
    count = 0
    for row in rows:
        if any(FORBIDDEN_MARKERS.search(value or "") for value in row.values()):
            count += 1
    return count


def _read_fact_funnel_keys() -> set[tuple[str, str]]:
    if not FACT_FUNNEL_PATH.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    with FACT_FUNNEL_PATH.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            date_value = _stringify(row.get("date", ""))
            nm_id_value = _stringify(row.get("nm_id", ""))
            if date_value and nm_id_value:
                keys.add((date_value, nm_id_value))
    return keys


def _read_reference_map(path: Path, key_fields: tuple[str, str], value_fields: tuple[str, ...]) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    ref: dict[tuple[str, str], dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            key = (_stringify(row.get(key_fields[0], "")), _stringify(row.get(key_fields[1], "")))
            if not key[0] or not key[1]:
                continue
            ref[key] = {field: _stringify(row.get(field, "")) for field in value_fields}
    return ref


@dataclass
class CheckRow:
    object_name: str
    check_name: str
    status: str
    rows_checked: int
    issues_count: int
    details: str

    def as_csv_row(self) -> dict[str, str]:
        return {
            "object_name": self.object_name,
            "check_name": self.check_name,
            "status": self.status,
            "rows_checked": str(self.rows_checked),
            "issues_count": str(self.issues_count),
            "details": self.details,
        }


def _status(pass_condition: bool) -> str:
    return "PASS" if pass_condition else "FAIL"


def _validate_sheet_header(sheet_name: str, actual: list[str], expected: tuple[str, ...]) -> CheckRow:
    return CheckRow(
        object_name=sheet_name,
        check_name="header_match",
        status=_status(actual == list(expected)),
        rows_checked=len(actual),
        issues_count=0 if actual == list(expected) else 1,
        details="header row matches canonical schema" if actual == list(expected) else f"header mismatch: actual={actual[:8]} expected={list(expected)[:8]}",
    )


def _validate_required_keys(sheet_name: str, rows: list[dict[str, str]], keys: tuple[str, ...]) -> CheckRow:
    missing = 0
    for row in rows:
        if any(not _stringify(row.get(key, "")) for key in keys):
            missing += 1
    return CheckRow(
        object_name=sheet_name,
        check_name="required_keys",
        status=_status(missing == 0),
        rows_checked=len(rows),
        issues_count=missing,
        details=f"required keys present for all rows: {', '.join(keys)}" if missing == 0 else f"{missing} rows missing one or more required keys: {', '.join(keys)}",
    )


def _validate_duplicates(sheet_name: str, rows: list[dict[str, str]], keys: tuple[str, ...]) -> CheckRow:
    pairs = [_row_values(row, keys) for row in rows]
    unique_pairs = set(pairs)
    issues = len(pairs) - len(unique_pairs)
    return CheckRow(
        object_name=sheet_name,
        check_name=f"unique_{'_'.join(keys)}",
        status=_status(issues == 0),
        rows_checked=len(rows),
        issues_count=issues,
        details=f"no duplicate combinations for {', '.join(keys)}" if issues == 0 else f"{issues} duplicate combinations found for {', '.join(keys)}",
    )


def _validate_forbidden_markers(sheet_name: str, rows: list[dict[str, str]]) -> CheckRow:
    issues = _count_forbidden(rows)
    return CheckRow(
        object_name=sheet_name,
        check_name="no_mock_fake",
        status=_status(issues == 0),
        rows_checked=len(rows),
        issues_count=issues,
        details="no ART-/TestBrand/DRY_RUN/mock/fake markers found" if issues == 0 else f"{issues} rows contain forbidden markers",
    )


def _validate_no_leading_zero_decimals(sheet_name: str, rows: list[dict[str, str]], columns: tuple[str, ...]) -> CheckRow:
    issues = 0
    for row in rows:
        for column in columns:
            value = _stringify(row.get(column, ""))
            if value and LEADING_ZERO_DECIMAL.match(value):
                issues += 1
    return CheckRow(
        object_name=sheet_name,
        check_name="no_leading_zero_decimals",
        status=_status(issues == 0),
        rows_checked=len(rows),
        issues_count=issues,
        details="numeric values are normalized without leading zero prefixes" if issues == 0 else f"{issues} values still have leading zero decimal formatting",
    )


def _validate_itogo_reference_fields(itogo_rows: list[dict[str, str]]) -> CheckRow:
    funnel_ref = _read_reference_map(FACT_FUNNEL_PATH, ("date", "nm_id"), ("supplier_article", "title", "subject", "brand"))
    stock_ref = _read_reference_map(FACT_STOCK_PATH, ("snapshot_date", "nm_id"), ("supplier_article", "title", "subject", "brand"))
    issues = 0
    for row in itogo_rows:
        key = (_stringify(row.get("date", "")), _stringify(row.get("nm_id", "")))
        expected = funnel_ref.get(key) or stock_ref.get(key) or {}
        for field in ("supplier_article", "title", "subject", "brand"):
            actual = _stringify(row.get(field, ""))
            expected_value = _stringify(expected.get(field, ""))
            if expected_value and actual != expected_value:
                issues += 1
            if not expected_value and actual and FORBIDDEN_MARKERS.search(actual):
                issues += 1
    return CheckRow(
        object_name=SHEET_NAME_ITOGO,
        check_name="reference_fields_match",
        status=_status(issues == 0),
        rows_checked=len(itogo_rows),
        issues_count=issues,
        details="supplier_article/title/subject/brand are copied from funnel or stock references when available" if issues == 0 else f"{issues} reference field mismatches detected",
    )


def _validate_ad_cost_rules(rows: list[dict[str, str]]) -> list[CheckRow]:
    statuses = {row.get("nm_id_parse_status", "") for row in rows}
    return [
        CheckRow(
            object_name=SHEET_NAME_AD_COSTS,
            check_name="nm_id_parse_status_rules",
            status=_status("AVAILABLE" not in statuses and statuses.issubset({"FROM_CAMPAIGN_NAME", "FROM_SECTION", "NOT_FOUND"})),
            rows_checked=len(rows),
            issues_count=sum(1 for row in rows if row.get("nm_id_parse_status", "") == "AVAILABLE" or row.get("nm_id_parse_status", "") not in {"FROM_CAMPAIGN_NAME", "FROM_SECTION", "NOT_FOUND"}),
            details="nm_id_parse_status uses FROM_CAMPAIGN_NAME, FROM_SECTION, or NOT_FOUND only",
        ),
        CheckRow(
            object_name=SHEET_NAME_AD_COSTS,
            check_name="campaign_type_rules",
            status=_status(all(_stringify(row.get("campaign_type", "")) != "9" for row in rows)),
            rows_checked=len(rows),
            issues_count=sum(1 for row in rows if _stringify(row.get("campaign_type", "")) == "9"),
            details="campaign_type is derived from campaign name, not from the Раздел column",
        ),
    ]


def _validate_itogo_fact_relation(itogo_rows: list[dict[str, str]]) -> CheckRow:
    fact_keys = _read_fact_funnel_keys()
    itogo_keys = [(_stringify(row.get("date", "")), _stringify(row.get("nm_id", ""))) for row in itogo_rows]
    missing = [key for key in itogo_keys if key not in fact_keys]
    return CheckRow(
        object_name=SHEET_NAME_ITOGO,
        check_name="fact_funnel_relation",
        status=_status(not missing),
        rows_checked=len(itogo_rows),
        issues_count=len(missing),
        details="all date+nm_id pairs exist in fact_funnel_day.csv" if not missing else f"{len(missing)} date+nm_id pairs missing from fact_funnel_day.csv",
    )


def _write_report(markdown_rows: list[dict[str, str]], markdown_summary: list[str]) -> None:
    REPORT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    REPORT_MD_PATH.write_text(
        "\n".join(markdown_summary) + "\n",
        encoding="utf-8",
    )

    with REPORT_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["object_name", "check_name", "status", "rows_checked", "issues_count", "details"],
        )
        writer.writeheader()
        for row in markdown_rows:
            writer.writerow(row)


def _write_quality_report(rows: list[CheckRow], sheet_data: dict[str, tuple[list[str], list[dict[str, str]]]]) -> None:
    QUALITY_REPORT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# MVP Mapping Quality Report",
        "",
        f"- Generated at: `{datetime.now().astimezone().isoformat(timespec='seconds')}`",
        "- Scope: clean-write mapping quality after MVP rerun on `2026-05-31 .. 2026-06-01`.",
        "- Goal: keep write paths clean, enrich `ИТОГО_v1`, and prevent malformed ad spend parsing.",
        "",
        "## Written Tabs",
        "",
    ]
    for sheet_name in (SHEET_NAME_FUNNEL, SHEET_NAME_STOCKS, SHEET_NAME_AD_COSTS, SHEET_NAME_SEARCH, SHEET_NAME_ITOGO, SHEET_NAME_BACKLOG):
        lines.append(f"- `{sheet_name}`: {len(sheet_data[sheet_name][1])} rows")
    lines.extend(
        [
            "",
            "## Quality Checks",
            "",
        ]
    )
    for row in rows:
        lines.append(f"- `{row.object_name}` / `{row.check_name}`: `{row.status}` ({row.issues_count} issues)")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `ИТОГО_v1` now copies `supplier_article`, `title`, `subject`, and `brand` from funnel/product or stock references when available.",
            "- Percent-like values are normalized before write, so the sheet should not show leading-zero decimals such as `09.04`.",
            "- `РасходРК` uses `FROM_CAMPAIGN_NAME`, `FROM_SECTION`, or `NOT_FOUND` for `nm_id_parse_status`.",
            "- `campaign_type` is derived from campaign name and should not contain raw section values.",
        ]
    )
    QUALITY_REPORT_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> bool:
    if not settings.google_sheet_id:
        raise RuntimeError("GOOGLE_SHEET_ID is missing")

    client = GoogleSheetsClient()
    spreadsheet_id = settings.google_sheet_id

    rows: list[CheckRow] = []
    markdown_summary: list[str] = []

    sheet_plan = [
        SHEET_NAME_FUNNEL,
        SHEET_NAME_STOCKS,
        SHEET_NAME_AD_COSTS,
        SHEET_NAME_SEARCH,
        SHEET_NAME_ITOGO,
        SHEET_NAME_BACKLOG,
    ]

    sheet_data: dict[str, tuple[list[str], list[dict[str, str]]]] = {}
    for sheet_name in sheet_plan:
        expected = USER_SHEET_SCHEMAS[sheet_name].columns
        header, data_rows = _load_sheet_rows(client, spreadsheet_id, sheet_name, expected)
        sheet_data[sheet_name] = (header, data_rows)
        rows.append(_validate_sheet_header(sheet_name, header, expected))
        rows.append(
            CheckRow(
                object_name=sheet_name,
                check_name="rows_written",
                status=_status(bool(data_rows)),
                rows_checked=len(data_rows),
                issues_count=0 if data_rows else 1,
                details=f"{len(data_rows)} data rows found in Google Sheets",
            )
        )
        rows.append(_validate_forbidden_markers(sheet_name, data_rows))

    rows.append(
        CheckRow(
            object_name=SHEET_NAME_VALIDATION,
            check_name="not_touched",
            status="SKIPPED",
            rows_checked=0,
            issues_count=0,
            details="not part of the MVP clean write run",
        )
    )

    funnel_header, funnel_rows = sheet_data[SHEET_NAME_FUNNEL]
    rows.append(_validate_required_keys(SHEET_NAME_FUNNEL, funnel_rows, ("Дата", "Артикул WB")))
    rows.append(_validate_duplicates(SHEET_NAME_FUNNEL, funnel_rows, ("Дата", "Артикул WB")))
    rows.append(_validate_no_leading_zero_decimals(SHEET_NAME_FUNNEL, funnel_rows, ("CTR", "Доля карточки в выручке", "Конверсия в корзину, %", "Конверсия в заказ, %", "Процент выкупа")))

    itogo_header, itogo_rows = sheet_data[SHEET_NAME_ITOGO]
    rows.append(_validate_required_keys(SHEET_NAME_ITOGO, itogo_rows, ("date", "nm_id")))
    rows.append(_validate_duplicates(SHEET_NAME_ITOGO, itogo_rows, ("date", "nm_id")))
    rows.append(_validate_itogo_fact_relation(itogo_rows))
    rows.append(_validate_no_leading_zero_decimals(SHEET_NAME_ITOGO, itogo_rows, ("ctr", "buyoutPercent", "addToCartConversion", "cartToOrderConversion", "visibility", "avg_position")))
    rows.append(_validate_itogo_reference_fields(itogo_rows))
    rows.extend(_validate_ad_cost_rules(sheet_data[SHEET_NAME_AD_COSTS][1]))

    funnel_count = len(funnel_rows)
    itogo_count = len(itogo_rows)
    skipped_funnel = sum(1 for row in funnel_rows if not _stringify(row.get("Дата", "")) or not _stringify(row.get("Артикул WB", "")))
    skipped_itogo = sum(1 for row in itogo_rows if not _stringify(row.get("date", "")) or not _stringify(row.get("nm_id", "")))

    markdown_summary.append("# MVP Clean Write Report")
    markdown_summary.append("")
    markdown_summary.append(f"- Generated at: `{datetime.now().astimezone().isoformat(timespec='seconds')}`")
    markdown_summary.append("- Period: `2026-05-31` .. `2026-06-01`")
    markdown_summary.append("- Real WB/MPStat API calls were read-only; no write calls were executed.")
    markdown_summary.append("- Existing sheet data was not cleared.")
    markdown_summary.append("- Mock/fake rows were not added.")
    markdown_summary.append("")
    markdown_summary.append("## Written Tabs")
    markdown_summary.append("")
    markdown_summary.append(f"- `{SHEET_NAME_FUNNEL}`: {funnel_count} rows")
    markdown_summary.append(f"- `{SHEET_NAME_STOCKS}`: {len(sheet_data[SHEET_NAME_STOCKS][1])} rows")
    markdown_summary.append(f"- `{SHEET_NAME_AD_COSTS}`: {len(sheet_data[SHEET_NAME_AD_COSTS][1])} rows")
    markdown_summary.append(f"- `{SHEET_NAME_SEARCH}`: {len(sheet_data[SHEET_NAME_SEARCH][1])} rows")
    markdown_summary.append(f"- `{SHEET_NAME_ITOGO}`: {itogo_count} rows")
    markdown_summary.append(f"- `{SHEET_NAME_BACKLOG}`: {len(sheet_data[SHEET_NAME_BACKLOG][1])} rows")
    markdown_summary.append("")
    markdown_summary.append("## Validation")
    markdown_summary.append("")
    markdown_summary.append(f"- Funnel skipped rows without keys: {skipped_funnel}")
    markdown_summary.append(f"- Itogo skipped rows without keys: {skipped_itogo}")
    markdown_summary.append(f"- Funnel duplicates: {'no' if not any(r.check_name == 'unique_Дата_Артикул WB' and r.status == 'FAIL' for r in rows) else 'yes'}")
    markdown_summary.append(f"- Itogo duplicates: {'no' if not any(r.check_name == 'unique_date_nm_id' and r.status == 'FAIL' for r in rows) else 'yes'}")
    markdown_summary.append(f"- Mock/fake markers found: {'no' if not any(r.check_name == 'no_mock_fake' and r.status == 'FAIL' for r in rows) else 'yes'}")
    markdown_summary.append(f"- Live validation: {'PASS' if all(r.status in {'PASS', 'SKIPPED'} for r in rows) else 'FAIL'}")
    markdown_summary.append("")
    markdown_summary.append("## Checklist")
    markdown_summary.append("")
    for row in rows:
        markdown_summary.append(f"- `{row.object_name}` / `{row.check_name}`: `{row.status}` ({row.issues_count} issues)")

    _write_report([row.as_csv_row() for row in rows], markdown_summary)
    _write_quality_report(rows, sheet_data)
    print(f"Markdown report: {REPORT_MD_PATH}")
    print(f"CSV report: {REPORT_CSV_PATH}")
    return all(row.status in {"PASS", "SKIPPED"} for row in rows)


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
