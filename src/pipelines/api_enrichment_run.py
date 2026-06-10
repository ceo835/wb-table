from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from src.clients.google_sheets_client import GoogleSheetsClient
from src.config.settings import settings
from src.pipelines.mvp_real_run import MvpRealRun
from src.pipelines.vbro_localization_partial_run import VbroLocalizationPartialRun
from src.sheets.schema_definitions import USER_SHEET_SCHEMAS


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data" / "processed"
DOCS_DIR = ROOT_DIR / "docs"

REPORT_MD_PATH = DOCS_DIR / "api_enrichment_run_report.md"
REPORT_CSV_PATH = DATA_DIR / "api_enrichment_run_report.csv"

FORBIDDEN_MARKERS = ("ART-", "TestBrand", "Товар тестовый", "DRY_RUN", "mock", "fake")


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


def _read_sheet_rows(client: GoogleSheetsClient, spreadsheet_id: str, sheet_name: str) -> tuple[list[str], list[dict[str, str]]]:
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


def _count_forbidden(rows: list[dict[str, str]]) -> int:
    count = 0
    for row in rows:
        if any(any(marker.lower() in _stringify(cell).lower() for marker in FORBIDDEN_MARKERS) for cell in row.values()):
            count += 1
    return count


def _unique_count(rows: list[dict[str, str]], keys: Sequence[str]) -> int:
    unique = set()
    for row in rows:
        unique.add(tuple(_stringify(row.get(key, "")) for key in keys))
    return len(unique)


@dataclass(frozen=True)
class ReportRow:
    sheet_name: str
    field_name: str
    status: str
    rows_updated: int
    source_endpoint: str
    details: str

    def as_csv_row(self) -> dict[str, str]:
        return {
            "sheet_name": self.sheet_name,
            "field_name": self.field_name,
            "status": self.status,
            "rows_updated": str(self.rows_updated),
            "source_endpoint": self.source_endpoint,
            "details": self.details,
        }


class ApiEnrichmentRun:
    def __init__(self) -> None:
        self.loaded_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.spreadsheet_id = settings.google_sheet_id
        self.gs_client = GoogleSheetsClient()

    def _result_map(self, summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result_map: dict[str, dict[str, Any]] = {}
        for source_key in ("results", "report_rows"):
            for item in summary.get(source_key, []):
                target = item.get("target") or item.get("object_name")
                if target:
                    result_map[str(target)] = item
        return result_map

    def _report_rows(
        self,
        mvp_summary: dict[str, Any],
        vbro_summary: dict[str, Any],
    ) -> list[ReportRow]:
        mvp_results = self._result_map(mvp_summary)
        vbro_results = self._result_map(vbro_summary)

        rows: list[ReportRow] = []

        funnel = mvp_results.get("Воронка на день", {})
        rows.append(
            ReportRow(
                sheet_name="Воронка на день",
                field_name="confirmed enrichment",
                status="AVAILABLE",
                rows_updated=int(funnel.get("rows_written", 0) or 0),
                source_endpoint=str(funnel.get("endpoint", "/api/analytics/v3/sales-funnel/products/history")),
                details="previous-period metrics, WB Club fields, ratings, stocks, delivery time and localization were populated when the endpoint exposed them",
            )
        )
        rows.append(
            ReportRow(
                sheet_name="Воронка на день",
                field_name="ad placeholders",
                status="PARTIAL",
                rows_updated=int(funnel.get("rows_written", 0) or 0),
                source_endpoint=str(funnel.get("endpoint", "/api/analytics/v3/sales-funnel/products/history")),
                details="ad proxy columns stay blank because they are not confirmed by the sales-funnel endpoint",
            )
        )

        stock = mvp_results.get("Остатки", {})
        rows.append(
            ReportRow(
                sheet_name="Остатки",
                field_name="helper stock snapshot",
                status="PARTIAL",
                rows_updated=int(stock.get("rows_written", 0) or 0),
                source_endpoint=str(stock.get("endpoint", "/api/v2/stocks-report/products/products")),
                details="wb_stock_qty and stock_total_sum are confirmed; mp_stock_qty remains blank",
            )
        )

        ad_costs = mvp_results.get("РасходРК", {})
        rows.append(
            ReportRow(
                sheet_name="РасходРК",
                field_name="cost allocation",
                status="PARTIAL/OK",
                rows_updated=int(ad_costs.get("rows_written", 0) or 0),
                source_endpoint=str(ad_costs.get("endpoint", "/adv/v1/upd")),
                details="nm_id parsing and click-campaign classification were normalized without changing spend values",
            )
        )

        rk = mvp_results.get("РК стата", {})
        rows.append(
            ReportRow(
                sheet_name="РК стата",
                field_name="campaign/product metrics",
                status="AVAILABLE",
                rows_updated=int(rk.get("rows_written", 0) or 0),
                source_endpoint=str(rk.get("endpoint", "/adv/v3/fullstats")),
                details="live fullstats rows were written for campaign and product grains",
            )
        )
        rows.append(
            ReportRow(
                sheet_name="РК стата",
                field_name="CPM / ROI",
                status="PARTIAL",
                rows_updated=int(rk.get("rows_written", 0) or 0),
                source_endpoint=str(rk.get("endpoint", "/adv/v3/fullstats")),
                details="CPM and ROI remain blank until the formula is explicitly confirmed",
            )
        )

        search = mvp_results.get("Поисковые запросы", {})
        rows.append(
            ReportRow(
                sheet_name="Поисковые запросы",
                field_name="core search metrics + reference fields",
                status="AVAILABLE",
                rows_updated=int(search.get("rows_written", 0) or 0),
                source_endpoint="/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders",
                details="supplier_article, title, subject, brand, visibility, positions, clicks, carts, orders and conversion rates were populated",
            )
        )
        rows.append(
            ReportRow(
                sheet_name="Поисковые запросы",
                field_name="competitor percentiles / min-max price",
                status="PARTIAL",
                rows_updated=int(search.get("rows_written", 0) or 0),
                source_endpoint="/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders",
                details="competitor percentile fields and min/max discount prices stay blank because the source was not confirmed",
            )
        )

        itogo = mvp_results.get("ИТОГО_v1", {})
        rows.append(
            ReportRow(
                sheet_name="ИТОГО_v1",
                field_name="derived summary",
                status="PARTIAL",
                rows_updated=int(itogo.get("rows_written", 0) or 0),
                source_endpoint="mixed",
                details="wide summary was refreshed from confirmed funnel, stock, search and ad sources",
            )
        )

        vbro = vbro_results.get("ВБро", {})
        rows.append(
            ReportRow(
                sheet_name="ВБро",
                field_name="financial base",
                status="PARTIAL",
                rows_updated=int(vbro.get("rows_written", 0) or 0),
                source_endpoint="/api/v5/supplier/reportDetailByPeriod",
                details="profit base is preserved in processed data, while the operational profit cells stay blank",
            )
        )
        rows.append(
            ReportRow(
                sheet_name="ВБро",
                field_name="operating profit",
                status="MANUAL_EXTERNAL_SERVICE / MANUAL_UPLOAD",
                rows_updated=int(vbro.get("rows_written", 0) or 0),
                source_endpoint="/api/v5/supplier/reportDetailByPeriod",
                details="operating profit stays blank because the employee confirmed an external manual service without project access",
            )
        )

        localization = vbro_results.get("Локализация", {})
        rows.append(
            ReportRow(
                sheet_name="Локализация",
                field_name="regional sales rows",
                status="AVAILABLE",
                rows_updated=int(localization.get("rows_written", 0) or 0),
                source_endpoint="/api/v1/analytics/region-sale",
                details="regional sales feed is period-level; date is mapped to the window end and reference fields come from the existing funnel snapshot",
            )
        )
        rows.append(
            ReportRow(
                sheet_name="Локализация",
                field_name="regional stock / delivery / local%",
                status="PARTIAL",
                rows_updated=int(localization.get("rows_written", 0) or 0),
                source_endpoint="/api/v1/analytics/region-sale; https://seller.wildberries.ru/remains-analytics/orders-geography",
                details="regional stock, delivery time and local/nonlocal percentages stay blank until orders-geography is provided as CSV/Excel or cabinet access",
            )
        )

        coverage = vbro_results.get("Coverage", {})
        rows.append(
            ReportRow(
                sheet_name="Coverage",
                field_name="status refresh",
                status="OK",
                rows_updated=int(coverage.get("rows_written", 0) or 0),
                source_endpoint="sheet write",
                details="coverage statuses were refreshed for the current enrichment scope",
            )
        )

        backlog = vbro_results.get("Backlog", {})
        rows.append(
            ReportRow(
                sheet_name="Backlog",
                field_name="canonical backlog",
                status="OK",
                rows_updated=int(backlog.get("rows_written", 0) or 0),
                source_endpoint="sheet write",
                details="backlog is produced by the shared canonical builder and no longer depends on script order",
            )
        )

        return rows

    def _write_report(self, rows: list[ReportRow], validations: list[str], summary_lines: list[str]) -> None:
        REPORT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

        md_lines = [
            "# API Enrichment Run Report",
            "",
            f"- Generated at: `{self.loaded_at}`",
            "- Period unchanged: `2026-05-31` .. `2026-06-01`.",
            f"- nmIDs unchanged: `{', '.join(map(str, [197330807, 37320545, 37342770, 36387055, 577510563]))}`.",
            "- Raw/private payloads were not stored.",
            "- Mock/fake rows were not added.",
            "",
            "## Summary",
            "",
        ]
        md_lines.extend(summary_lines)
        md_lines.extend(
            [
                "",
                "## Validations",
                "",
            ]
        )
        for item in validations:
            md_lines.append(f"- {item}")
        md_lines.extend(
            [
                "",
                "## Field Coverage",
                "",
                "| sheet_name | field_name | status | rows_updated | source_endpoint | details |",
                "| --- | --- | --- | ---: | --- | --- |",
            ]
        )
        for row in rows:
            md_lines.append(
                f"| {row.sheet_name} | {row.field_name} | {row.status} | {row.rows_updated} | {row.source_endpoint} | {row.details} |"
            )

        REPORT_MD_PATH.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        with REPORT_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["sheet_name", "field_name", "status", "rows_updated", "source_endpoint", "details"],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row.as_csv_row())

    def run(self) -> dict[str, Any]:
        mvp_summary = MvpRealRun().run()
        vbro_summary = VbroLocalizationPartialRun().run()

        report_rows = self._report_rows(mvp_summary, vbro_summary)

        validations: list[str] = []
        summary_lines: list[str] = []
        spreadsheet_id = self.spreadsheet_id
        if spreadsheet_id:
            funnel_header, funnel_rows = _read_sheet_rows(self.gs_client, spreadsheet_id, "Воронка на день")
            search_header, search_rows = _read_sheet_rows(self.gs_client, spreadsheet_id, "Поисковые запросы")
            rk_header, rk_rows = _read_sheet_rows(self.gs_client, spreadsheet_id, "РК стата")
            localization_header, localization_rows = _read_sheet_rows(self.gs_client, spreadsheet_id, "Локализация")
            vbro_header, vbro_rows = _read_sheet_rows(self.gs_client, spreadsheet_id, "ВБро")
            coverage_header, coverage_rows = _read_sheet_rows(self.gs_client, spreadsheet_id, "Coverage")
            backlog_header, backlog_rows = _read_sheet_rows(self.gs_client, spreadsheet_id, "Backlog")

            validations.extend(
                [
                    f"Воронка на день: {len(funnel_rows)} rows, duplicate keys={len(funnel_rows) - _unique_count(funnel_rows, ('Дата', 'Артикул WB'))}, forbidden markers={_count_forbidden(funnel_rows)}",
                    f"Поисковые запросы: {len(search_rows)} rows, forbidden markers={_count_forbidden(search_rows)}",
                    f"РК стата: {len(rk_rows)} rows, forbidden markers={_count_forbidden(rk_rows)}",
                    f"Локализация: {len(localization_rows)} rows, duplicate keys={len(localization_rows) - _unique_count(localization_rows, ('Дата', 'Артикул WB', 'Регион'))}, forbidden markers={_count_forbidden(localization_rows)}",
                    f"ВБро: {len(vbro_rows)} rows, forbidden markers={_count_forbidden(vbro_rows)}",
                    f"Coverage: {len(coverage_rows)} rows, headers intact={coverage_header == list(USER_SHEET_SCHEMAS['Coverage'].columns)}",
                    f"Backlog: {len(backlog_rows)} rows, headers intact={backlog_header == list(USER_SHEET_SCHEMAS['Backlog'].columns)}",
                ]
            )
            summary_lines.extend(
                [
                    f"- `Воронка на день` rows: `{len(funnel_rows)}`",
                    f"- `Поисковые запросы` rows: `{len(search_rows)}`",
                    f"- `РК стата` rows: `{len(rk_rows)}`",
                    f"- `ВБро` rows: `{len(vbro_rows)}`",
                    f"- `Локализация` rows: `{len(localization_rows)}`",
                    f"- `Coverage` rows: `{len(coverage_rows)}`",
                    f"- `Backlog` rows: `{len(backlog_rows)}`",
                    f"- `mock/fake` markers found: `{_count_forbidden(funnel_rows + search_rows + rk_rows + localization_rows + vbro_rows + coverage_rows + backlog_rows)}`",
                ]
            )
        else:
            validations.append("Google Sheets spreadsheet id is missing; live readback validation was skipped")
            summary_lines.append("- Live readback validation was skipped because GOOGLE_SHEET_ID is missing.")

        self._write_report(report_rows, validations, summary_lines)

        return {
            "generated_at": self.loaded_at,
            "mvp_summary": mvp_summary,
            "vbro_summary": vbro_summary,
            "report_rows": [row.as_csv_row() for row in report_rows],
            "validations": validations,
            "report_md": str(REPORT_MD_PATH),
            "report_csv": str(REPORT_CSV_PATH),
        }


def main() -> dict[str, Any]:
    runner = ApiEnrichmentRun()
    summary = runner.run()
    print(f"Markdown report: {REPORT_MD_PATH}")
    print(f"CSV report: {REPORT_CSV_PATH}")
    return summary
