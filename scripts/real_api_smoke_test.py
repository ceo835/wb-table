#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.clients.google_sheets_client import GoogleSheetsClient
from src.config.settings import settings


TEST_NM_IDS = [197330807, 37320545, 37342770, 36387055, 577510563]
DOCS_REPORT_PATH = ROOT_DIR / "docs" / "real_api_smoke_report.md"
CSV_REPORT_PATH = ROOT_DIR / "data" / "processed" / "real_api_smoke_report.csv"
JSON_SUMMARY_PATH = ROOT_DIR / "data" / "processed" / "real_api_smoke_summary.json"

WB_CONTENT_BASE = "https://content-api.wildberries.ru"
WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"
WB_PROMOTION_BASE = "https://advert-api.wildberries.ru"
MPSTAT_BASE = "https://mpstats.io/api/wb/get"


@dataclass
class SmokeResult:
    source: str
    endpoint: str
    method: str
    status: str
    http_status: str
    objects_count: int
    fields_found: list[str]
    fields_missing: list[str]
    error_short: str
    mvp_usable: str
    notes: str = ""


def normalize_key(key: str) -> str:
    return key.replace("_", "").replace("-", "").lower()


def truncate_error(error: str | None, limit: int = 180) -> str:
    if not error:
        return ""
    compact = " ".join(str(error).split())
    return compact[:limit]


def iter_nested_items(payload: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            yield key, value
            yield from iter_nested_items(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from iter_nested_items(item)


def has_key(payload: Any, candidates: list[str]) -> bool:
    normalized_candidates = {normalize_key(candidate) for candidate in candidates}
    for key, _value in iter_nested_items(payload):
        if normalize_key(key) in normalized_candidates:
            return True
    return False


def has_non_empty_path(payload: Any, path: list[str]) -> bool:
    current = payload
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    if current in (None, "", [], {}):
        return False
    return True


def count_matching_dicts(payload: Any, required_keys: list[str]) -> int:
    required = {normalize_key(key) for key in required_keys}
    count = 0

    def walk(node: Any) -> None:
        nonlocal count
        if isinstance(node, dict):
            keys = {normalize_key(key) for key in node.keys()}
            if required.issubset(keys):
                count += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return count


def first_list_length(payload: Any, preferred_keys: list[str]) -> int:
    if isinstance(payload, dict):
        for key in preferred_keys:
            if key in payload and isinstance(payload[key], list):
                return len(payload[key])
        for value in payload.values():
            length = first_list_length(value, preferred_keys)
            if length:
                return length
    elif isinstance(payload, list):
        return len(payload)
    return 0


def list_from_path(payload: Any, path: list[str]) -> list[Any]:
    current = payload
    for part in path:
        if not isinstance(current, dict):
            return []
        current = current.get(part)
    return current if isinstance(current, list) else []


def append_backlog_updates(results: list[SmokeResult]) -> list[dict[str, str]]:
    updates: list[dict[str, str]] = []
    for result in results:
        if result.mvp_usable == "YES":
            continue
        if result.status == "OK":
            continue
        reason = result.error_short or ", ".join(result.fields_missing) or result.notes or "requires follow-up"
        next_step = "confirm API contract and mapping"
        if "RATE_LIMIT" in reason or result.http_status == "429":
            next_step = "rerun with throttling / schedule requests"
        elif result.http_status in {"401", "403", "402"}:
            next_step = "verify token category / access rights / subscription"
        elif result.source.startswith("WB Stocks"):
            next_step = "use current stocks API for snapshot and CSV for history"
        elif result.source.startswith("WB Search"):
            next_step = "combine Jam endpoints and keep missing fields in PARTIAL"
        elif result.source == "WB Promotion fullstats":
            next_step = "derive row_type/conversion_type mapping from nested fullstats structure"
        elif result.source == "MPStat":
            next_step = "confirm current MPStat base URL / auth header and endpoint contract"

        updates.append(
            {
                "block": result.source,
                "status": result.status,
                "reason": truncate_error(reason, 220),
                "next_step": next_step,
                "priority": "high" if result.status == "FAIL" else "medium",
            }
        )
    return updates


def write_markdown_report(
    path: Path,
    date_from: date,
    date_to: date,
    results: list[SmokeResult],
    sheet_titles: list[str],
    backlog_updates: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Real API Smoke Report",
        "",
        f"- Generated at: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Test nmIDs: `{', '.join(map(str, TEST_NM_IDS))}`",
        f"- Test window: `{date_from.isoformat()}` .. `{date_to.isoformat()}`",
        "- Google Sheets were read only. No rows were written.",
        "- WB / MPStat responses were summarized only. Raw private payloads were not saved.",
        "- Mock/fake rows were not created.",
        "",
        "## Google Sheets tabs",
        "",
    ]
    lines.extend(f"- {title}" for title in sheet_titles)
    lines.extend(["", "## Results", ""])

    for result in results:
        lines.extend(
            [
                f"### {result.source}",
                "",
                f"- Endpoint: `{result.endpoint}`",
                f"- Method: `{result.method}`",
                f"- Status: `{result.status}`",
                f"- HTTP status: `{result.http_status}`",
                f"- Objects count: `{result.objects_count}`",
                f"- Fields found: `{', '.join(result.fields_found) if result.fields_found else '-'}`",
                f"- Fields missing: `{', '.join(result.fields_missing) if result.fields_missing else '-'}`",
                f"- MVP usable: `{result.mvp_usable}`",
                f"- Error: `{result.error_short or '-'}`",
                f"- Notes: `{result.notes or '-'}`",
                "",
            ]
        )

    lines.extend(["## Backlog updates", ""])
    if backlog_updates:
        for item in backlog_updates:
            lines.append(
                f"- `{item['block']}` | `{item['status']}` | {item['reason']} | next: {item['next_step']}"
            )
    else:
        lines.append("- No backlog updates required from this smoke run.")

    lines.extend(
        [
            "",
            "## Safety confirmation",
            "",
            "- Google Sheets were not populated.",
            "- Existing Google Sheets data was not cleared.",
            "- WB / MPStat write actions were not executed.",
            "- Full pipeline was not started.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv_report(path: Path, results: list[SmokeResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "source",
                "endpoint",
                "method",
                "status",
                "http_status",
                "objects_count",
                "fields_found",
                "fields_missing",
                "error_short",
                "mvp_usable",
            ]
        )
        for result in results:
            writer.writerow(
                [
                    result.source,
                    result.endpoint,
                    result.method,
                    result.status,
                    result.http_status,
                    result.objects_count,
                    ";".join(result.fields_found),
                    ";".join(result.fields_missing),
                    result.error_short,
                    result.mvp_usable,
                ]
            )


def write_json_summary(
    path: Path,
    date_from: date,
    date_to: date,
    results: list[SmokeResult],
    sheet_titles: list[str],
    backlog_updates: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "test_nm_ids": TEST_NM_IDS,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "google_sheets_tabs_count": len(sheet_titles),
        "results": [asdict(result) for result in results],
        "backlog_updates": backlog_updates,
        "safety": {
            "google_sheets_written": False,
            "raw_private_payloads_saved": False,
            "mock_data_created": False,
            "wb_mpstat_write_calls_executed": False,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class SafeSmokeRunner:
    def __init__(self) -> None:
        self.date_to = datetime.now().date() - timedelta(days=1)
        self.date_from = self.date_to - timedelta(days=1)
        self.session = requests.Session()
        self.analytics_calls = 0

    def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | list[Any] | None = None,
        timeout: int = 60,
    ) -> tuple[str, Any, str]:
        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return "REQUEST_ERROR", None, truncate_error(str(exc))

        status = str(response.status_code)
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code >= 400:
            short_error = truncate_error(response.text or response.reason)
            return status, data, short_error
        return status, data, ""

    def _analytics_headers(self) -> dict[str, str]:
        return {
            "Authorization": settings.wb_analytics_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _content_headers(self) -> dict[str, str]:
        return {
            "Authorization": settings.wb_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _promotion_headers(self) -> dict[str, str]:
        return {
            "Authorization": settings.wb_token,
            "Accept": "application/json",
        }

    def _mpstat_headers(self) -> dict[str, str]:
        return {
            "X-Mpstats": settings.mpstats_api_token,
            "Accept": "application/json",
        }

    def _throttle_analytics(self) -> None:
        self.analytics_calls += 1
        if self.analytics_calls == 3:
            time.sleep(21)

    def run_google_sheets(self) -> tuple[SmokeResult, list[str]]:
        if not settings.google_sheet_id or not settings.google_application_credentials:
            return (
                SmokeResult(
                    source="Google Sheets",
                    endpoint="spreadsheet metadata",
                    method="GET",
                    status="SKIPPED",
                    http_status="N/A",
                    objects_count=0,
                    fields_found=[],
                    fields_missing=["spreadsheet_id", "credentials"],
                    error_short="google settings are incomplete",
                    mvp_usable="NO",
                ),
                [],
            )

        try:
            client = GoogleSheetsClient(spreadsheet_id=settings.google_sheet_id)
            titles = client.get_worksheet_titles(settings.google_sheet_id) or []
            status = "OK" if titles else "PARTIAL"
            missing = [] if titles else ["tabs"]
            result = SmokeResult(
                source="Google Sheets",
                endpoint="spreadsheet metadata",
                method="GET",
                status=status,
                http_status="200" if titles else "200",
                objects_count=len(titles),
                fields_found=["spreadsheet_id", "tabs"] if titles else ["spreadsheet_id"],
                fields_missing=missing,
                error_short="",
                mvp_usable="YES" if titles else "PARTIAL",
                notes="read-only check",
            )
            return result, titles
        except Exception as exc:
            return (
                SmokeResult(
                    source="Google Sheets",
                    endpoint="spreadsheet metadata",
                    method="GET",
                    status="FAIL",
                    http_status="ERROR",
                    objects_count=0,
                    fields_found=[],
                    fields_missing=["tabs"],
                    error_short=truncate_error(str(exc)),
                    mvp_usable="NO",
                ),
                [],
            )

    def run_wb_content_cards(self) -> SmokeResult:
        if not settings.wb_token:
            return SmokeResult(
                source="WB Content API",
                endpoint="/content/v2/get/cards/list",
                method="POST",
                status="SKIPPED",
                http_status="N/A",
                objects_count=0,
                fields_found=[],
                fields_missing=["nm_id", "vendorCode", "title", "subject", "brand"],
                error_short="WB_TOKEN is missing",
                mvp_usable="NO",
            )

        payload = {"settings": {"cursor": {"limit": 10, "offset": 0}}}
        status_code, data, error = self._request(
            "POST",
            f"{WB_CONTENT_BASE}/content/v2/get/cards/list",
            self._content_headers(),
            json_body=payload,
        )
        fields_map = {
            "nm_id": ["nmID", "nmId"],
            "vendorCode": ["vendorCode"],
            "title": ["title"],
            "subject": ["subjectName", "subject"],
            "brand": ["brand", "brandName"],
        }
        cards = list_from_path(data, ["cards"])
        first_card = cards[0] if cards and isinstance(cards[0], dict) else {}
        fields_found = [name for name, candidates in fields_map.items() if has_key(first_card, candidates)]
        fields_missing = [name for name in fields_map if name not in fields_found]
        objects_count = len(cards)
        status = "OK" if status_code == "200" and objects_count > 0 and not fields_missing else "PARTIAL"
        if status_code != "200":
            status = "FAIL"
        return SmokeResult(
            source="WB Content API",
            endpoint="/content/v2/get/cards/list",
            method="POST",
            status=status,
            http_status=status_code,
            objects_count=objects_count,
            fields_found=fields_found,
            fields_missing=fields_missing,
            error_short=error,
            mvp_usable="YES" if status == "OK" else ("PARTIAL" if status == "PARTIAL" else "NO"),
            notes="200 with empty cards list for the current token/account" if status_code == "200" and objects_count == 0 else "",
        )

    def run_wb_sales_funnel(self) -> SmokeResult:
        if not settings.wb_analytics_token:
            return SmokeResult(
                source="WB Sales Funnel",
                endpoint="/api/analytics/v3/sales-funnel/products/history",
                method="POST",
                status="SKIPPED",
                http_status="N/A",
                objects_count=0,
                fields_found=[],
                fields_missing=["date", "nm_id", "impressions", "card_clicks", "cartCount", "orderCount", "orderSum"],
                error_short="WB_ANALYTICS_TOKEN is missing",
                mvp_usable="NO",
            )

        payload = {
            "selectedPeriod": {"start": self.date_from.isoformat(), "end": self.date_to.isoformat()},
            "nmIds": TEST_NM_IDS,
            "skipDeletedNm": True,
            "aggregationLevel": "day",
        }
        status_code, data, error = self._request(
            "POST",
            f"{WB_ANALYTICS_BASE}/api/analytics/v3/sales-funnel/products/history",
            self._analytics_headers(),
            json_body=payload,
        )
        self._throttle_analytics()
        fields_map = {
            "date": ["date", "start"],
            "nm_id": ["nmId"],
            "impressions": ["openCount", "impressions"],
            "card_clicks": ["openCard", "cardClicks", "openCount"],
            "cartCount": ["cartCount"],
            "orderCount": ["orderCount"],
            "orderSum": ["orderSum"],
            "buyoutSum": ["buyoutSum"],
        }
        fields_found = [name for name, candidates in fields_map.items() if has_key(data, candidates)]
        fields_missing = [name for name in fields_map if name not in fields_found]
        objects_count = count_matching_dicts(data, ["nmId"]) or first_list_length(data, ["data", "products"])
        status = "OK" if status_code == "200" and objects_count > 0 and not fields_missing else "PARTIAL"
        if status_code != "200":
            status = "FAIL"
        return SmokeResult(
            source="WB Sales Funnel",
            endpoint="/api/analytics/v3/sales-funnel/products/history",
            method="POST",
            status=status,
            http_status=status_code,
            objects_count=objects_count,
            fields_found=fields_found,
            fields_missing=fields_missing,
            error_short=error,
            mvp_usable="YES" if status == "OK" else ("PARTIAL" if status == "PARTIAL" else "NO"),
            notes=f"window {self.date_from.isoformat()}..{self.date_to.isoformat()}",
        )

    def run_wb_stocks_products(self) -> SmokeResult:
        if not settings.wb_analytics_token:
            return SmokeResult(
                source="WB Stocks products",
                endpoint="/api/v2/stocks-report/products/products",
                method="POST",
                status="SKIPPED",
                http_status="N/A",
                objects_count=0,
                fields_found=[],
                fields_missing=["wb_stock_qty", "mp_stock_qty", "stock_total_sum"],
                error_short="WB_ANALYTICS_TOKEN is missing",
                mvp_usable="NO",
            )

        payload = {
            "nmIDs": TEST_NM_IDS,
            "currentPeriod": {"start": self.date_to.isoformat(), "end": self.date_to.isoformat()},
            "stockType": "",
            "skipDeletedNm": False,
            "availabilityFilters": [],
            "orderBy": {"field": "avgOrders", "mode": "asc"},
            "limit": 50,
            "offset": 0,
        }
        status_code, data, error = self._request(
            "POST",
            f"{WB_ANALYTICS_BASE}/api/v2/stocks-report/products/products",
            self._analytics_headers(),
            json_body=payload,
        )
        self._throttle_analytics()
        checks = {
            "wb_stock_qty": has_key(data, ["stockCount"]),
            "mp_stock_qty": has_key(data, ["mpStockCount", "mp"]),
            "stock_total_sum": has_key(data, ["stockSum", "balanceSum"]),
        }
        fields_found = [name for name, present in checks.items() if present]
        fields_missing = [name for name in checks if name not in fields_found]
        objects_count = len(list_from_path(data, ["data", "items"]))
        status = "OK" if status_code == "200" and objects_count > 0 and not fields_missing else "PARTIAL"
        if status_code != "200":
            status = "FAIL"
        return SmokeResult(
            source="WB Stocks products",
            endpoint="/api/v2/stocks-report/products/products",
            method="POST",
            status=status,
            http_status=status_code,
            objects_count=objects_count,
            fields_found=fields_found,
            fields_missing=fields_missing,
            error_short=error,
            mvp_usable="YES" if status == "OK" else ("PARTIAL" if status == "PARTIAL" else "NO"),
        )

    def run_wb_stocks_offices(self) -> SmokeResult:
        if not settings.wb_analytics_token:
            return SmokeResult(
                source="WB Stocks offices",
                endpoint="/api/v2/stocks-report/offices",
                method="POST",
                status="SKIPPED",
                http_status="N/A",
                objects_count=0,
                fields_found=[],
                fields_missing=["region", "warehouse", "quantity"],
                error_short="WB_ANALYTICS_TOKEN is missing",
                mvp_usable="NO",
            )

        payload = {
            "currentPeriod": {"start": self.date_to.isoformat(), "end": self.date_to.isoformat()},
            "stockType": "",
            "skipDeletedNm": False,
            "availabilityFilters": [],
            "orderBy": {"field": "stockCount", "mode": "desc"},
            "limit": 50,
            "offset": 0,
        }
        status_code, data, error = self._request(
            "POST",
            f"{WB_ANALYTICS_BASE}/api/v2/stocks-report/offices",
            self._analytics_headers(),
            json_body=payload,
        )
        self._throttle_analytics()
        fields_map = {
            "region": ["regionName"],
            "warehouse": ["officeName", "warehouseName", "offices"],
            "quantity": ["quantity", "stockCount"],
        }
        fields_found = [name for name, candidates in fields_map.items() if has_key(data, candidates)]
        fields_missing = [name for name in fields_map if name not in fields_found]
        objects_count = len(list_from_path(data, ["data", "items"])) or len(list_from_path(data, ["data", "groups"]))
        status = "OK" if status_code == "200" and objects_count > 0 and not fields_missing else "PARTIAL"
        if status_code != "200":
            status = "FAIL"
        return SmokeResult(
            source="WB Stocks offices",
            endpoint="/api/v2/stocks-report/offices",
            method="POST",
            status=status,
            http_status=status_code,
            objects_count=objects_count,
            fields_found=fields_found,
            fields_missing=fields_missing,
            error_short=error,
            mvp_usable="PARTIAL" if status in {"OK", "PARTIAL"} else "NO",
            notes="useful for regional/detail view, not enough alone for full stock snapshot",
        )

    def _get_campaign_ids(self) -> tuple[list[int], str, str]:
        status_code, data, error = self._request(
            "GET",
            f"{WB_PROMOTION_BASE}/adv/v1/promotion/count",
            self._promotion_headers(),
        )
        ids: list[int] = []
        adverts = data.get("adverts", []) if isinstance(data, dict) else []
        for advert_group in adverts:
            if not isinstance(advert_group, dict):
                continue
            for advert in advert_group.get("advert_list", []) or []:
                advert_id = advert.get("advertId")
                if isinstance(advert_id, int):
                    ids.append(advert_id)
        return ids[:3], status_code, error

    def run_wb_adv_costs(self) -> SmokeResult:
        if not settings.wb_token:
            return SmokeResult(
                source="WB Promotion costs",
                endpoint="/adv/v1/upd",
                method="GET",
                status="SKIPPED",
                http_status="N/A",
                objects_count=0,
                fields_found=[],
                fields_missing=["advertId", "campaign_name", "writeoff_date", "sum", "document_number"],
                error_short="WB_TOKEN is missing",
                mvp_usable="NO",
            )

        time.sleep(1.1)
        status_code, data, error = self._request(
            "GET",
            f"{WB_PROMOTION_BASE}/adv/v1/upd",
            self._promotion_headers(),
            params={"from": self.date_from.isoformat(), "to": self.date_to.isoformat()},
        )
        fields_map = {
            "advertId": ["advertId"],
            "campaign_name": ["campName"],
            "writeoff_date": ["updTime"],
            "sum": ["updSum"],
            "document_number": ["updNum"],
        }
        fields_found = [name for name, candidates in fields_map.items() if has_key(data, candidates)]
        fields_missing = [name for name in fields_map if name not in fields_found]
        objects_count = first_list_length(data, [])
        status = "OK" if status_code == "200" and objects_count > 0 and not fields_missing else "PARTIAL"
        if status_code != "200":
            status = "FAIL"
        return SmokeResult(
            source="WB Promotion costs",
            endpoint="/adv/v1/upd",
            method="GET",
            status=status,
            http_status=status_code,
            objects_count=objects_count,
            fields_found=fields_found,
            fields_missing=fields_missing,
            error_short=error,
            mvp_usable="YES" if status == "OK" else ("PARTIAL" if status == "PARTIAL" else "NO"),
        )

    def run_wb_adv_fullstats(self) -> SmokeResult:
        if not settings.wb_token:
            return SmokeResult(
                source="WB Promotion fullstats",
                endpoint="/adv/v3/fullstats",
                method="GET",
                status="SKIPPED",
                http_status="N/A",
                objects_count=0,
                fields_found=[],
                fields_missing=["date", "advertId", "campaign_name", "nm_id", "views", "clicks", "atbs", "orders"],
                error_short="WB_TOKEN is missing",
                mvp_usable="NO",
            )

        campaign_ids, count_status, count_error = self._get_campaign_ids()
        if count_status != "200" or not campaign_ids:
            return SmokeResult(
                source="WB Promotion fullstats",
                endpoint="/adv/v3/fullstats",
                method="GET",
                status="PARTIAL" if count_status == "200" else "FAIL",
                http_status=count_status,
                objects_count=0,
                fields_found=[],
                fields_missing=["campaign_ids"],
                error_short=truncate_error(count_error or "campaign ids were not returned by /adv/v1/promotion/count"),
                mvp_usable="NO",
                notes="fullstats requires campaign ids from count helper",
            )

        time.sleep(1.1)
        status_code, data, error = self._request(
            "GET",
            f"{WB_PROMOTION_BASE}/adv/v3/fullstats",
            self._promotion_headers(),
            params={
                "ids": ",".join(map(str, campaign_ids)),
                "beginDate": self.date_from.isoformat(),
                "endDate": self.date_to.isoformat(),
            },
        )
        fields_map = {
            "date": ["date"],
            "advertId": ["advertId"],
            "campaign_name": ["name", "campName"],
            "row_type": ["appType"],
            "conversion_type": ["boosterStats", "apps"],
            "nm_id": ["nmId"],
            "ad_spend": ["sum"],
            "ad_revenue": ["sum_price"],
            "views": ["views"],
            "clicks": ["clicks"],
            "atbs": ["atbs"],
            "orders": ["orders"],
            "ctr": ["ctr"],
            "cpc": ["cpc"],
            "cpm": ["cpm"],
            "cr": ["cr"],
            "roi": ["roi"],
        }
        fields_found = [name for name, candidates in fields_map.items() if has_key(data, candidates)]
        fields_missing = [name for name in fields_map if name not in fields_found]
        objects_count = count_matching_dicts(data, ["advertId"]) or first_list_length(data, [])
        status = "OK" if status_code == "200" and objects_count > 0 and not fields_missing else "PARTIAL"
        if status_code != "200":
            status = "FAIL"
        return SmokeResult(
            source="WB Promotion fullstats",
            endpoint="/adv/v3/fullstats",
            method="GET",
            status=status,
            http_status=status_code,
            objects_count=objects_count,
            fields_found=fields_found,
            fields_missing=fields_missing,
            error_short=error,
            mvp_usable="PARTIAL" if status in {"OK", "PARTIAL"} else "NO",
            notes=(
                "200 with null body for selected campaign ids/date window"
                if status_code == "200" and data is None
                else "nested fullstats structure is suitable for RK stats but may need transformation for CPM/ROI and conversion types"
            ),
        )

    def run_wb_search_texts(self) -> tuple[SmokeResult, list[str], int | None]:
        if not settings.wb_analytics_token:
            return (
                SmokeResult(
                    source="WB Search texts",
                    endpoint="/api/v2/search-report/product/search-texts",
                    method="POST",
                    status="SKIPPED",
                    http_status="N/A",
                    objects_count=0,
                    fields_found=[],
                    fields_missing=["search_query", "query_count", "visibility", "avg_position", "median_position", "clicks", "carts", "orders"],
                    error_short="WB_ANALYTICS_TOKEN is missing",
                    mvp_usable="NO",
                ),
                [],
                None,
            )

        payload = {
            "currentPeriod": {"start": self.date_to.isoformat(), "end": self.date_to.isoformat()},
            "pastPeriod": {"start": self.date_from.isoformat(), "end": self.date_from.isoformat()},
            "nmIds": TEST_NM_IDS,
            "topOrderBy": "openCard",
            "includeSubstitutedSKUs": True,
            "includeSearchTexts": True,
            "orderBy": {"field": "avgPosition", "mode": "asc"},
            "limit": 10,
        }
        status_code, data, error = self._request(
            "POST",
            f"{WB_ANALYTICS_BASE}/api/v2/search-report/product/search-texts",
            self._analytics_headers(),
            json_body=payload,
        )
        self._throttle_analytics()
        fields_map = {
            "search_query": ["text"],
            "query_count": ["frequency"],
            "visibility": ["visibility"],
            "avg_position": ["avgPosition"],
            "median_position": ["medianPosition"],
            "clicks": ["openCard"],
            "carts": ["addToCart"],
            "orders": ["orders"],
        }
        fields_found = [name for name, candidates in fields_map.items() if has_key(data, candidates)]
        fields_missing = [name for name in fields_map if name not in fields_found]
        objects_count = first_list_length(data, ["items"])
        status = "OK" if status_code == "200" and objects_count > 0 and not fields_missing else "PARTIAL"
        if status_code != "200":
            status = "FAIL"

        search_texts: list[str] = []
        nm_id: int | None = None
        items = (((data or {}).get("data") or {}).get("items") or []) if isinstance(data, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text:
                search_texts.append(text)
            candidate_nm = item.get("nmId")
            if nm_id is None and isinstance(candidate_nm, int):
                nm_id = candidate_nm
        return (
            SmokeResult(
                source="WB Search texts",
                endpoint="/api/v2/search-report/product/search-texts",
                method="POST",
                status=status,
                http_status=status_code,
                objects_count=objects_count,
                fields_found=fields_found,
                fields_missing=fields_missing,
                error_short=error,
                mvp_usable="YES" if status == "OK" else ("PARTIAL" if status == "PARTIAL" else "NO"),
                notes="Jam endpoint",
            ),
            search_texts[:3],
            nm_id,
        )

    def run_wb_search_orders(self, nm_id: int | None, search_texts: list[str]) -> SmokeResult:
        if not settings.wb_analytics_token:
            return SmokeResult(
                source="WB Search orders",
                endpoint="/api/v2/search-report/product/orders",
                method="POST",
                status="SKIPPED",
                http_status="N/A",
                objects_count=0,
                fields_found=[],
                fields_missing=["search_query", "avg_position", "orders"],
                error_short="WB_ANALYTICS_TOKEN is missing",
                mvp_usable="NO",
            )
        if not nm_id or not search_texts:
            return SmokeResult(
                source="WB Search orders",
                endpoint="/api/v2/search-report/product/orders",
                method="POST",
                status="PARTIAL",
                http_status="N/A",
                objects_count=0,
                fields_found=[],
                fields_missing=["searchTexts"],
                error_short="search texts were not available from the previous endpoint",
                mvp_usable="NO",
                notes="dependent on search-texts response",
            )

        payload = {
            "period": {"start": self.date_from.isoformat(), "end": self.date_to.isoformat()},
            "nmId": nm_id,
            "searchTexts": search_texts,
        }
        status_code, data, error = self._request(
            "POST",
            f"{WB_ANALYTICS_BASE}/api/v2/search-report/product/orders",
            self._analytics_headers(),
            json_body=payload,
        )
        self._throttle_analytics()
        fields_map = {
            "search_query": ["text"],
            "avg_position": ["avgPosition"],
            "orders": ["orders"],
            "date": ["dt"],
        }
        fields_found = [name for name, candidates in fields_map.items() if has_key(data, candidates)]
        fields_missing = [name for name in fields_map if name not in fields_found]
        objects_count = first_list_length(data, ["items", "total"])
        status = "OK" if status_code == "200" and objects_count > 0 and not fields_missing else "PARTIAL"
        if status_code != "200":
            status = "FAIL"
        return SmokeResult(
            source="WB Search orders",
            endpoint="/api/v2/search-report/product/orders",
            method="POST",
            status=status,
            http_status=status_code,
            objects_count=objects_count,
            fields_found=fields_found,
            fields_missing=fields_missing,
            error_short=error,
            mvp_usable="PARTIAL" if status in {"OK", "PARTIAL"} else "NO",
            notes="gives daily orders and positions, not full visibility/click metrics",
        )

    def run_mpstat(self) -> SmokeResult:
        if not settings.mpstats_api_token:
            return SmokeResult(
                source="MPStat",
                endpoint="/item/{nm_id}",
                method="GET",
                status="SKIPPED",
                http_status="N/A",
                objects_count=0,
                fields_found=[],
                fields_missing=["auth", "connectivity"],
                error_short="MPSTATS_API_TOKEN is missing",
                mvp_usable="NO",
            )

        status_code, data, error = self._request(
            "GET",
            f"{MPSTAT_BASE}/item/{TEST_NM_IDS[0]}",
            self._mpstat_headers(),
            params={"d1": self.date_from.isoformat(), "d2": self.date_to.isoformat()},
        )
        fields_map = {
            "nm_id": ["nmId", "id", "item_id"],
            "title": ["name", "title"],
            "brand": ["brand", "brandName"],
        }
        fields_found = [name for name, candidates in fields_map.items() if has_key(data, candidates)]
        fields_missing = [name for name in fields_map if name not in fields_found]
        objects_count = 1 if status_code == "200" and data else 0
        status = "OK" if status_code == "200" and objects_count > 0 else "FAIL"
        if status == "OK" and fields_missing:
            status = "PARTIAL"
        return SmokeResult(
            source="MPStat",
            endpoint="/item/{nm_id}",
            method="GET",
            status=status,
            http_status=status_code,
            objects_count=objects_count,
            fields_found=fields_found,
            fields_missing=fields_missing,
            error_short=error,
            mvp_usable="PARTIAL" if status in {"OK", "PARTIAL"} else "NO",
            notes="connectivity/auth check only",
        )


def main() -> int:
    runner = SafeSmokeRunner()
    results: list[SmokeResult] = []

    google_result, sheet_titles = runner.run_google_sheets()
    results.append(google_result)
    results.append(runner.run_wb_content_cards())
    results.append(runner.run_wb_sales_funnel())
    results.append(runner.run_wb_stocks_products())
    results.append(runner.run_wb_stocks_offices())
    results.append(runner.run_wb_adv_costs())
    results.append(runner.run_wb_adv_fullstats())
    search_texts_result, search_texts, search_nm_id = runner.run_wb_search_texts()
    results.append(search_texts_result)
    results.append(runner.run_wb_search_orders(search_nm_id, search_texts))
    results.append(runner.run_mpstat())

    backlog_updates = append_backlog_updates(results)
    write_markdown_report(
        DOCS_REPORT_PATH,
        runner.date_from,
        runner.date_to,
        results,
        sheet_titles,
        backlog_updates,
    )
    write_csv_report(CSV_REPORT_PATH, results)
    write_json_summary(
        JSON_SUMMARY_PATH,
        runner.date_from,
        runner.date_to,
        results,
        sheet_titles,
        backlog_updates,
    )

    print(f"Markdown report: {DOCS_REPORT_PATH}")
    print(f"CSV report: {CSV_REPORT_PATH}")
    print(f"JSON summary: {JSON_SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
