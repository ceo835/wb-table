from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import csv
import json
import time

import requests

from src.config.settings import settings


ROOT_DIR = Path(__file__).resolve().parents[2]
DOCS_REPORT_PATH = ROOT_DIR / "docs" / "endpoint_gap_audit_report.md"
CSV_REPORT_PATH = ROOT_DIR / "data" / "processed" / "endpoint_gap_audit_report.csv"
JSON_SUMMARY_PATH = ROOT_DIR / "data" / "processed" / "endpoint_gap_audit_summary.json"

TEST_NM_IDS = [197330807, 37320545, 37342770, 36387055, 577510563]
TEST_DATE_TO = date(2026, 6, 1)
TEST_DATE_FROM = date(2026, 5, 31)

WB_CONTENT_BASE = "https://content-api.wildberries.ru"
WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"
WB_PROMOTION_BASE = "https://advert-api.wildberries.ru"
WB_STATISTICS_BASE = "https://statistics-api.wildberries.ru"
MPSTAT_BASE = "https://mpstats.io/api/wb/get"


@dataclass(frozen=True)
class FieldSpec:
    field: str
    paths: tuple[tuple[str, ...], ...]
    source_type: str
    missing_status: str
    next_step: str
    employee_question: str
    evidence_found: str = "present in live response"
    evidence_missing: str = "not found in tested response"
    found_status: str = "FOUND"


@dataclass(frozen=True)
class FieldResult:
    block: str
    field: str
    status: str
    source_type: str
    endpoint: str
    http_status: str
    evidence_short: str
    next_step: str
    employee_question: str


@dataclass(frozen=True)
class EndpointResult:
    name: str
    endpoint: str
    method: str
    http_status: str
    payload: Any
    error_short: str
    objects_count: int
    note: str = ""


@dataclass(frozen=True)
class BlockResult:
    block: str
    endpoint_tested: str
    method: str
    status: str
    http_status: str
    fields_found: list[str]
    fields_not_found: list[str]
    next_step: str
    employee_question: str
    details: str = ""


def normalize_key(key: str) -> str:
    return key.replace("_", "").replace("-", "").lower()


def truncate_error(error: str | None, limit: int = 180) -> str:
    if not error:
        return ""
    return " ".join(str(error).split())[:limit]


def _value_present(value: Any) -> bool:
    return value not in (None, "", [], {})


def has_path_anywhere(payload: Any, path: tuple[str, ...]) -> bool:
    if not path:
        return _value_present(payload)

    key = path[0]
    rest = path[1:]

    if isinstance(payload, dict):
        if key in payload and has_path_anywhere(payload[key], rest):
            return True
        return any(has_path_anywhere(value, path) for value in payload.values())

    if isinstance(payload, list):
        return any(has_path_anywhere(item, path) for item in payload)

    return False


def first_list_length(payload: Any, preferred_keys: tuple[str, ...] = ()) -> int:
    if isinstance(payload, dict):
        for key in preferred_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return len(value)
        for value in payload.values():
            length = first_list_length(value, preferred_keys)
            if length:
                return length
    elif isinstance(payload, list):
        return len(payload)
    return 0


def _extract_list(payload: Any, preferred_keys: tuple[str, ...] = ()) -> list[Any]:
    if isinstance(payload, dict):
        for key in preferred_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
        for value in payload.values():
            nested = _extract_list(value, preferred_keys)
            if nested:
                return nested
    elif isinstance(payload, list):
        return payload
    return []


def _extract_first_dict(payload: Any, preferred_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    items = _extract_list(payload, preferred_keys)
    first = items[0] if items and isinstance(items[0], dict) else {}
    return first


def _find_download_id(payload: Any) -> str:
    for item in _extract_list(payload, ("data",)):
        if isinstance(item, dict):
            download_id = item.get("id") or item.get("downloadId")
            if download_id:
                return str(download_id)
    return ""


def _payload_summary(payload: Any) -> str:
    if payload is None:
        return "empty response"
    if isinstance(payload, list):
        return f"list[{len(payload)}]"
    if isinstance(payload, dict):
        keys = list(payload)[:8]
        return f"dict keys={keys}"
    return type(payload).__name__


def _field_result(
    block: str,
    endpoint: str,
    http_status: str,
    payloads: list[Any],
    spec: FieldSpec,
) -> FieldResult:
    found_path: tuple[str, ...] | None = None
    for payload in payloads:
        for path in spec.paths:
            if has_path_anywhere(payload, path):
                found_path = path
                break
        if found_path:
            break

    if found_path:
        return FieldResult(
            block=block,
            field=spec.field,
            status=spec.found_status,
            source_type=spec.source_type,
            endpoint=endpoint,
            http_status=http_status,
            evidence_short=f"found path {'/'.join(found_path)}",
            next_step=spec.next_step,
            employee_question=spec.employee_question,
        )

    return FieldResult(
        block=block,
        field=spec.field,
        status=spec.missing_status,
        source_type=spec.source_type,
        endpoint=endpoint,
        http_status=http_status,
        evidence_short=spec.evidence_missing,
        next_step=spec.next_step,
        employee_question=spec.employee_question,
    )


class EndpointGapAuditRunner:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.test_date_from = TEST_DATE_FROM
        self.test_date_to = TEST_DATE_TO
        self.loaded_at = datetime.now().isoformat(timespec="seconds")

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
            payload = response.json()
        except ValueError:
            payload = response.text
        if response.status_code >= 400:
            return status, payload, truncate_error(response.text or response.reason)
        return status, payload, ""

    def _wb_headers(self) -> dict[str, str]:
        return {
            "Authorization": settings.wb_token or "",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _analytics_headers(self) -> dict[str, str]:
        return {
            "Authorization": settings.wb_analytics_token or "",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _promotion_headers(self) -> dict[str, str]:
        return {
            "Authorization": settings.wb_token or "",
            "Accept": "application/json",
        }

    def _mpstat_headers(self) -> dict[str, str]:
        return {
            "X-Mpstats": settings.mpstats_api_token or "",
            "Accept": "application/json",
        }

    def _funnel_payload(self) -> dict[str, Any]:
        return {
            "selectedPeriod": {
                "start": self.test_date_from.isoformat(),
                "end": self.test_date_to.isoformat(),
            },
            "nmIds": TEST_NM_IDS,
            "skipDeletedNm": True,
            "aggregationLevel": "day",
        }

    def _search_payload(self) -> dict[str, Any]:
        past_end = self.test_date_from - timedelta(days=1)
        past_start = past_end - (self.test_date_to - self.test_date_from)
        return {
            "currentPeriod": {
                "start": self.test_date_from.isoformat(),
                "end": self.test_date_to.isoformat(),
            },
            "pastPeriod": {
                "start": past_start.isoformat(),
                "end": past_end.isoformat(),
            },
            "nmIds": TEST_NM_IDS,
            "topOrderBy": "openCard",
            "includeSubstitutedSKUs": True,
            "includeSearchTexts": True,
            "orderBy": {"field": "avgPosition", "mode": "asc"},
            "limit": 100,
        }

    def _stocks_payload(self) -> dict[str, Any]:
        return {
            "nmIDs": TEST_NM_IDS,
            "currentPeriod": {
                "start": self.test_date_to.isoformat(),
                "end": self.test_date_to.isoformat(),
            },
            "stockType": "",
            "skipDeletedNm": False,
            "availabilityFilters": [],
            "orderBy": {"field": "avgOrders", "mode": "asc"},
            "limit": 50,
            "offset": 0,
        }

    def _run_funnel(self) -> tuple[BlockResult, list[FieldResult], list[EndpointResult]]:
        endpoint_results: list[EndpointResult] = []

        history_status, history_payload, history_error = self._request(
            "POST",
            f"{WB_ANALYTICS_BASE}/api/analytics/v3/sales-funnel/products/history",
            self._analytics_headers(),
            json_body=self._funnel_payload(),
        )
        history_objects = first_list_length(history_payload, ("data", "products"))
        endpoint_results.append(
            EndpointResult(
                name="sales-funnel/products/history",
                endpoint="/api/analytics/v3/sales-funnel/products/history",
                method="POST",
                http_status=history_status,
                payload=history_payload,
                error_short=history_error,
                objects_count=history_objects,
                note="daily funnel over the requested window",
            )
        )

        products_status, products_payload, products_error = self._request(
            "POST",
            f"{WB_ANALYTICS_BASE}/api/analytics/v3/sales-funnel/products",
            self._analytics_headers(),
            json_body=self._funnel_payload(),
        )
        products_objects = first_list_length(products_payload, ("data", "products"))
        endpoint_results.append(
            EndpointResult(
                name="sales-funnel/products",
                endpoint="/api/analytics/v3/sales-funnel/products",
                method="POST",
                http_status=products_status,
                payload=products_payload,
                error_short=products_error,
                objects_count=products_objects,
                note="selected/past/comparison view for comparison fields",
            )
        )

        field_specs = [
            FieldSpec("date", (("date",), ("history", "date"), ("selected", "date")), "WB", "PARTIAL", "history date", "Need to keep history output for daily granularity"),
            FieldSpec("nm_id", (("nmId",), ("nmID",)), "WB", "PARTIAL", "WB nmId", "Need to keep history output for daily granularity"),
            FieldSpec("impressions", (("openCount",), ("impressions",), ("selected", "openCount")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("card_clicks", (("openCard",), ("cardClicks",), ("selected", "openCard")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("cartCount", (("cartCount",), ("selected", "cartCount")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("orderCount", (("orderCount",), ("selected", "orderCount")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("orderSum", (("orderSum",), ("selected", "orderSum")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("buyoutSum", (("buyoutSum",), ("selected", "buyoutSum")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("cancelCount", (("cancelCount",), ("selected", "cancelCount")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("cancelSum", (("cancelSum",), ("selected", "cancelSum")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("avgPrice", (("avgPrice",), ("selected", "avgPrice")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("avgOrdersCountPerDay", (("avgOrdersCountPerDay",), ("selected", "avgOrdersCountPerDay")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("shareOrderPercent", (("shareOrderPercent",), ("selected", "shareOrderPercent")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("addToWishlist", (("addToWishlistCount",), ("addToWishlist",), ("selected", "addToWishlistCount")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("timeToReady", (("timeToReady",), ("avgDeliveryTime",), ("selected", "timeToReady")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("localizationPercent", (("localizationPercent",), ("selected", "localizationPercent")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("wbClub", (("wbClub",), ("selected", "wbClub")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("productRating", (("productRating",), ("selected", "productRating")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("feedbackRating", (("feedbackRating",), ("selected", "feedbackRating")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("wb_stock_qty", (("stockCount",), ("stocks", "wb", "stockCount"), ("selected", "stockCount")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("mp_stock_qty", (("mpStockCount",), ("stocks", "mp", "stockCount"), ("selected", "mpStockCount")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("stock_total_sum", (("stockSum",), ("balanceSum",), ("stocks", "balanceSum"), ("selected", "stockSum")), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
            FieldSpec("past_period", (("past",), ("pastPeriod",), ("comparison",)), "WB", "PARTIAL", "Need to keep history output for daily granularity", "confirm source if missing in history"),
        ]

        field_results = []
        for spec in field_specs:
            field_results.append(
                _field_result(
                    "Воронка на день",
                    "/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history",
                    history_status if history_status != "200" else products_status,
                    [history_payload, products_payload],
                    spec,
                )
            )

        fields_found = [row.field for row in field_results if row.status == "FOUND"]
        fields_not_found = [row.field for row in field_results if row.status != "FOUND"]
        if history_status in {"401", "403", "402"} or products_status in {"401", "403", "402"}:
            block_status = "NEEDS_ACCESS"
        elif any(row.status in {"PARTIAL", "CSV_ONLY", "NOT_FOUND"} for row in field_results):
            block_status = "PARTIAL"
        else:
            block_status = "FOUND"
        summary = BlockResult(
            block="Воронка на день",
            endpoint_tested="/api/analytics/v3/sales-funnel/products; /api/analytics/v3/sales-funnel/products/history",
            method="POST",
            status=block_status,
            http_status=products_status if products_status != "200" else history_status,
            fields_found=fields_found,
            fields_not_found=fields_not_found,
            next_step="Keep history for day-level rows and use products endpoint for the comparison block and extra funnel fields.",
            employee_question="Need confirmation only if the products endpoint still omits past-period or localization fields.",
            details=_payload_summary(products_payload if products_status == "200" else history_payload),
        )
        return summary, field_results, endpoint_results

    def _run_search(self) -> tuple[BlockResult, list[FieldResult], list[EndpointResult]]:
        endpoint_results: list[EndpointResult] = []
        payload = self._search_payload()

        search_specs = [
            ("search-texts", "/api/v2/search-report/product/search-texts", "POST"),
            ("search-orders", "/api/v2/search-report/product/orders", "POST"),
            ("search-report", "/api/v2/search-report/report", "POST"),
            ("table-groups", "/api/v2/search-report/table/groups", "POST"),
            ("table-details", "/api/v2/search-report/table/details", "POST"),
        ]
        payloads: list[Any] = []
        statuses: list[str] = []
        for name, endpoint, method in search_specs:
            status, body, error = self._request(
                method,
                f"{WB_ANALYTICS_BASE}{endpoint}",
                self._analytics_headers(),
                json_body=payload,
            )
            payloads.append(body)
            statuses.append(status)
            endpoint_results.append(
                EndpointResult(
                    name=name,
                    endpoint=endpoint,
                    method=method,
                    http_status=status,
                    payload=body,
                    error_short=error,
                    objects_count=first_list_length(body, ("data", "items", "total")),
                    note=_payload_summary(body),
                )
            )

        field_specs = [
            FieldSpec("search_query", (("text",), ("searchQuery",), ("query",)), "WB", "PARTIAL", "use search-texts/search-orders plus maybe CSV export", "Need to confirm the source of any missing competitor-derived query values"),
            FieldSpec("query_count", (("frequency",), ("weekFrequency",), ("items", "frequency"), ("total", "orders")), "WB", "PARTIAL", "use search-texts/search-orders plus maybe CSV export", "Need to confirm whether frequency should come from current or weekly period"),
            FieldSpec("visibility", (("visibility",), ("items", "visibility")), "WB", "PARTIAL", "use search-texts/search-orders plus maybe CSV export", "Need to confirm whether visibility is available directly or only via Jam/export"),
            FieldSpec("visibility_prev", (("visibility", "dynamics"), ("items", "visibility", "dynamics")), "WB", "NEEDS_FORMULA", "previous period can be reconstructed from current and dynamics", "Need confirmation only if a direct previous-period field is required"),
            FieldSpec("avg_position", (("avgPosition",), ("items", "avgPosition"), ("total", "avgPosition")), "WB", "PARTIAL", "use search-texts/search-orders plus maybe CSV export", "Need to confirm if search-report/table/* returns a better position source"),
            FieldSpec("avg_position_prev", (("avgPosition", "dynamics"), ("items", "avgPosition", "dynamics")), "WB", "NEEDS_FORMULA", "previous period can be reconstructed from current and dynamics", "Need confirmation only if a direct previous-period field is required"),
            FieldSpec("median_position", (("medianPosition",), ("items", "medianPosition")), "WB", "PARTIAL", "use search-texts/search-orders plus maybe CSV export", "Need to confirm if search-report/table/* returns a better position source"),
            FieldSpec("median_position_prev", (("medianPosition", "dynamics"), ("items", "medianPosition", "dynamics")), "WB", "NEEDS_FORMULA", "previous period can be reconstructed from current and dynamics", "Need confirmation only if a direct previous-period field is required"),
            FieldSpec("search_clicks", (("openCard",), ("clicks",), ("items", "openCard"), ("items", "clicks")), "WB", "PARTIAL", "use search-texts/search-orders plus maybe CSV export", "Need confirmation only if a direct search-report endpoint is expected"),
            FieldSpec("search_clicks_prev", (("openCard", "dynamics"), ("clicks", "dynamics"), ("items", "openCard", "dynamics")), "WB", "NEEDS_FORMULA", "previous period can be reconstructed from current and dynamics", "Need confirmation only if a direct previous-period field is required"),
            FieldSpec("search_clicks_competitor_percentile", (("openCard", "percentile"), ("items", "openCard", "percentile")), "WB", "CSV_ONLY", "competitor percentile likely comes from Jam/export or a private report", "Is there a CSV/UI export for competitor percentiles?"),
            FieldSpec("search_cart", (("addToCart",), ("carts",), ("items", "addToCart")), "WB", "PARTIAL", "use search-texts/search-orders plus maybe CSV export", "Need confirmation only if a direct search-report endpoint is expected"),
            FieldSpec("search_cart_prev", (("addToCart", "dynamics"), ("items", "addToCart", "dynamics")), "WB", "NEEDS_FORMULA", "previous period can be reconstructed from current and dynamics", "Need confirmation only if a direct previous-period field is required"),
            FieldSpec("search_cart_competitor_percentile", (("addToCart", "percentile"), ("items", "addToCart", "percentile")), "WB", "CSV_ONLY", "competitor percentile likely comes from Jam/export or a private report", "Is there a CSV/UI export for competitor percentiles?"),
            FieldSpec("cart_conversion", (("cartToOrder",), ("items", "cartToOrder")), "WB", "PARTIAL", "use search-texts/search-orders plus maybe CSV export", "Need confirmation only if a direct search-report endpoint is expected"),
            FieldSpec("cart_conversion_prev", (("cartToOrder", "dynamics"), ("items", "cartToOrder", "dynamics")), "WB", "NEEDS_FORMULA", "previous period can be reconstructed from current and dynamics", "Need confirmation only if a direct previous-period field is required"),
            FieldSpec("cart_conversion_competitor_percentile", (("cartToOrder", "percentile"), ("items", "cartToOrder", "percentile")), "WB", "CSV_ONLY", "competitor percentile likely comes from Jam/export or a private report", "Is there a CSV/UI export for competitor percentiles?"),
            FieldSpec("search_orders", (("orders",), ("items", "orders"), ("total", "orders")), "WB", "PARTIAL", "use search-texts/search-orders plus maybe CSV export", "Need confirmation only if a direct search-report endpoint is expected"),
            FieldSpec("search_orders_prev", (("orders", "dynamics"), ("items", "orders", "dynamics")), "WB", "NEEDS_FORMULA", "previous period can be reconstructed from current and dynamics", "Need confirmation only if a direct previous-period field is required"),
            FieldSpec("search_orders_competitor_percentile", (("orders", "percentile"), ("items", "orders", "percentile")), "WB", "CSV_ONLY", "competitor percentile likely comes from Jam/export or a private report", "Is there a CSV/UI export for competitor percentiles?"),
            FieldSpec("order_conversion", (("orderConversion",), ("items", "orderConversion")), "WB", "CSV_ONLY", "requires a dedicated report/table endpoint if it is not returned by search-texts", "Does a search report endpoint expose order conversion directly?"),
            FieldSpec("order_conversion_prev", (("orderConversion", "dynamics"), ("items", "orderConversion", "dynamics")), "WB", "NEEDS_FORMULA", "previous period can be reconstructed from current and dynamics", "Need confirmation only if a direct previous-period field is required"),
            FieldSpec("order_conversion_competitor_percentile", (("orderConversion", "percentile"), ("items", "orderConversion", "percentile")), "WB", "CSV_ONLY", "competitor percentile likely comes from Jam/export or a private report", "Is there a CSV/UI export for competitor percentiles?"),
            FieldSpec("min_discount_price", (("minDiscountPrice",), ("min_discount_price",), ("items", "minDiscountPrice")), "WB", "CSV_ONLY", "likely available only through a table/export report", "Does search-report/table/details expose min/max discount price?"),
            FieldSpec("max_discount_price", (("maxDiscountPrice",), ("max_discount_price",), ("items", "maxDiscountPrice")), "WB", "CSV_ONLY", "likely available only through a table/export report", "Does search-report/table/details expose min/max discount price?"),
        ]

        field_results = [
            _field_result(
                "Поисковые запросы",
                "/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details",
                ";".join(statuses),
                payloads,
                spec,
            )
            for spec in field_specs
        ]
        fields_found = [row.field for row in field_results if row.status in {"FOUND", "NEEDS_FORMULA"}]
        fields_not_found = [row.field for row in field_results if row.status not in {"FOUND", "NEEDS_FORMULA"}]
        if any(status in {"401", "403", "402"} for status in statuses):
            block_status = "NEEDS_ACCESS"
        elif any(status in {"200"} for status in statuses) and fields_not_found:
            block_status = "PARTIAL"
        elif any(status in {"200"} for status in statuses):
            block_status = "FOUND"
        else:
            block_status = "NOT_FOUND"
        summary = BlockResult(
            block="Поисковые запросы",
            endpoint_tested=", ".join(endpoint for _name, endpoint, _method in search_specs),
            method="POST",
            status=block_status,
            http_status=";".join(statuses),
            fields_found=fields_found,
            fields_not_found=fields_not_found,
            next_step="Keep search-texts and search-orders; competitor percentile columns likely need Jam/export or a private search report.",
            employee_question="Do we have a supported export/private report for competitor percentiles and min/max discount price?",
            details="search-texts/search-orders are live; table/report endpoints were probed for extra search metrics",
        )
        return summary, field_results, endpoint_results

    def _run_ads(self) -> tuple[BlockResult, list[FieldResult], list[EndpointResult]]:
        endpoint_results: list[EndpointResult] = []

        count_status, count_payload, count_error = self._request(
            "GET",
            f"{WB_PROMOTION_BASE}/adv/v1/promotion/count",
            self._promotion_headers(),
        )
        advert_ids: list[int] = []
        if isinstance(count_payload, dict):
            for group in count_payload.get("adverts", []):
                if not isinstance(group, dict):
                    continue
                if str(group.get("status")) not in {"7", "9", "11"}:
                    continue
                for advert in group.get("advert_list", []) or []:
                    advert_id = advert.get("advertId")
                    if isinstance(advert_id, int):
                        advert_ids.append(advert_id)
        endpoint_results.append(
            EndpointResult(
                name="promotion-count",
                endpoint="/adv/v1/promotion/count",
                method="GET",
                http_status=count_status,
                payload=count_payload,
                error_short=count_error,
                objects_count=len(advert_ids),
                note="campaign ids for fullstats",
            )
        )

        time.sleep(1.0)
        costs_status, costs_payload, costs_error = self._request(
            "GET",
            f"{WB_PROMOTION_BASE}/adv/v1/upd",
            self._promotion_headers(),
            params={"from": self.test_date_from.isoformat(), "to": self.test_date_to.isoformat()},
        )
        endpoint_results.append(
            EndpointResult(
                name="promotion-costs",
                endpoint="/adv/v1/upd",
                method="GET",
                http_status=costs_status,
                payload=costs_payload,
                error_short=costs_error,
                objects_count=first_list_length(costs_payload),
                note="spend events by advertId",
            )
        )

        fullstats_payload = None
        fullstats_status = "N/A"
        fullstats_error = ""
        fullstats_windows = [
            (date(2026, 5, 31), date(2026, 6, 1)),
            (date(2026, 5, 24), date(2026, 6, 1)),
            (date(2026, 5, 1), date(2026, 6, 1)),
        ]
        for window_start, window_end in fullstats_windows:
            if not advert_ids:
                break
            time.sleep(1.0)
            status, payload, error = self._request(
                "GET",
                f"{WB_PROMOTION_BASE}/adv/v3/fullstats",
                self._promotion_headers(),
                params={
                    "ids": ",".join(map(str, advert_ids[:20])),
                    "beginDate": window_start.isoformat(),
                    "endDate": window_end.isoformat(),
                },
            )
            if status == "200" and _extract_list(payload):
                fullstats_payload = payload
                fullstats_status = status
                fullstats_error = error
                break
            if fullstats_payload is None:
                fullstats_payload = payload
                fullstats_status = status
                fullstats_error = error
        endpoint_results.append(
            EndpointResult(
                name="promotion-fullstats",
                endpoint="/adv/v3/fullstats",
                method="GET",
                http_status=fullstats_status,
                payload=fullstats_payload,
                error_short=fullstats_error,
                objects_count=first_list_length(fullstats_payload),
                note="tried 2026-05-31..2026-06-01, 2026-05-24..2026-06-01, 2026-05-01..2026-06-01",
            )
        )

        field_specs = [
            FieldSpec("advertId", (("advertId",), ("adverts", "advert_list", "advertId")), "WB", "PARTIAL", "use /adv/v1/promotion/count and /adv/v1/upd", "Need a stable campaign-to-product mapping for nm_id"),
            FieldSpec("campaign_name", (("campName",), ("campaignName",), ("name",)), "WB", "PARTIAL", "use /adv/v1/upd and/or count metadata", "Need a confirmed campaign name source for the sheet"),
            FieldSpec("writeoff_datetime", (("updTime",),), "WB", "PARTIAL", "use /adv/v1/upd", "Need to keep the time component instead of truncating to date"),
            FieldSpec("document_number", (("updNum",),), "WB", "PARTIAL", "use /adv/v1/upd", "Need the document number to keep event-level uniqueness"),
            FieldSpec("spend", (("updSum",),), "WB", "PARTIAL", "use /adv/v1/upd", "Need the spend amount as written-off sum"),
            FieldSpec("paymentType", (("paymentType",),), "WB", "PARTIAL", "use /adv/v1/upd", "Need to confirm whether payment type can replace name parsing"),
            FieldSpec("advertType", (("advertType",),), "WB", "PARTIAL", "use /adv/v1/upd", "Need to confirm whether campaign type can be mapped from advertType"),
            FieldSpec("advertStatus", (("advertStatus",),), "WB", "PARTIAL", "use /adv/v1/upd", "Need to keep the campaign status for filters and backlog"),
            FieldSpec("date", (("days", "date"), ("date",), ("days", "apps", "date")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need the date grain from fullstats"),
            FieldSpec("row_type", (("days", "apps", "appType"), ("boosterStats", "appType")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need to map the row type from nested fullstats structure"),
            FieldSpec("conversion_type", (("days", "apps", "nms", "name"), ("days", "apps", "appType")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need to clarify how the conversion type should be derived"),
            FieldSpec("nm_id", (("days", "apps", "nms", "nmId"), ("boosterStats", "nmId")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need the campaign-product join to keep nm_id"),
            FieldSpec("ad_spend", (("sum",), ("days", "sum"), ("days", "apps", "sum")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need the spend metric from fullstats"),
            FieldSpec("ad_revenue", (("sum_price",), ("days", "sum_price"), ("days", "apps", "sum_price")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need the revenue metric from fullstats"),
            FieldSpec("views", (("views",), ("days", "views"), ("days", "apps", "views"), ("days", "apps", "nms", "views")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need the views metric from fullstats"),
            FieldSpec("clicks", (("clicks",), ("days", "clicks"), ("days", "apps", "clicks"), ("days", "apps", "nms", "clicks")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need the clicks metric from fullstats"),
            FieldSpec("atbs", (("atbs",), ("days", "atbs"), ("days", "apps", "atbs"), ("days", "apps", "nms", "atbs")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need the atbs metric from fullstats"),
            FieldSpec("orders", (("orders",), ("days", "orders"), ("days", "apps", "orders"), ("days", "apps", "nms", "orders")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need the orders metric from fullstats"),
            FieldSpec("ctr", (("ctr",), ("days", "ctr"), ("days", "apps", "ctr"), ("days", "apps", "nms", "ctr")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need the CTR metric from fullstats"),
            FieldSpec("cpc", (("cpc",), ("days", "cpc"), ("days", "apps", "cpc"), ("days", "apps", "nms", "cpc")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need the CPC metric from fullstats"),
            FieldSpec("cpm", (("cpm",), ("days", "cpm"), ("days", "apps", "cpm")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need the CPM metric from fullstats"),
            FieldSpec("cr", (("cr",), ("days", "cr"), ("days", "apps", "cr"), ("days", "apps", "nms", "cr")), "WB", "PARTIAL", "use /adv/v3/fullstats", "Need the CR metric from fullstats"),
            FieldSpec("roi", (("roi",),), "WB", "NEEDS_FORMULA", "ROI may need a business formula if the endpoint does not expose it directly", "Need confirmation of the business ROI formula if not returned directly"),
        ]

        payloads = [costs_payload, fullstats_payload]
        field_results = [
            _field_result(
                "РК стата",
                "/adv/v1/upd; /adv/v3/fullstats",
                fullstats_status if fullstats_status != "200" else costs_status,
                payloads,
                spec,
            )
            for spec in field_specs
        ]
        fields_found = [row.field for row in field_results if row.status == "FOUND"]
        fields_not_found = [row.field for row in field_results if row.status != "FOUND"]
        if count_status in {"401", "403", "402"} or costs_status in {"401", "403", "402"} or fullstats_status in {"401", "403", "402"}:
            block_status = "NEEDS_ACCESS"
        elif fullstats_status == "200" and _extract_list(fullstats_payload):
            block_status = "PARTIAL" if any(row.status != "FOUND" for row in field_results) else "FOUND"
        elif costs_status == "200":
            block_status = "PARTIAL"
        else:
            block_status = "NOT_FOUND"
        summary = BlockResult(
            block="РК стата",
            endpoint_tested="/adv/v1/promotion/count; /adv/v1/upd; /adv/v3/fullstats",
            method="GET",
            status=block_status,
            http_status=";".join([count_status, costs_status, fullstats_status]),
            fields_found=fields_found,
            fields_not_found=fields_not_found,
            next_step="If fullstats stays null for the chosen windows, retry with another confirmed campaign set or confirm the exact campaign statuses that expose data.",
            employee_question="Can you confirm a campaign set and window where fullstats is guaranteed to return rows?",
            details=_payload_summary(fullstats_payload if _extract_list(fullstats_payload) else costs_payload),
        )
        return summary, field_results, endpoint_results

    def _run_stocks(self) -> tuple[BlockResult, list[FieldResult], list[EndpointResult]]:
        endpoint_results: list[EndpointResult] = []
        payload = self._stocks_payload()
        payloads: list[Any] = []
        statuses: list[str] = []

        specs = [
            ("stocks-products", "/api/v2/stocks-report/products/products", "POST"),
            ("stocks-offices", "/api/v2/stocks-report/offices", "POST"),
            ("wb-warehouses", "/api/analytics/v1/stocks-report/wb-warehouses", "GET"),
            ("stocks-sizes", "/api/v2/stocks-report/products/sizes", "POST"),
            ("stocks-groups", "/api/v2/stocks-report/products/groups", "POST"),
        ]
        for name, endpoint, method in specs:
            status, body, error = self._request(
                method,
                f"{WB_ANALYTICS_BASE}{endpoint}",
                self._analytics_headers(),
                json_body=payload if method == "POST" else None,
            )
            payloads.append(body)
            statuses.append(status)
            endpoint_results.append(
                EndpointResult(
                    name=name,
                    endpoint=endpoint,
                    method=method,
                    http_status=status,
                    payload=body,
                    error_short=error,
                    objects_count=first_list_length(body, ("data", "items", "regions")),
                    note=_payload_summary(body),
                )
            )

        field_specs = [
            FieldSpec("wb_stock_qty", (("stockCount",), ("metrics", "stockCount")), "WB", "PARTIAL", "current snapshot from stock products", "Need confirmation only if a regional breakdown is required"),
            FieldSpec("mp_stock_qty", (("mpStockCount",), ("metrics", "mpStockCount")), "WB", "PARTIAL", "not confirmed in the live stock snapshot", "Need a confirmed MP-stock or own-stock field from WB"),
            FieldSpec("stock_total_sum", (("stockSum",), ("balanceSum",), ("metrics", "stockSum")), "WB", "PARTIAL", "current snapshot from stock products", "Need confirmation only if a regional breakdown is required"),
            FieldSpec("saleRate", (("saleRate",), ("metrics", "saleRate")), "WB", "PARTIAL", "current snapshot from stock products", "Need confirmation only if a regional breakdown is required"),
            FieldSpec("toClientCount", (("toClientCount",), ("metrics", "toClientCount")), "WB", "PARTIAL", "current snapshot from stock products", "Need confirmation only if a regional breakdown is required"),
            FieldSpec("fromClientCount", (("fromClientCount",), ("metrics", "fromClientCount")), "WB", "PARTIAL", "current snapshot from stock products", "Need confirmation only if a regional breakdown is required"),
            FieldSpec("availability", (("availability",), ("metrics", "availability")), "WB", "PARTIAL", "current snapshot from stock products", "Need confirmation only if a regional breakdown is required"),
            FieldSpec("regionName", (("regionName",), ("regions", "regionName")), "WB", "PARTIAL", "regional breakdown if offices/region endpoints return rows", "Need confirmation only if regional stock is expected here"),
            FieldSpec("officeName", (("officeName",), ("offices", "officeName")), "WB", "PARTIAL", "regional breakdown if offices/region endpoints return rows", "Need confirmation only if regional stock is expected here"),
            FieldSpec("quantity", (("quantity",), ("metrics", "quantity"), ("stockCount",)), "WB", "PARTIAL", "regional breakdown if offices/region endpoints return rows", "Need confirmation only if regional stock is expected here"),
            FieldSpec("warehouse_id", (("warehouseID",), ("warehouseId",), ("officeID",)), "WB", "CSV_ONLY", "warehouse ID may only be exposed in a report/export", "Need a confirmed warehouse-level report if this is required"),
            FieldSpec("size", (("size",),), "WB", "CSV_ONLY", "size-level stock breakdown may need a dedicated report/export", "Need a confirmed size-level report if this is required"),
            FieldSpec("group", (("group",), ("groupName",)), "WB", "CSV_ONLY", "group-level stock breakdown may need a dedicated report/export", "Need a confirmed group-level report if this is required"),
        ]
        field_results = [_field_result("Остатки", "/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups", statuses[0] if statuses else "N/A", payloads, spec) for spec in field_specs]
        fields_found = [row.field for row in field_results if row.status == "FOUND"]
        fields_not_found = [row.field for row in field_results if row.status != "FOUND"]
        if any(status in {"401", "403", "402"} for status in statuses):
            block_status = "NEEDS_ACCESS"
        elif any(status == "200" for status in statuses):
            block_status = "PARTIAL"
        else:
            block_status = "NOT_FOUND"
        summary = BlockResult(
            block="Остатки",
            endpoint_tested="/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups",
            method="POST/GET",
            status=block_status,
            http_status=";".join(statuses),
            fields_found=fields_found,
            fields_not_found=fields_not_found,
            next_step="Keep the current stock snapshot for live tabs and use CSV history for historical stock rows.",
            employee_question="Can the WB side confirm a public endpoint for MP stock qty or a regional/warehouse stock feed?",
            details="current snapshot is available; regional/warehouse granularity and MP stock remain partial",
        )
        return summary, field_results, endpoint_results

    def _run_localization(self) -> tuple[BlockResult, list[FieldResult], list[EndpointResult]]:
        endpoint_results: list[EndpointResult] = []
        status, payload, error = self._request(
            "GET",
            f"{WB_ANALYTICS_BASE}/api/v1/analytics/region-sale",
            self._analytics_headers(),
            params={"dateFrom": self.test_date_from.isoformat(), "dateTo": self.test_date_to.isoformat()},
        )
        endpoint_results.append(
            EndpointResult(
                name="region-sale",
                endpoint="/api/v1/analytics/region-sale",
                method="GET",
                http_status=status,
                payload=payload,
                error_short=error,
                objects_count=first_list_length(payload, ("report",)),
                note=_payload_summary(payload),
            )
        )

        field_specs = [
            FieldSpec("countryName", (("countryName",), ("report", "countryName")), "WB", "PARTIAL", "regional sales feed", "Need confirmation only if the country dimension is required"),
            FieldSpec("foName", (("foName",), ("report", "foName")), "WB", "PARTIAL", "regional sales feed", "Need confirmation only if the federal district dimension is required"),
            FieldSpec("regionName", (("regionName",), ("report", "regionName")), "WB", "PARTIAL", "regional sales feed", "Need confirmation only if the region dimension is required"),
            FieldSpec("cityName", (("cityName",), ("report", "cityName")), "WB", "PARTIAL", "regional sales feed", "Need confirmation only if the city dimension is required"),
            FieldSpec("nmID", (("nmID",), ("report", "nmID")), "WB", "PARTIAL", "regional sales feed", "Need confirmation only if the nmID dimension is required"),
            FieldSpec("saleItemInvoiceQty", (("saleItemInvoiceQty",), ("report", "saleItemInvoiceQty")), "WB", "PARTIAL", "regional sales feed", "Need confirmation only if the regional sales metric is required"),
            FieldSpec("saleInvoiceCostPrice", (("saleInvoiceCostPrice",), ("report", "saleInvoiceCostPrice")), "WB", "PARTIAL", "regional sales feed", "Need confirmation only if the cost metric is required"),
            FieldSpec("saleInvoiceCostPricePerc", (("saleInvoiceCostPricePerc",), ("report", "saleInvoiceCostPricePerc")), "WB", "PARTIAL", "regional sales feed", "Need confirmation only if the percent metric is required"),
            FieldSpec("delivery_time", (("delivery_time",), ("avgDeliveryTime",), ("timeToReady",)), "WB", "PARTIAL", "regional sales feed does not confirm delivery time", "Need a confirmed source or accepted business rule for delivery time"),
            FieldSpec("local_orders_percent", (("local_orders_percent",),), "WB", "PARTIAL", "regional sales feed does not confirm local/nonlocal KPI", "Need a confirmed business formula for local/nonlocal orders"),
            FieldSpec("nonlocal_orders_percent", (("nonlocal_orders_percent",),), "WB", "PARTIAL", "regional sales feed does not confirm local/nonlocal KPI", "Need a confirmed business formula for local/nonlocal orders"),
            FieldSpec("wb_stock_qty", (("stockCount",), ("metrics", "stockCount")), "WB", "PARTIAL", "regional stock cannot be inferred from total WB stock", "Need a confirmed regional stock source"),
        ]
        field_results = [_field_result("Локализация", "/api/v1/analytics/region-sale", status, [payload], spec) for spec in field_specs]
        fields_found = [row.field for row in field_results if row.status == "FOUND"]
        fields_not_found = [row.field for row in field_results if row.status != "FOUND"]
        if status in {"401", "403", "402"}:
            block_status = "NEEDS_ACCESS"
        elif status == "200":
            block_status = "PARTIAL"
        else:
            block_status = "NOT_FOUND"
        summary = BlockResult(
            block="Локализация",
            endpoint_tested="/api/v1/analytics/region-sale",
            method="GET",
            status=block_status,
            http_status=status,
            fields_found=fields_found,
            fields_not_found=fields_not_found,
            next_step="Keep regional sales, but do not reuse total stock as regional stock until a proper feed is confirmed.",
            employee_question="Is there a confirmed regional stock or delivery-time source, or should those columns stay blank?",
            details=_payload_summary(payload),
        )
        return summary, field_results, endpoint_results

    def _run_finance(self) -> tuple[BlockResult, list[FieldResult], list[EndpointResult]]:
        endpoint_results: list[EndpointResult] = []
        payloads: list[Any] = []
        statuses: list[str] = []

        report_status, report_payload, report_error = self._request(
            "GET",
            f"{WB_STATISTICS_BASE}/api/v5/supplier/reportDetailByPeriod",
            self._wb_headers(),
            params={
                "dateFrom": self.test_date_from.isoformat(),
                "dateTo": self.test_date_to.isoformat(),
                "limit": 200,
                "rrdid": 0,
                "period": "daily",
            },
        )
        payloads.append(report_payload)
        statuses.append(report_status)
        endpoint_results.append(
            EndpointResult(
                name="reportDetailByPeriod",
                endpoint="/api/v5/supplier/reportDetailByPeriod",
                method="GET",
                http_status=report_status,
                payload=report_payload,
                error_short=report_error,
                objects_count=first_list_length(report_payload),
                note=_payload_summary(report_payload),
            )
        )

        orders_status, orders_payload, orders_error = self._request(
            "GET",
            f"{WB_STATISTICS_BASE}/api/v1/supplier/orders",
            self._wb_headers(),
            params={"dateFrom": self.test_date_from.isoformat(), "dateTo": self.test_date_to.isoformat(), "limit": 1000},
        )
        payloads.append(orders_payload)
        statuses.append(orders_status)
        endpoint_results.append(
            EndpointResult(
                name="supplier-orders",
                endpoint="/api/v1/supplier/orders",
                method="GET",
                http_status=orders_status,
                payload=orders_payload,
                error_short=orders_error,
                objects_count=first_list_length(orders_payload),
                note=_payload_summary(orders_payload),
            )
        )

        sales_status, sales_payload, sales_error = self._request(
            "GET",
            f"{WB_STATISTICS_BASE}/api/v1/supplier/sales",
            self._wb_headers(),
            params={"dateFrom": self.test_date_from.isoformat(), "dateTo": self.test_date_to.isoformat(), "limit": 1000},
        )
        payloads.append(sales_payload)
        statuses.append(sales_status)
        endpoint_results.append(
            EndpointResult(
                name="supplier-sales",
                endpoint="/api/v1/supplier/sales",
                method="GET",
                http_status=sales_status,
                payload=sales_payload,
                error_short=sales_error,
                objects_count=first_list_length(sales_payload),
                note=_payload_summary(sales_payload),
            )
        )

        field_specs = [
            FieldSpec("date", (("sale_dt",), ("date",), ("date_from",), ("lastChangeDate",)), "WB", "PARTIAL", "finance base from reportDetailByPeriod and orders/sales", "Need a stable line date for aggregation"),
            FieldSpec("nm_id", (("nm_id",), ("nmId",), ("report", "nmID")), "WB", "PARTIAL", "finance base from reportDetailByPeriod and orders/sales", "Need a stable nm_id for aggregation"),
            FieldSpec("supplier_article", (("sa_name",), ("supplierArticle",), ("supplierArticleName",)), "WB", "PARTIAL", "finance base from reportDetailByPeriod and orders/sales", "Need supplier article for VBro and matching with funnel/stock reference"),
            FieldSpec("organic_sales_qty", (), "FORMULA", "NEEDS_FORMULA", "could be derived only with a confirmed formula", "What is the agreed formula for organic sales quantity?"),
            FieldSpec("net_sales_payout", (("ppvz_for_pay",), ("finishedPrice",), ("retail_amount",)), "WB", "PARTIAL", "reportDetailByPeriod and sales/orders give the finance base", "Need the agreed base payout metric for VBro"),
            FieldSpec("ad_spend", (("sum",), ("updSum",)), "WB", "PARTIAL", "use promotion costs / writeoff feed", "Need to confirm whether ad spend should be linked by advertId or allocated to nm_id"),
            FieldSpec("logistics", (("delivery_rub",),), "WB", "PARTIAL", "reportDetailByPeriod gives the logistics base", "Need to confirm whether logistics should use delivery_rub only or a broader formula"),
            FieldSpec("storage", (("storage_fee",),), "WB", "PARTIAL", "reportDetailByPeriod gives the storage base", "Need to confirm whether storage should include all holding fees"),
            FieldSpec("penalties", (("penalty",),), "WB", "PARTIAL", "reportDetailByPeriod gives the penalty base", "Need to confirm whether penalties should include deductions/withholds"),
            FieldSpec("deductions", (("deduction",),), "WB", "PARTIAL", "reportDetailByPeriod gives the deduction base", "Need to confirm whether deductions should include all удержания"),
            FieldSpec("acceptance", (("acceptance",),), "WB", "PARTIAL", "reportDetailByPeriod gives the acceptance base", "Need to confirm whether acceptance should be included as a separate cost line"),
            FieldSpec("cogs", (), "EXTERNAL_SOURCE", "NEEDS_FORMULA", "COGS is not available from WB API", "What is the approved COGS source?"),
            FieldSpec("other_costs", (), "FORMULA", "NEEDS_FORMULA", "other costs are not directly exposed by WB API", "What formula should be used for other costs?"),
            FieldSpec("operating_profit", (), "FORMULA", "NEEDS_FORMULA", "requires COGS and a confirmed business formula", "What is the approved operating profit formula?"),
            FieldSpec("operating_profit_per_unit", (), "FORMULA", "NEEDS_FORMULA", "requires operating profit and a unit formula", "What is the approved unit-profit formula?"),
        ]
        field_results = [_field_result("ВБро", "/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales", report_status if report_status != "200" else orders_status, payloads, spec) for spec in field_specs]
        fields_found = [row.field for row in field_results if row.status == "FOUND"]
        fields_not_found = [row.field for row in field_results if row.status != "FOUND"]
        if any(status in {"401", "403", "402"} for status in statuses):
            block_status = "NEEDS_ACCESS"
        elif any(row.status == "NEEDS_FORMULA" for row in field_results):
            block_status = "NEEDS_FORMULA"
        elif any(status == "200" for status in statuses):
            block_status = "PARTIAL"
        else:
            block_status = "NOT_FOUND"
        summary = BlockResult(
            block="ВБро",
            endpoint_tested="/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales",
            method="GET",
            status=block_status,
            http_status=";".join(statuses),
            fields_found=fields_found,
            fields_not_found=fields_not_found,
            next_step="Use reportDetailByPeriod as the finance base, but keep operating profit blank until COGS and the business formula are confirmed.",
            employee_question="What is the approved COGS source and operating-profit formula?",
            details="finance base is present; profit still needs formula confirmation",
        )
        return summary, field_results, endpoint_results

    def _run_content(self) -> tuple[BlockResult, list[FieldResult], list[EndpointResult]]:
        endpoint_results: list[EndpointResult] = []
        status, payload, error = self._request(
            "POST",
            f"{WB_CONTENT_BASE}/content/v2/get/cards/list",
            self._wb_headers(),
            json_body={"settings": {"cursor": {"limit": 10, "offset": 0}}},
        )
        endpoint_results.append(
            EndpointResult(
                name="content-cards-list",
                endpoint="/content/v2/get/cards/list",
                method="POST",
                http_status=status,
                payload=payload,
                error_short=error,
                objects_count=first_list_length(payload, ("cards",)),
                note=_payload_summary(payload),
            )
        )
        field_specs = [
            FieldSpec("nm_id", (("cards", "nmID"), ("cards", "nmId")), "WB", "PARTIAL", "cards/list should expose nmId if the token/account has access", "Need a confirmed content access scope or a different token category"),
            FieldSpec("vendorCode", (("cards", "vendorCode"),), "WB", "PARTIAL", "cards/list should expose vendorCode if the token/account has access", "Need a confirmed content access scope or a different token category"),
            FieldSpec("title", (("cards", "title"),), "WB", "PARTIAL", "cards/list should expose title if the token/account has access", "Need a confirmed content access scope or a different token category"),
            FieldSpec("subjectName", (("cards", "subjectName"), ("cards", "subject")), "WB", "PARTIAL", "cards/list should expose subjectName if the token/account has access", "Need a confirmed content access scope or a different token category"),
            FieldSpec("brand", (("cards", "brand"), ("cards", "brandName")), "WB", "PARTIAL", "cards/list should expose brand if the token/account has access", "Need a confirmed content access scope or a different token category"),
            FieldSpec("photos", (("cards", "photos"),), "WB", "PARTIAL", "cards/list should expose photos if the token/account has access", "Need a confirmed content access scope or a different token category"),
            FieldSpec("sizes", (("cards", "sizes"),), "WB", "PARTIAL", "cards/list should expose sizes if the token/account has access", "Need a confirmed content access scope or a different token category"),
        ]
        field_results = [_field_result("WB Content API / dim_product", "/content/v2/get/cards/list", status, [payload], spec) for spec in field_specs]
        fields_found = [row.field for row in field_results if row.status == "FOUND"]
        fields_not_found = [row.field for row in field_results if row.status != "FOUND"]
        if status in {"401", "403", "402"}:
            block_status = "NEEDS_ACCESS"
        elif status == "200" and first_list_length(payload, ("cards",)) == 0:
            block_status = "PARTIAL"
        elif status == "200":
            block_status = "FOUND" if not fields_not_found else "PARTIAL"
        else:
            block_status = "NOT_FOUND"
        summary = BlockResult(
            block="WB Content API / dim_product",
            endpoint_tested="/content/v2/get/cards/list",
            method="POST",
            status=block_status,
            http_status=status,
            fields_found=fields_found,
            fields_not_found=fields_not_found,
            next_step="If cards/list remains empty, keep dim_product as a fallback from funnel/stocks and do not invent catalog data.",
            employee_question="Is the current WB token supposed to have content access, or should catalog data stay on the fallback path?",
            details=_payload_summary(payload),
        )
        return summary, field_results, endpoint_results

    def _run_csv_reports(self) -> tuple[BlockResult, list[FieldResult], list[EndpointResult]]:
        endpoint_results: list[EndpointResult] = []
        list_status, list_payload, list_error = self._request(
            "GET",
            f"{WB_ANALYTICS_BASE}/api/v2/nm-report/downloads",
            self._analytics_headers(),
        )
        download_id = _find_download_id(list_payload)
        endpoint_results.append(
            EndpointResult(
                name="nm-report-downloads",
                endpoint="/api/v2/nm-report/downloads",
                method="GET",
                http_status=list_status,
                payload=list_payload,
                error_short=list_error,
                objects_count=first_list_length(list_payload),
                note=_payload_summary(list_payload),
            )
        )

        post_status, post_payload, post_error = self._request(
            "POST",
            f"{WB_ANALYTICS_BASE}/api/v2/nm-report/downloads",
            self._analytics_headers(),
            json_body={},
        )
        endpoint_results.append(
            EndpointResult(
                name="nm-report-downloads-post",
                endpoint="/api/v2/nm-report/downloads",
                method="POST",
                http_status=post_status,
                payload=post_payload,
                error_short=post_error,
                objects_count=first_list_length(post_payload),
                note=_payload_summary(post_payload),
            )
        )

        file_status = "SKIPPED"
        file_payload: Any = None
        file_error = ""
        if download_id:
            time.sleep(0.5)
            file_status, file_payload, file_error = self._request(
                "GET",
                f"{WB_ANALYTICS_BASE}/api/v2/nm-report/downloads/file/{download_id}",
                self._analytics_headers(),
            )
            endpoint_results.append(
                EndpointResult(
                    name="nm-report-download-file",
                    endpoint=f"/api/v2/nm-report/downloads/file/{download_id}",
                    method="GET",
                    http_status=file_status,
                    payload=file_payload,
                    error_short=file_error,
                    objects_count=first_list_length(file_payload),
                    note=_payload_summary(file_payload),
                )
            )
        else:
            endpoint_results.append(
                EndpointResult(
                    name="nm-report-download-file",
                    endpoint="/api/v2/nm-report/downloads/file/{downloadId}",
                    method="GET",
                    http_status="SKIPPED",
                    payload=None,
                    error_short="download id not returned by the list endpoint",
                    objects_count=0,
                    note="skipped because list endpoint did not expose a download id",
                )
            )

        report_type_names = []
        if isinstance(list_payload, dict):
            for item in _extract_list(list_payload, ("data",)):
                if isinstance(item, dict) and item.get("name"):
                    report_type_names.append(str(item["name"]))
        entry_points_known = any("entry" in name.lower() and "point" in name.lower() for name in report_type_names)

        field_specs = [
            FieldSpec("download_list", (("id",), ("name",), ("status",)), "WB", "PARTIAL", "nm-report/downloads list endpoint", "Need a confirmed report type if entry points should be automated"),
            FieldSpec("stock_history_csv", (("stock-history",),), "WB", "CSV_ONLY", "stock history is already proven as CSV-only in the project", "Need a CSV flow if historical stock rows are required"),
            FieldSpec("entry_point_report_type", (), "WB", "CSV_ONLY" if entry_points_known else "NOT_FOUND", "entry-point report type was not confirmed in the downloads list", "Need a confirmed CSV/export/private endpoint for entry points"),
        ]
        payloads = [list_payload, post_payload, file_payload]
        field_results = [_field_result("Точка вх", "/api/v2/nm-report/downloads; /api/v2/nm-report/downloads/file/{downloadId}", list_status, payloads, spec) for spec in field_specs]
        fields_found = [row.field for row in field_results if row.status == "FOUND"]
        fields_not_found = [row.field for row in field_results if row.status != "FOUND"]
        if list_status in {"401", "403", "402"} or post_status in {"401", "403", "402"} or file_status in {"401", "403", "402"}:
            block_status = "NEEDS_ACCESS"
        elif entry_points_known:
            block_status = "CSV_ONLY"
        elif list_status == "200":
            block_status = "NOT_FOUND"
        else:
            block_status = "NOT_FOUND"
        summary = BlockResult(
            block="Точка вх",
            endpoint_tested="/api/v2/nm-report/downloads; /api/v2/nm-report/downloads/file/{downloadId}",
            method="GET/POST",
            status=block_status,
            http_status=";".join([list_status, post_status, file_status]),
            fields_found=fields_found,
            fields_not_found=fields_not_found,
            next_step="If no dedicated entry-point report is listed, keep this block as CSV_ONLY / private endpoint required.",
            employee_question="Is there a confirmed CSV/export/private endpoint for the entry-point report type?",
            details="downloads list exists, but the audit did not confirm an entry-point report type",
        )
        return summary, field_results, endpoint_results

    def _run_mpstat(self) -> tuple[BlockResult, list[FieldResult], list[EndpointResult]]:
        endpoint_results: list[EndpointResult] = []
        payloads: list[Any] = []
        statuses: list[str] = []
        item_id = TEST_NM_IDS[0]

        full_status, full_payload, full_error = self._request(
            "GET",
            f"{MPSTAT_BASE}/item/{item_id}",
            self._mpstat_headers(),
            params={"d1": self.test_date_from.isoformat(), "d2": self.test_date_to.isoformat()},
        )
        payloads.append(full_payload)
        statuses.append(full_status)
        endpoint_results.append(
            EndpointResult(
                name="mpstat-item-full",
                endpoint=f"/item/{item_id}",
                method="GET",
                http_status=full_status,
                payload=full_payload,
                error_short=full_error,
                objects_count=1 if full_payload else 0,
                note=_payload_summary(full_payload),
            )
        )

        sales_status, sales_payload, sales_error = self._request(
            "GET",
            f"{MPSTAT_BASE}/item/{item_id}/sales",
            self._mpstat_headers(),
            params={"d1": self.test_date_from.isoformat(), "d2": self.test_date_to.isoformat()},
        )
        payloads.append(sales_payload)
        statuses.append(sales_status)
        endpoint_results.append(
            EndpointResult(
                name="mpstat-item-sales",
                endpoint=f"/item/{item_id}/sales",
                method="GET",
                http_status=sales_status,
                payload=sales_payload,
                error_short=sales_error,
                objects_count=first_list_length(sales_payload),
                note=_payload_summary(sales_payload),
            )
        )

        field_specs = [
            FieldSpec("nm_id", (("nm_id",), ("nmId",), ("item", "id")), "MPSTAT", "NEEDS_ACCESS", "MPStat is blocked until auth succeeds", "Need a valid MPStat token/base-url combination"),
            FieldSpec("title", (("title",), ("name",), ("item", "name")), "MPSTAT", "NEEDS_ACCESS", "MPStat is blocked until auth succeeds", "Need a valid MPStat token/base-url combination"),
            FieldSpec("brand", (("brand",), ("item", "brand"), ("brandName",)), "MPSTAT", "NEEDS_ACCESS", "MPStat is blocked until auth succeeds", "Need a valid MPStat token/base-url combination"),
            FieldSpec("sales", (("sales",), ("item", "sales")), "MPSTAT", "NEEDS_ACCESS", "MPStat item sales is blocked until auth succeeds", "Need a valid MPStat token/base-url combination"),
            FieldSpec("balance", (("balance",), ("item", "balance")), "MPSTAT", "NEEDS_ACCESS", "MPStat item sales is blocked until auth succeeds", "Need a valid MPStat token/base-url combination"),
            FieldSpec("search_position_avg", (("search_position_avg",), ("item", "search_position_avg")), "MPSTAT", "NEEDS_ACCESS", "MPStat item sales is blocked until auth succeeds", "Need a valid MPStat token/base-url combination"),
            FieldSpec("search_visibility", (("search_visibility",), ("item", "search_visibility")), "MPSTAT", "NEEDS_ACCESS", "MPStat item sales is blocked until auth succeeds", "Need a valid MPStat token/base-url combination"),
            FieldSpec("direct_competitor_feed", (), "MPSTAT", "NEEDS_ACCESS", "competitor feed not assembled from tested endpoints", "Need a valid MPStat token/base-url combination"),
        ]
        field_results = [_field_result("MPStat / Сравнение карточек", f"/item/{item_id}; /item/{item_id}/sales", full_status, payloads, spec) for spec in field_specs]
        fields_found = [row.field for row in field_results if row.status == "FOUND"]
        fields_not_found = [row.field for row in field_results if row.status != "FOUND"]
        if any(status in {"401", "403", "402"} for status in statuses):
            block_status = "NEEDS_ACCESS"
        elif any(status == "200" for status in statuses):
            block_status = "PARTIAL"
        else:
            block_status = "NOT_FOUND"
        summary = BlockResult(
            block="MPStat / Сравнение карточек",
            endpoint_tested=f"/item/{item_id}; /item/{item_id}/sales",
            method="GET",
            status=block_status,
            http_status=";".join(statuses),
            fields_found=fields_found,
            fields_not_found=fields_not_found,
            next_step="Verify the MPStat token, subscription, and endpoint contract before trying competitor comparison again.",
            employee_question="Can you confirm the correct MPStat token/base URL and whether this plan includes item endpoints?",
            details="auth check only; direct competitor feed not assembled",
        )
        return summary, field_results, endpoint_results

    def run(self) -> tuple[list[BlockResult], list[FieldResult], dict[str, Any]]:
        block_results: list[BlockResult] = []
        field_results: list[FieldResult] = []
        endpoint_results_by_block: dict[str, list[EndpointResult]] = {}

        for block_runner in (
            self._run_content,
            self._run_funnel,
            self._run_stocks,
            self._run_ads,
            self._run_search,
            self._run_finance,
            self._run_localization,
            self._run_csv_reports,
            self._run_mpstat,
        ):
            block_result, block_field_results, endpoint_results = block_runner()
            block_results.append(block_result)
            field_results.extend(block_field_results)
            endpoint_results_by_block[block_result.block] = endpoint_results

        summary = {
            "generated_at": self.loaded_at,
            "test_date_from": self.test_date_from.isoformat(),
            "test_date_to": self.test_date_to.isoformat(),
            "test_nm_ids": TEST_NM_IDS,
            "blocks": [asdict(block) for block in block_results],
            "fields": [asdict(field) for field in field_results],
            "safety": {
                "google_sheets_written": False,
                "wb_mpstat_write_calls_executed": False,
                "mock_data_created": False,
                "raw_private_payloads_saved": False,
            },
        }
        return block_results, field_results, summary


def write_markdown_report(path: Path, blocks: list[BlockResult], field_results: list[FieldResult], summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Endpoint Gap Audit Report",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Test window: `{summary['test_date_from']}` .. `{summary['test_date_to']}`",
        f"- Test nmIDs: `{', '.join(map(str, summary['test_nm_ids']))}`",
        "- Google Sheets were read only. No rows were written.",
        "- WB / MPStat responses were summarized only. Raw private payloads were not saved.",
        "- Mock/fake rows were not created.",
        "",
        "## Block summary",
        "",
        "| Block | Endpoint tested | Method | Status | HTTP | Fields found | Fields not found | Next step | Employee question |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for block in blocks:
        lines.append(
            f"| {block.block} | {block.endpoint_tested} | {block.method} | {block.status} | {block.http_status} | "
            f"{', '.join(block.fields_found) if block.fields_found else '-'} | "
            f"{', '.join(block.fields_not_found) if block.fields_not_found else '-'} | "
            f"{block.next_step} | {block.employee_question} |"
        )

    lines.extend(["", "## Field gaps", ""])
    for row in field_results:
        lines.extend(
            [
                f"### {row.block} :: {row.field}",
                "",
                f"- Status: `{row.status}`",
                f"- Source type: `{row.source_type}`",
                f"- Endpoint: `{row.endpoint}`",
                f"- HTTP status: `{row.http_status}`",
                f"- Evidence: `{row.evidence_short}`",
                f"- Next step: {row.next_step}",
                f"- Employee question: {row.employee_question}",
                "",
            ]
        )

    lines.extend(
        [
            "## Safety confirmation",
            "",
            "- Google Sheets were not populated.",
            "- Existing Google Sheets data was not cleared.",
            "- WB / MPStat write actions were not executed.",
            "- Full pipeline was not started.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv_report(path: Path, field_results: list[FieldResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "block",
                "field",
                "status",
                "source_type",
                "endpoint",
                "http_status",
                "evidence_short",
                "next_step",
                "employee_question",
            ]
        )
        for row in field_results:
            writer.writerow(
                [
                    row.block,
                    row.field,
                    row.status,
                    row.source_type,
                    row.endpoint,
                    row.http_status,
                    row.evidence_short,
                    row.next_step,
                    row.employee_question,
                ]
            )


def write_json_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def run_endpoint_gap_audit() -> tuple[list[BlockResult], list[FieldResult], dict[str, Any]]:
    runner = EndpointGapAuditRunner()
    return runner.run()
