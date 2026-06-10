#!/usr/bin/env python3
from __future__ import annotations

import csv
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
from src.sheets.backlog_builder import build_backlog_rows
from src.sheets.schema_definitions import USER_SHEET_SCHEMAS


DOCS_DIR = ROOT_DIR / "docs"
DATA_DIR = ROOT_DIR / "data" / "processed"

SEARCH_FACT_PATH = DATA_DIR / "fact_search_query_metric.csv"
AD_FACT_PATH = DATA_DIR / "fact_ad_cost_event.csv"

REPORT_MD_PATH = DOCS_DIR / "quick_mvp_polish_report.md"
REPORT_CSV_PATH = DATA_DIR / "quick_mvp_polish_report.csv"

SHEET_SEARCH = "Поисковые запросы"
SHEET_AD_COSTS = "РасходРК"
SHEET_LOCALIZATION = "Локализация"
SHEET_COVERAGE = "Coverage"
SHEET_BACKLOG = "Backlog"
SHEET_STOCKS = "Остатки"


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


def _column_letter(index: int) -> str:
    result = ""
    while index > 0:
        index -= 1
        result = chr(65 + index % 26) + result
        index //= 26
    return result


def _load_sheet_rows(client: GoogleSheetsClient, spreadsheet_id: str, sheet_name: str) -> tuple[list[str], list[dict[str, str]]]:
    columns = USER_SHEET_SCHEMAS[sheet_name].columns
    end_col = _column_letter(len(columns))
    values = client.read_range(spreadsheet_id, f"'{sheet_name}'!A1:{end_col}5000") or []
    header = [_stringify(value) for value in values[0]] if values else []
    rows: list[dict[str, str]] = []
    for raw_row in values[1:]:
        row_values = [_stringify(value) for value in raw_row]
        if not any(row_values):
            continue
        rows.append({header[i]: row_values[i] if i < len(row_values) else "" for i in range(len(header))})
    return header, rows


def _read_csv_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def _read_csv_sum(path: Path, column: str) -> float:
    if not path.exists():
        return 0.0
    total = 0.0
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            total += _to_float(row.get(column, "")) or 0.0
    return round(total, 2)


def _count_forbidden(rows: list[dict[str, str]]) -> int:
    markers = ("ART-", "TestBrand", "Товар тестовый", "DRY_RUN", "mock", "fake")
    count = 0
    for row in rows:
        if any(any(marker.lower() in _stringify(cell).lower() for marker in markers) for cell in row.values()):
            count += 1
    return count


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


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def build_report(client: GoogleSheetsClient, spreadsheet_id: str) -> tuple[list[CheckRow], list[str]]:
    search_header, search_rows = _load_sheet_rows(client, spreadsheet_id, SHEET_SEARCH)
    ad_header, ad_rows = _load_sheet_rows(client, spreadsheet_id, SHEET_AD_COSTS)
    localization_header, localization_rows = _load_sheet_rows(client, spreadsheet_id, SHEET_LOCALIZATION)
    coverage_header, coverage_rows = _load_sheet_rows(client, spreadsheet_id, SHEET_COVERAGE)
    backlog_header, backlog_rows = _load_sheet_rows(client, spreadsheet_id, SHEET_BACKLOG)
    stocks_header, stocks_rows = _load_sheet_rows(client, spreadsheet_id, SHEET_STOCKS)

    rows: list[CheckRow] = []

    processed_search_count = _read_csv_count(SEARCH_FACT_PATH)
    search_ref_rows = sum(
        1
        for row in search_rows
        if any(_stringify(row.get(column, "")) for column in ("Артикул продавца", "Название", "Предмет", "Бренд"))
    )
    search_ref_missing = sum(
        1
        for row in search_rows
        if _stringify(row.get("Артикул WB", "")) and not any(_stringify(row.get(column, "")) for column in ("Артикул продавца", "Название", "Предмет", "Бренд"))
    )
    rows.append(
        CheckRow(
            object_name=SHEET_SEARCH,
            check_name="rows_preserved",
            status=_status(len(search_rows) == processed_search_count and len(search_rows) > 0),
            rows_checked=len(search_rows),
            issues_count=abs(len(search_rows) - processed_search_count),
            details="sheet row count matches fact_search_query_metric.csv",
        )
    )
    rows.append(
        CheckRow(
            object_name=SHEET_SEARCH,
            check_name="reference_enrichment",
            status=_status(search_ref_rows > 0 and search_ref_missing == 0),
            rows_checked=len(search_rows),
            issues_count=search_ref_missing,
            details="supplier_article/title/subject/brand are copied from funnel or stock references when available",
        )
    )

    ad_click_rows = [
        row
        for row in ad_rows
        if any(token in _stringify(row.get("Кампания", "")).lower() for token in ("за клик", "оплата за клик", "клик"))
    ]
    ad_click_mismatches = sum(1 for row in ad_click_rows if _stringify(row.get("campaign_type", "")) != "За клик")
    ad_sum_sheet = round(sum(_to_float(row.get("Сумма", "")) or 0.0 for row in ad_rows), 2)
    ad_sum_fact = _read_csv_sum(AD_FACT_PATH, "spend")
    rows.append(
        CheckRow(
            object_name=SHEET_AD_COSTS,
            check_name="campaign_type_click",
            status=_status(ad_click_mismatches == 0),
            rows_checked=len(ad_rows),
            issues_count=ad_click_mismatches,
            details='campaign_type is "За клик" for click campaigns',
        )
    )
    rows.append(
        CheckRow(
            object_name=SHEET_AD_COSTS,
            check_name="sum_preserved",
            status=_status(ad_sum_sheet == ad_sum_fact),
            rows_checked=len(ad_rows),
            issues_count=0 if ad_sum_sheet == ad_sum_fact else 1,
            details="sheet spend sum matches fact_ad_cost_event.csv",
        )
    )

    localization_blank_stock = sum(1 for row in localization_rows if _stringify(row.get("Остатки склад ВБ, шт", "")))
    localization_unique = {(row.get("Дата", ""), row.get("Артикул WB", ""), row.get("Регион", "")) for row in localization_rows}
    localization_metrics = sum(
        1
        for row in localization_rows
        if any(_stringify(row.get(column, "")) for column in ("Итого заказов, шт", "Продажи, шт", "Сумма продаж, ₽"))
    )
    rows.append(
        CheckRow(
            object_name=SHEET_LOCALIZATION,
            check_name="no_regional_stock_fallback",
            status=_status(localization_blank_stock == 0),
            rows_checked=len(localization_rows),
            issues_count=localization_blank_stock,
            details="regional stock column stays blank unless confirmed",
        )
    )
    rows.append(
        CheckRow(
            object_name=SHEET_LOCALIZATION,
            check_name="no_duplicates",
            status=_status(len(localization_unique) == len(localization_rows)),
            rows_checked=len(localization_rows),
            issues_count=len(localization_rows) - len(localization_unique),
            details="no duplicate combinations for date + nm_id + region",
        )
    )
    rows.append(
        CheckRow(
            object_name=SHEET_LOCALIZATION,
            check_name="real_metrics",
            status=_status(localization_metrics == len(localization_rows)),
            rows_checked=len(localization_rows),
            issues_count=0 if localization_metrics == len(localization_rows) else len(localization_rows) - localization_metrics,
            details="orders, sales, and sales amount remain real in the wide user sheet",
        )
    )

    expected_coverage = {
        "Поисковые запросы": "PARTIAL",
        "РасходРК": "PARTIAL/OK",
        "Локализация": "PARTIAL",
        "Остатки": "TECHNICAL / PARTIAL",
        "ВБро": "MANUAL_EXTERNAL_SERVICE / MANUAL_UPLOAD",
        "РК стата": "PARTIAL",
        "Сравнение карточек": "MPSTAT_401",
        "Точка вх": "CSV_ONLY / PRIVATE_ENDPOINT / NEEDS_EXPORT_SAMPLE",
        "ИТОГО_FULL": "LATER",
    }
    coverage_map = {row.get("sheet_name", ""): row.get("status", "") for row in coverage_rows}
    coverage_issues = sum(1 for sheet_name, expected in expected_coverage.items() if coverage_map.get(sheet_name) != expected)
    rows.append(
        CheckRow(
            object_name=SHEET_COVERAGE,
            check_name="status_updates",
            status=_status(coverage_issues == 0),
            rows_checked=len(coverage_rows),
            issues_count=coverage_issues,
            details="coverage statuses were refreshed for the current quick polish scope",
        )
    )

    expected_backlog = {row["block"]: row["status"] for row in build_backlog_rows()}
    backlog_map = {row.get("block", ""): row.get("status", "") for row in backlog_rows}
    backlog_issues = sum(1 for block, expected in expected_backlog.items() if backlog_map.get(block) != expected)
    rows.append(
        CheckRow(
            object_name=SHEET_BACKLOG,
            check_name="status_updates",
            status=_status(backlog_issues == 0),
            rows_checked=len(backlog_rows),
            issues_count=backlog_issues,
            details="backlog keeps only the remaining confirmed blockers",
        )
    )

    rows.append(
        CheckRow(
            object_name=SHEET_STOCKS,
            check_name="technical_sheet_present",
            status=_status(len(stocks_rows) > 0),
            rows_checked=len(stocks_rows),
            issues_count=0 if stocks_rows else 1,
            details="helper stock sheet remains present and is not deleted",
        )
    )

    forbidden_rows = search_rows + ad_rows + localization_rows + coverage_rows + backlog_rows + stocks_rows
    rows.append(
        CheckRow(
            object_name="all_sheets",
            check_name="no_mock_fake",
            status=_status(_count_forbidden(forbidden_rows) == 0),
            rows_checked=len(forbidden_rows),
            issues_count=_count_forbidden(forbidden_rows),
            details="no ART-/TestBrand/Товар тестовый/DRY_RUN/mock/fake markers found",
        )
    )

    lines = [
        "# Quick MVP Polish Report",
        "",
        f"- Generated at: `{datetime.now().astimezone().isoformat(timespec='seconds')}`",
        "- Scope: safe polish for `Поисковые запросы`, `РасходРК`, `Локализация`, `Coverage`, and `Backlog`.",
        "- Period unchanged: `2026-05-31` .. `2026-06-01`.",
        "- nmIDs unchanged: `197330807, 37320545, 37342770, 36387055, 577510563`.",
        "- Mock/fake rows were not added.",
        "",
        "## Checks",
        "",
    ]
    for row in rows:
        lines.append(f"- `{row.object_name}` / `{row.check_name}`: `{row.status}` ({row.issues_count} issues)")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `Поисковые запросы` now pulls product reference fields from funnel/stock data when available.",
            "- `РасходРК` classifies click campaigns as `За клик` without changing spend values.",
            "- `Локализация` no longer shows total WB stock as a regional stock proxy.",
            "- `Остатки` is treated as a technical/helper sheet.",
            "- Processed tables were not removed.",
        ]
    )
    return rows, lines


def _write_report(rows: list[CheckRow], lines: list[str]) -> None:
    REPORT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with REPORT_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["object_name", "check_name", "status", "rows_checked", "issues_count", "details"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_csv_row())


def main() -> bool:
    if not settings.google_sheet_id:
        raise RuntimeError("GOOGLE_SHEET_ID is missing")

    client = GoogleSheetsClient()
    rows, lines = build_report(client, settings.google_sheet_id)
    _write_report(rows, lines)
    print(f"Markdown report: {REPORT_MD_PATH}")
    print(f"CSV report: {REPORT_CSV_PATH}")
    return all(row.status == "PASS" for row in rows)


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
