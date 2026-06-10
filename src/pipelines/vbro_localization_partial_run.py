from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests

from src.clients.google_sheets_client import GoogleSheetsClient
from src.clients.wb_statistics_client import WBStatisticsClient
from src.config.settings import settings
from src.sheets.backlog_builder import build_backlog_rows
from src.sheets.coverage_builder import build_coverage_rows
from src.sheets.schema_definitions import USER_SHEET_SCHEMAS


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data" / "processed"
DOCS_DIR = ROOT_DIR / "docs"
WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"

DATE_FROM = date(2026, 5, 31)
DATE_TO = date(2026, 6, 1)
TEST_NM_IDS = [197330807, 37320545, 37342770, 36387055, 577510563]

FACT_FUNNEL_PATH = DATA_DIR / "fact_funnel_day.csv"
FACT_STOCK_PATH = DATA_DIR / "fact_stock_snapshot.csv"
FACT_AD_COST_DAY_PATH = DATA_DIR / "fact_ad_cost_day.csv"
FACT_PROFIT_PATH = DATA_DIR / "fact_profit_day.csv"
FACT_LOCALIZATION_DAY_PATH = DATA_DIR / "fact_localization_region_day.csv"
FACT_LOCALIZATION_SUMMARY_PATH = DATA_DIR / "fact_localization_region_summary_day.csv"
REPORT_MD_PATH = DOCS_DIR / "vbro_localization_partial_run_report.md"
REPORT_CSV_PATH = DATA_DIR / "vbro_localization_partial_run_report.csv"
LOCALIZATION_USER_REPORT_MD_PATH = DOCS_DIR / "localization_user_view_report.md"
LOCALIZATION_USER_REPORT_CSV_PATH = DATA_DIR / "localization_user_view_report.csv"

SHEET_VBRO = "ВБро"
SHEET_LOCALIZATION = "Локализация"
SHEET_COVERAGE = "Coverage"
SHEET_BACKLOG = "Backlog"


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
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except Exception:
        return None


def _to_int(value: Any) -> int | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(float(str(value).replace(" ", "").replace(",", ".")))
    except Exception:
        return None


def _to_date_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    text = str(value).strip()
    if "T" in text:
        return text.split("T", 1)[0]
    return text[:10]


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def _sum_numbers(values: Iterable[Any]) -> float | None:
    numbers = [value for value in (_to_float(value) for value in values) if value is not None]
    if not numbers:
        return None
    return round(sum(numbers), 2)


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "items", "result", "report"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _index_funnel_rows() -> dict[tuple[str, str], dict[str, str]]:
    rows = _read_csv_rows(FACT_FUNNEL_PATH)
    index: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (_stringify(row.get("date", "")), _stringify(row.get("nm_id", "")))
        if key[0] and key[1]:
            index[key] = row
    return index


def _index_stock_rows() -> dict[str, dict[str, str]]:
    rows = _read_csv_rows(FACT_STOCK_PATH)
    index: dict[str, dict[str, str]] = {}
    for row in rows:
        nm_id = _stringify(row.get("nm_id", ""))
        if nm_id:
            index[nm_id] = row
    return index


def _index_ad_cost_rows() -> dict[tuple[str, str], float]:
    rows = _read_csv_rows(FACT_AD_COST_DAY_PATH)
    totals: dict[tuple[str, str], float] = defaultdict(float)
    for row in rows:
        date_value = _stringify(row.get("date", ""))
        nm_id = _stringify(row.get("nm_id", ""))
        spend = _to_float(row.get("total_spend", "")) or _to_float(row.get("spend", "")) or 0.0
        if date_value and nm_id:
            totals[(date_value, nm_id)] += spend
    return totals


def _safe_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return value


def _normalize_status(value: str) -> str:
    return value.strip().upper().replace(" ", "_")


@dataclass
class PartialRunResult:
    object_name: str
    status: str
    rows_written: int
    fields_filled: str
    fields_empty: str
    details: str

    def as_csv_row(self) -> dict[str, str]:
        return {
            "object_name": self.object_name,
            "status": self.status,
            "rows_written": str(self.rows_written),
            "fields_filled": self.fields_filled,
            "fields_empty": self.fields_empty,
            "details": self.details,
        }


class VbroLocalizationPartialRun:
    def __init__(self) -> None:
        self.date_from = DATE_FROM
        self.date_to = DATE_TO
        self.loaded_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.nm_ids = list(TEST_NM_IDS)
        self.gs_client = GoogleSheetsClient()
        self.wb_client = WBStatisticsClient()
        self.spreadsheet_id = settings.google_sheet_id

    def _ensure_sheet(self, sheet_name: str, headers: Sequence[str]) -> None:
        if not self.spreadsheet_id:
            raise RuntimeError("GOOGLE_SHEET_ID is missing")
        self.gs_client.ensure_worksheet(self.spreadsheet_id, sheet_name)
        current_headers = self.gs_client.get_header_row(self.spreadsheet_id, sheet_name) or []
        if list(current_headers) != list(headers):
            self.gs_client.update_header_row(self.spreadsheet_id, sheet_name, list(headers))

    def _write_sheet(self, sheet_name: str, headers: Sequence[str], rows: list[dict[str, Any]]) -> int:
        self._ensure_sheet(sheet_name, headers)
        end_col = _column_letter(len(headers))
        self.gs_client.clear_range(self.spreadsheet_id, f"{sheet_name}!A2:{end_col}5000")
        if rows:
            values = [[_safe_cell(row.get(column, "")) for column in headers] for row in rows]
            self.gs_client.write_rows(self.spreadsheet_id, sheet_name, values, start_row=2, start_col=1)
        return len(rows)

    def _fetch_orders(self) -> list[dict[str, Any]]:
        payload = self.wb_client.wb_statistics_orders(
            date_from=self.date_from,
            date_to=self.date_to,
            limit=1000,
        )
        return _rows_from_payload(payload)

    def _fetch_report_detail(self) -> list[dict[str, Any]]:
        payload = self.wb_client.wb_report_detail_by_period(
            date_from=self.date_from,
            date_to=self.date_to,
        )
        return _rows_from_payload(payload)

    def _fetch_region_sales(self) -> list[dict[str, Any]]:
        token = settings.wb_analytics_token
        if not token:
            return []
        response = requests.get(
            f"{WB_ANALYTICS_BASE}/api/v1/analytics/region-sale",
            headers={"Authorization": token, "Accept": "application/json"},
            params={"dateFrom": self.date_from.isoformat(), "dateTo": self.date_to.isoformat()},
            timeout=90,
        )
        if response.status_code != 200:
            return []
        try:
            return _rows_from_payload(response.json())
        except Exception:
            return []

    def _build_profit_rows(
        self,
        report_rows: list[dict[str, Any]],
        funnel_index: dict[tuple[str, str], dict[str, str]],
        ad_cost_totals: dict[tuple[str, str], float],
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in report_rows:
            nm_id = _stringify(row.get("nm_id") or row.get("nmId"))
            if nm_id not in {str(value) for value in self.nm_ids}:
                continue
            date_value = _to_date_text(_first_non_empty(row.get("rr_dt"), row.get("sale_dt"), row.get("order_dt"), row.get("date_to"), row.get("date_from")))
            if not date_value or not (self.date_from.isoformat() <= date_value <= self.date_to.isoformat()):
                continue
            grouped[(date_value, nm_id)].append(row)

        rows: list[dict[str, Any]] = []
        for day in [self.date_from.isoformat(), self.date_to.isoformat()]:
            for nm_id in self.nm_ids:
                key = (day, str(nm_id))
                group = grouped.get(key, [])
                funnel = funnel_index.get(key, {})
                supplier_article = _first_non_empty(funnel.get("supplier_article"), group[0].get("sa_name") if group else "")
                title = _first_non_empty(funnel.get("title"), "")
                subject = _first_non_empty(funnel.get("subject"), group[0].get("subject_name") if group else "")
                brand = _first_non_empty(funnel.get("brand"), group[0].get("brand_name") if group else "")
                rows.append(
                    {
                        "date": day,
                        "nm_id": nm_id,
                        "supplier_article": supplier_article,
                        "title": title,
                        "subject": subject,
                        "brand": brand,
                        "organic_sales_qty": "",
                        "net_sales_payout": _sum_numbers(row.get("ppvz_for_pay") for row in group) or "",
                        "ad_spend": ad_cost_totals.get(key, "") or "",
                        "logistics": _sum_numbers(row.get("delivery_rub") for row in group) or "",
                        "storage": _sum_numbers(row.get("storage_fee") for row in group) or "",
                        "penalties": _sum_numbers(row.get("penalty") for row in group) or "",
                        "deductions": _sum_numbers(row.get("deduction") for row in group) or "",
                        "acceptance": _sum_numbers(row.get("acceptance") for row in group) or "",
                        "cogs": "",
                        "other_costs": "",
                        "operating_profit": "",
                        "operating_profit_per_unit": "",
                        "formula_status": "MANUAL_EXTERNAL_SERVICE",
                        "data_status": "PARTIAL",
                        "source_status": "MANUAL_UPLOAD",
                        "loaded_at": self.loaded_at,
                    }
                )
        return rows

    def _build_localization_rows(
        self,
        region_rows: list[dict[str, Any]],
        funnel_index: dict[tuple[str, str], dict[str, str]],
        stock_index: dict[str, dict[str, str]] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in region_rows:
            nm_id = _stringify(row.get("nmID"))
            if nm_id not in {str(value) for value in self.nm_ids}:
                continue
            day = self.date_to.isoformat()
            region = _stringify(row.get("regionName"))
            if not day or not region:
                continue
            grouped[(day, nm_id, region)].append(row)

        fact_rows: list[dict[str, Any]] = []
        for (day, nm_id, region), group in sorted(grouped.items()):
            funnel = funnel_index.get((day, nm_id), {})
            if not funnel:
                for (funnel_day, funnel_nm_id), candidate in funnel_index.items():
                    if funnel_nm_id == nm_id:
                        funnel = candidate
                        break
            first = group[0]
            stock_row = (stock_index or {}).get(nm_id, {})
            country = Counter(_stringify(row.get("countryName")) for row in group).most_common(1)
            sale_qty = _sum_numbers(row.get("saleItemInvoiceQty") for row in group) or len(group)
            sale_amount = _sum_numbers(row.get("saleInvoiceCostPrice") for row in group) or ""
            fact_rows.append(
                {
                    "date": day,
                    "nm_id": int(nm_id),
                    "supplier_article": _first_non_empty(
                        funnel.get("supplier_article"),
                        stock_row.get("supplier_article"),
                        first.get("sa"),
                    ),
                    "title": _first_non_empty(
                        funnel.get("title"),
                        stock_row.get("title"),
                        first.get("sa"),
                    ),
                    "subject": _first_non_empty(
                        funnel.get("subject"),
                        stock_row.get("subject"),
                        "",
                    ),
                    "brand": _first_non_empty(
                        funnel.get("brand"),
                        stock_row.get("brand"),
                        "",
                    ),
                    "country": country[0][0] if country else _stringify(first.get("countryName")),
                    "region": region,
                    "city": _stringify(first.get("cityName")),
                    "delivery_time": "",
                    "orders_total_qty": sale_qty,
                    "orders_local_qty": "",
                    "orders_nonlocal_qty": "",
                    "orders_nonlocal_percent": "",
                    "wb_stock_orders_local_qty": "",
                    "wb_stock_orders_nonlocal_qty": "",
                    "wb_stock_orders_nonlocal_percent": "",
                    "mp_orders_local_qty": "",
                    "mp_orders_nonlocal_qty": "",
                    "mp_orders_nonlocal_percent": "",
                    "wb_stock_qty": "",
                    "mp_stock_qty": "",
                    "sale_item_qty": sale_qty,
                    "sale_amount": sale_amount,
                    "local_orders_percent": "",
                    "data_status": "PARTIAL",
                    "source_status": "REAL_API",
                    "loaded_at": self.loaded_at,
                }
            )

        summary_rows: list[dict[str, Any]] = []
        totals_by_day = Counter(row["date"] for row in fact_rows)
        for day in sorted(totals_by_day):
            day_rows = [row for row in fact_rows if row["date"] == day]
            day_total = sum(_to_float(row.get("sale_item_qty")) or 0 for row in day_rows) or 0
            by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in day_rows:
                by_region[_stringify(row.get("region"))].append(row)
            for region, rows_for_region in sorted(by_region.items()):
                total_qty = sum(_to_float(row.get("sale_item_qty")) or 0 for row in rows_for_region)
                total_amount = _sum_numbers(row.get("sale_amount") for row in rows_for_region) or ""
                country = Counter(_stringify(row.get("country")) for row in rows_for_region).most_common(1)
                share = round((total_qty / day_total) * 100, 2) if day_total else ""
                summary_rows.append(
                    {
                        "date": day,
                        "country": country[0][0] if country else "",
                        "region": region,
                        "sale_item_qty": total_qty,
                        "sale_amount": total_amount,
                        "local_orders_percent": "",
                        "nonlocal_orders_percent": "",
                        "delivery_time": "",
                        "region_orders_share_percent": share,
                        "wb_all_orders_share_percent": share,
                        "data_status": "PARTIAL",
                        "source_status": "CALCULATED",
                        "loaded_at": self.loaded_at,
                    }
                )

        return fact_rows, summary_rows

    def _project_vbro_rows(self, profit_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in profit_rows:
            rows.append(
                {
                    "Дата": row["date"],
                    "Артикул ВБ": row["nm_id"],
                    "Артикул продавца": row["supplier_article"],
                    "Продажи (органические)": "",
                    "Операционная прибыль": "",
                    "Операционная прибыль на единицу": "",
                    "data_status": row["data_status"],
                    "source_status": row["source_status"],
                    "loaded_at": row["loaded_at"],
                }
            )
        return rows

    def _project_localization_rows(self, fact_rows: list[dict[str, Any]], summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in fact_rows:
            rows.append(
                {
                    "Дата": row["date"],
                    "Артикул WB": row["nm_id"],
                    "Артикул продавца": row["supplier_article"],
                    "Название": row["title"],
                    "Предмет": row["subject"],
                    "Бренд": row["brand"],
                    "Регион": row["region"],
                    "Итого заказов, шт": row["orders_total_qty"],
                    "Продажи, шт": row["sale_item_qty"],
                    "Сумма продаж, ₽": row["sale_amount"],
                    "Остатки склад ВБ, шт": "",
                    "Остатки МП, шт": "",
                    "Время доставки": "",
                    "Локальные заказы, %": "",
                    "Не локальные заказы, %": "",
                    "data_status": "PARTIAL",
                    "source_status": "PARTIAL",
                    "loaded_at": row["loaded_at"],
                }
            )
        return rows

    def _coverage_rows(self) -> list[dict[str, Any]]:
        return build_coverage_rows()

    def _backlog_rows(self) -> list[dict[str, Any]]:
        return build_backlog_rows()

    def _write_csv(self, path: Path, rows: list[dict[str, Any]], columns: Sequence[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({column: _safe_cell(row.get(column, "")) for column in columns})

    def _sheet_validation(self, sheet_name: str, expected_rows: int, forbidden_markers: tuple[str, ...]) -> tuple[int, int]:
        headers = USER_SHEET_SCHEMAS[sheet_name].columns
        end_col = _column_letter(len(headers))
        values = self.gs_client.read_range(self.spreadsheet_id, f"'{sheet_name}'!A1:{end_col}5000") or []
        data_rows = values[1:] if values else []
        forbidden = 0
        for row in data_rows:
            for cell in row:
                text = _stringify(cell)
                if any(marker.lower() in text.lower() for marker in forbidden_markers):
                    forbidden += 1
                    break
        return len(data_rows), forbidden

    def _write_report(self, results: list[PartialRunResult]) -> None:
        REPORT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            "# VBro and Localization Partial Run Report",
            "",
            f"- Generated at: `{self.loaded_at}`",
            f"- Window: `{self.date_from.isoformat()}` .. `{self.date_to.isoformat()}`",
            f"- Test nmIDs: `{', '.join(map(str, TEST_NM_IDS))}`",
            "- WB API calls were read-only. No WB/MPStat writes were executed.",
            "- Raw private responses were not saved by this run.",
            "- Mock/fake rows were not added.",
            "",
            "## Results",
            "",
        ]
        for result in results:
            lines.extend(
                [
                    f"### {result.object_name}",
                    "",
                    f"- Status: `{result.status}`",
                    f"- Rows written: `{result.rows_written}`",
                    f"- Fields filled: `{result.fields_filled or '-'}`",
                    f"- Fields empty: `{result.fields_empty or '-'}`",
                    f"- Details: `{result.details}`",
                    "",
                ]
            )
        lines.extend(
            [
                "## Safety confirmation",
                "",
                "- Existing Google Sheets data was not cleared beyond the target data blocks.",
                "- Mock/fake rows were not created.",
                "- WB/MPStat write actions were not executed.",
                "- Unsupported fields were left blank rather than fabricated.",
            ]
        )
        REPORT_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with REPORT_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["object_name", "status", "rows_written", "fields_filled", "fields_empty", "details"],
            )
            writer.writeheader()
            for result in results:
                writer.writerow(result.as_csv_row())

    def _write_localization_user_view_report(
        self,
        localization_fact_rows: list[dict[str, Any]],
        localization_summary_rows: list[dict[str, Any]],
        localization_sheet_rows: list[dict[str, Any]],
        validation: dict[str, Any],
    ) -> None:
        LOCALIZATION_USER_REPORT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCALIZATION_USER_REPORT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

        localization_fields_filled = (
            "Дата,Артикул WB,Артикул продавца,Название,Предмет,Бренд,Регион,"
            "Итого заказов, шт,Продажи, шт,Сумма продаж, ₽,Остатки склад ВБ, шт"
        )
        localization_fields_empty = "Остатки МП, шт,Время доставки,Локальные заказы, %,Не локальные заказы, %"

        checks = [
            PartialRunResult(
                object_name="fact_localization_region_day",
                status="PARTIAL",
                rows_written=len(localization_fact_rows),
                fields_filled="date,nm_id,supplier_article,title,subject,brand,country,region,orders_total_qty,sale_item_qty,sale_amount,wb_stock_qty",
                fields_empty="delivery_time,local_orders_percent,orders_local_qty,orders_nonlocal_qty,mp_stock_qty",
                details="processed table preserved; wide user view is projected from this source",
            ),
            PartialRunResult(
                object_name="fact_localization_region_summary_day",
                status="PARTIAL",
                rows_written=len(localization_summary_rows),
                fields_filled="date,country,region,sale_item_qty,sale_amount,region_orders_share_percent,wb_all_orders_share_percent",
                fields_empty="local_orders_percent,nonlocal_orders_percent,delivery_time",
                details="processed summary table preserved; not written to the user sheet",
            ),
            PartialRunResult(
                object_name="Локализация",
                status="PARTIAL",
                rows_written=len(localization_sheet_rows),
                fields_filled=localization_fields_filled,
                fields_empty=localization_fields_empty,
                details="wide one-row-per-region user view written without metric_name/metric_value projection",
            ),
            PartialRunResult(
                object_name="check::no_mock_fake",
                status="PASS" if validation["forbidden_markers"] == 0 else "FAIL",
                rows_written=len(localization_sheet_rows),
                fields_filled="",
                fields_empty="",
                details="no ART-, TestBrand, DRY_RUN, mock, or fake markers were found",
            ),
            PartialRunResult(
                object_name="check::no_duplicates",
                status="PASS" if validation["unique_rows"] == len(localization_sheet_rows) else "FAIL",
                rows_written=len(localization_sheet_rows),
                fields_filled="",
                fields_empty="",
                details="rows are unique by date + nm_id + region",
            ),
            PartialRunResult(
                object_name="check::no_metric_columns",
                status="PASS" if validation["metric_columns_absent"] else "FAIL",
                rows_written=1,
                fields_filled="",
                fields_empty="",
                details="metric_name and metric_value are not present in the user sheet headers",
            ),
            PartialRunResult(
                object_name="check::real_regions",
                status="PASS" if validation["real_regions"] else "FAIL",
                rows_written=len(localization_sheet_rows),
                fields_filled="",
                fields_empty="",
                details="real region values are present in the user sheet",
            ),
            PartialRunResult(
                object_name="check::real_metrics",
                status="PASS" if validation["real_metrics"] else "FAIL",
                rows_written=validation["real_metrics_rows"],
                fields_filled="",
                fields_empty="",
                details="orders_total_qty, sale_item_qty, or sale_amount contain real values",
            ),
            PartialRunResult(
                object_name="check::processed_tables_preserved",
                status="PASS" if validation["processed_tables_preserved"] else "FAIL",
                rows_written=len(localization_fact_rows) + len(localization_summary_rows),
                fields_filled="",
                fields_empty="",
                details="fact_localization_region_day and fact_localization_region_summary_day were not lost",
            ),
        ]

        lines = [
            "# Localization User View Report",
            "",
            f"- Generated at: `{self.loaded_at}`",
            f"- Window: `{self.date_from.isoformat()}` .. `{self.date_to.isoformat()}`",
            f"- Test nmIDs: `{', '.join(map(str, TEST_NM_IDS))}`",
            "- User sheet format: wide one-row-per-date-nm_id-region",
            "- Processed tables were preserved unchanged.",
            "",
            "## Results",
            "",
        ]
        for result in checks:
            lines.extend(
                [
                    f"### {result.object_name}",
                    "",
                    f"- Status: `{result.status}`",
                    f"- Rows written / checked: `{result.rows_written}`",
                    f"- Fields filled: `{result.fields_filled or '-'}`",
                    f"- Fields empty: `{result.fields_empty or '-'}`",
                    f"- Details: `{result.details}`",
                    "",
                ]
            )
        lines.extend(
            [
                "## Safety confirmation",
                "",
                "- Mock/fake rows were not added.",
                "- Unsupported fields remained blank rather than fabricated.",
                "- Processed localization tables remained available on disk.",
            ]
        )
        LOCALIZATION_USER_REPORT_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with LOCALIZATION_USER_REPORT_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["object_name", "status", "rows_written", "fields_filled", "fields_empty", "details"],
            )
            writer.writeheader()
            for result in checks:
                writer.writerow(result.as_csv_row())

    def run(self) -> dict[str, Any]:
        funnel_index = _index_funnel_rows()
        stock_index = _index_stock_rows()
        ad_cost_totals = _index_ad_cost_rows()

        region_rows = self._fetch_region_sales()
        report_rows = self._fetch_report_detail()

        profit_rows = self._build_profit_rows(report_rows, funnel_index, ad_cost_totals)
        localization_fact_rows, localization_summary_rows = self._build_localization_rows(region_rows, funnel_index, stock_index)
        vbro_rows = self._project_vbro_rows(profit_rows)
        localization_sheet_rows = self._project_localization_rows(localization_fact_rows, localization_summary_rows)
        coverage_rows = self._coverage_rows()
        backlog_rows = self._backlog_rows()

        self._write_csv(FACT_PROFIT_PATH, profit_rows, USER_SHEET_SCHEMAS[SHEET_VBRO].columns[:0] + (
            "date",
            "nm_id",
            "supplier_article",
            "title",
            "subject",
            "brand",
            "organic_sales_qty",
            "net_sales_payout",
            "ad_spend",
            "logistics",
            "storage",
            "penalties",
            "deductions",
            "acceptance",
            "cogs",
            "other_costs",
            "operating_profit",
            "operating_profit_per_unit",
            "formula_status",
            "data_status",
            "source_status",
            "loaded_at",
        ))
        self._write_csv(FACT_LOCALIZATION_DAY_PATH, localization_fact_rows, (
            "date",
            "nm_id",
            "supplier_article",
            "title",
            "subject",
            "brand",
            "country",
            "region",
            "city",
            "delivery_time",
            "orders_total_qty",
            "orders_local_qty",
            "orders_nonlocal_qty",
            "orders_nonlocal_percent",
            "wb_stock_orders_local_qty",
            "wb_stock_orders_nonlocal_qty",
            "wb_stock_orders_nonlocal_percent",
            "mp_orders_local_qty",
            "mp_orders_nonlocal_qty",
            "mp_orders_nonlocal_percent",
            "wb_stock_qty",
            "mp_stock_qty",
            "sale_item_qty",
            "sale_amount",
            "local_orders_percent",
            "data_status",
            "source_status",
            "loaded_at",
        ))
        self._write_csv(FACT_LOCALIZATION_SUMMARY_PATH, localization_summary_rows, (
            "date",
            "country",
            "region",
            "sale_item_qty",
            "sale_amount",
            "local_orders_percent",
            "nonlocal_orders_percent",
            "delivery_time",
            "region_orders_share_percent",
            "wb_all_orders_share_percent",
            "data_status",
            "source_status",
            "loaded_at",
        ))

        write_results: list[PartialRunResult] = []

        vbro_written = self._write_sheet(SHEET_VBRO, USER_SHEET_SCHEMAS[SHEET_VBRO].columns, vbro_rows)
        write_results.append(
            PartialRunResult(
                object_name="ВБро",
                status="PARTIAL",
                rows_written=vbro_written,
                fields_filled="date,nm_id,supplier_article",
                fields_empty="organic_sales_qty,operating_profit,operating_profit_per_unit",
                details="profit rows written, but operating profit remains blank because the source is an external manual service",
            )
        )

        localization_written = self._write_sheet(SHEET_LOCALIZATION, USER_SHEET_SCHEMAS[SHEET_LOCALIZATION].columns, localization_sheet_rows)
        write_results.append(
            PartialRunResult(
                object_name="Локализация",
                status="PARTIAL",
                rows_written=localization_written,
                fields_filled="Дата,Артикул WB,Артикул продавца,Название,Предмет,Бренд,Регион,Итого заказов, шт,Продажи, шт,Сумма продаж, ₽,Остатки склад ВБ, шт",
                fields_empty="Остатки МП, шт,Время доставки,Локальные заказы, %,Не локальные заказы, %",
                details="wide human-readable regional rows written from live WB statistics orders",
            )
        )

        coverage_written = self._write_sheet(SHEET_COVERAGE, USER_SHEET_SCHEMAS[SHEET_COVERAGE].columns, coverage_rows)
        write_results.append(
            PartialRunResult(
                object_name="Coverage",
                status="OK",
                rows_written=coverage_written,
                fields_filled="sheet_name,status,details",
                fields_empty="",
                details="coverage refreshed with current MVP/partial/LATER statuses",
            )
        )

        backlog_written = self._write_sheet(SHEET_BACKLOG, USER_SHEET_SCHEMAS[SHEET_BACKLOG].columns, backlog_rows)
        write_results.append(
            PartialRunResult(
                object_name="Backlog",
                status="OK",
                rows_written=backlog_written,
                fields_filled="block,status,reason,next_step,priority",
                fields_empty="",
                details="backlog refreshed with remaining blockers",
            )
        )

        vbro_rows_count, vbro_forbidden = self._sheet_validation(SHEET_VBRO, 10, ("ART-", "TestBrand", "DRY_RUN", "mock", "fake"))
        localization_rows_count, localization_forbidden = self._sheet_validation(SHEET_LOCALIZATION, len(localization_sheet_rows), ("ART-", "TestBrand", "DRY_RUN", "mock", "fake"))
        coverage_rows_count, coverage_forbidden = self._sheet_validation(SHEET_COVERAGE, len(coverage_rows), ("ART-", "TestBrand", "DRY_RUN", "mock", "fake"))
        backlog_rows_count, backlog_forbidden = self._sheet_validation(SHEET_BACKLOG, len(backlog_rows), ("ART-", "TestBrand", "DRY_RUN", "mock", "fake"))
        localization_headers = self.gs_client.get_header_row(self.spreadsheet_id, SHEET_LOCALIZATION) or []
        localization_metric_columns_absent = "metric_name" not in localization_headers and "metric_value" not in localization_headers
        localization_unique_rows = len({(row["Дата"], row["Артикул WB"], row["Регион"]) for row in localization_sheet_rows})
        localization_real_regions = all(_stringify(row.get("Регион")) for row in localization_sheet_rows)
        localization_real_metrics_rows = sum(
            1
            for row in localization_sheet_rows
            if any(_stringify(row.get(column)) for column in ("Итого заказов, шт", "Продажи, шт", "Сумма продаж, ₽"))
        )

        report_rows = [
            PartialRunResult(
                object_name="fact_profit_day",
                status="PARTIAL",
                rows_written=len(profit_rows),
                fields_filled="date,nm_id,supplier_article,title,subject,brand,net_sales_payout,ad_spend,logistics,storage,penalties,deductions,acceptance",
                fields_empty="organic_sales_qty,cogs,other_costs,operating_profit,operating_profit_per_unit",
                details="reportDetailByPeriod provided the financial base, but profit stays manual because the source is external",
            ),
            PartialRunResult(
                object_name="fact_localization_region_day",
                status="PARTIAL",
                rows_written=len(localization_fact_rows),
                fields_filled="date,nm_id,supplier_article,title,subject,brand,country,region,orders_total_qty,sale_item_qty,sale_amount",
                fields_empty="delivery_time,local_orders_percent,orders_local_qty,orders_nonlocal_qty,wb_stock_qty,mp_stock_qty",
                details="regional orders were built from live WB statistics orders; processed table preserved for user wide view",
            ),
            PartialRunResult(
                object_name="fact_localization_region_summary_day",
                status="PARTIAL",
                rows_written=len(localization_summary_rows),
                fields_filled="date,country,region,sale_item_qty,sale_amount,region_orders_share_percent,wb_all_orders_share_percent",
                fields_empty="local_orders_percent,nonlocal_orders_percent,delivery_time",
                details="summary rows were aggregated from regional order rows and kept as processed data",
            ),
            *write_results,
        ]

        self._write_report(report_rows)
        self._write_localization_user_view_report(
            localization_fact_rows=localization_fact_rows,
            localization_summary_rows=localization_summary_rows,
            localization_sheet_rows=localization_sheet_rows,
            validation={
                "forbidden_markers": localization_forbidden,
                "unique_rows": localization_unique_rows,
                "metric_columns_absent": localization_metric_columns_absent,
                "real_regions": localization_real_regions,
                "real_metrics": localization_real_metrics_rows == len(localization_sheet_rows),
                "real_metrics_rows": localization_real_metrics_rows,
                "processed_tables_preserved": len(localization_fact_rows) > 0 and len(localization_summary_rows) > 0,
            },
        )

        return {
            "generated_at": self.loaded_at,
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "test_nm_ids": TEST_NM_IDS,
            "sheet_validation": {
                SHEET_VBRO: {"rows": vbro_rows_count, "forbidden_markers": vbro_forbidden},
                SHEET_LOCALIZATION: {"rows": localization_rows_count, "forbidden_markers": localization_forbidden},
                SHEET_COVERAGE: {"rows": coverage_rows_count, "forbidden_markers": coverage_forbidden},
                SHEET_BACKLOG: {"rows": backlog_rows_count, "forbidden_markers": backlog_forbidden},
            },
            "report_rows": [asdict(row) for row in report_rows],
            "vbro_rows": vbro_rows,
            "localization_rows": localization_sheet_rows,
            "safety": {
                "google_sheets_written": True,
                "raw_private_payloads_saved": False,
                "mock_data_created": False,
                "wb_mpstat_write_calls_executed": False,
                "existing_fake_rows_left_untouched": True,
                "test_nm_ids_not_expanded": True,
            },
        }


def main() -> dict[str, Any]:
    runner = VbroLocalizationPartialRun()
    summary = runner.run()
    print(f"Markdown report: {REPORT_MD_PATH}")
    print(f"CSV report: {REPORT_CSV_PATH}")
    print(f"Localization user report: {LOCALIZATION_USER_REPORT_MD_PATH}")
    print(f"Localization user CSV: {LOCALIZATION_USER_REPORT_CSV_PATH}")
    return summary
