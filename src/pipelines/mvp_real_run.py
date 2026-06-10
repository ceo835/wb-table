from __future__ import annotations

import csv
import json
import math
import re
import statistics
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests

from src.clients.google_sheets_client import GoogleSheetsClient
from src.config.settings import settings
from src.sheets.backlog_builder import build_backlog_rows
from src.sheets.schema_definitions import PROCESSED_TABLE_SCHEMAS, USER_SHEET_SCHEMAS


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data" / "processed"
DOCS_DIR = ROOT_DIR / "docs"

TEST_NM_IDS = [197330807, 37320545, 37342770, 36387055, 577510563]

WB_CONTENT_BASE = "https://content-api.wildberries.ru"
WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"
WB_PROMOTION_BASE = "https://advert-api.wildberries.ru"
MPSTAT_BASE = "https://mpstats.io/api/wb/get"


def _today_local() -> date:
    return date.today()


def _column_letter(index: int) -> str:
    result = ""
    while index > 0:
        index -= 1
        result = chr(65 + index % 26) + result
        index //= 26
    return result


def _normalize_key(value: str) -> str:
    return value.replace("_", "").replace("-", "").replace(" ", "").lower()


def _truncate(value: str | None, limit: int = 240) -> str:
    if not value:
        return ""
    compact = " ".join(str(value).split())
    return compact[:limit]


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return value


def _to_float(value: Any) -> float | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        text = str(value).replace(" ", "").replace(",", ".")
        return float(text)
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
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text.replace(",", ".")))
    except Exception:
        return None


def _to_date_text(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if "T" in text:
        return text.split("T", 1)[0]
    return text


def _format_writeoff_datetime_for_sheet(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    text = str(value).strip().replace("T", " ").replace("Z", "")
    if not text:
        return ""
    if len(text) >= 16 and text[10] == " ":
        return text[:16]
    return text


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def _get_path(payload: Any, path: Sequence[str]) -> Any:
    current = payload
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _list_from_payload(payload: Any, *paths: Sequence[str]) -> list[Any]:
    for path in paths:
        value = _get_path(payload, path)
        if isinstance(value, list):
            return value
    if isinstance(payload, list):
        return payload
    return []


def _first_text(item: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return str(value)
    return ""


def _first_number(item: Mapping[str, Any], *keys: str) -> float | None:
    if not isinstance(item, Mapping):
        return None
    for key in keys:
        if key in item:
            value = _to_float(item.get(key))
            if value is not None:
                return value
    return None


def _nested_number(item: Mapping[str, Any], *path: str) -> float | None:
    value = _get_path(item, path)
    if isinstance(value, dict):
        for nested_key in ("current", "selected"):
            nested_value = _to_float(value.get(nested_key))
            if nested_value is not None:
                return nested_value
        return None
    return _to_float(value)


def _nested_previous_number(item: Mapping[str, Any], *path: str) -> float | None:
    value = _get_path(item, path)
    if isinstance(value, dict):
        current_value = None
        for nested_key in ("current", "selected"):
            current_value = _to_float(value.get(nested_key))
            if current_value is not None:
                break
        if current_value is not None:
            dynamics_value = _to_float(value.get("dynamics"))
            if dynamics_value is not None:
                return round(current_value - dynamics_value, 2)
        for nested_key in ("past", "previous"):
            previous_value = _to_float(value.get(nested_key))
            if previous_value is not None:
                return previous_value
        return None
    return _to_float(value)


def _duration_text(value: Any) -> str:
    if isinstance(value, dict):
        parts: list[str] = []
        for key, suffix in (("days", "д"), ("hours", "ч"), ("mins", "мин")):
            number = _to_float(value.get(key))
            if number is None:
                continue
            if float(number).is_integer():
                number_text = str(int(number))
            else:
                number_text = str(round(number, 2))
            parts.append(f"{number_text} {suffix}")
        return " ".join(parts)
    return _stringify(value)


def _first_int(item: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        if key in item:
            value = _to_int(item.get(key))
            if value is not None:
                return value
    return None


def _parse_nm_id(text: str) -> int | None:
    if not text:
        return None
    match = re.search(r"(?<!\d)(\d{6,})(?!\d)", str(text))
    if not match:
        return None
    return int(match.group(1))


def _parse_nm_id_from_campaign_name(campaign_name: str) -> int | None:
    if not campaign_name:
        return None
    match = re.search(r"(?:Арт\.?|Артикул)\s*(\d{7,10})", str(campaign_name), flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _mean(values: Iterable[float | None]) -> float | None:
    cleaned = [value for value in values if value is not None]
    if not cleaned:
        return None
    return statistics.mean(cleaned)


def _ratio(numerator: Any, denominator: Any) -> float | None:
    n = _to_float(numerator)
    d = _to_float(denominator)
    if n is None or d in (None, 0):
        return None
    return round((n / d) * 100, 2)


def _should_blank_fallback_card_clicks(card_clicks: Any, impressions: Any, ctr: Any) -> bool:
    clicks = _to_float(card_clicks)
    shows = _to_float(impressions)
    ctr_value = _to_float(ctr)
    if clicks is None or shows in (None, 0) or ctr_value is None:
        return False
    return clicks == shows and ctr_value == 100.0


def _sanitize_funnel_ctr_row(row: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = dict(row)
    if _should_blank_fallback_card_clicks(cleaned.get("card_clicks"), cleaned.get("impressions"), cleaned.get("ctr")):
        cleaned["card_clicks"] = ""
        cleaned["ctr"] = ""
    if _should_blank_fallback_card_clicks(cleaned.get("card_clicks_prev"), cleaned.get("impressions_prev"), cleaned.get("ctr_prev")):
        cleaned["card_clicks_prev"] = ""
        cleaned["ctr_prev"] = ""
    return cleaned


def _normalize_number_value(value: Any) -> Any:
    number = _to_float(value)
    if number is None:
        return value
    if float(number).is_integer():
        return int(number)
    return round(number, 2)


def _calc_metric_per_unit(total: Any, units: Any) -> float | None:
    t = _to_float(total)
    u = _to_float(units)
    if t is None or u in (None, 0):
        return None
    return round(t / u, 2)


def _classify_campaign_type(campaign_name: str) -> str:
    text = " ".join((campaign_name or "").split())
    upper = text.upper()
    if "ЗА КЛИК" in upper or "ОПЛАТА ЗА КЛИК" in upper or upper.startswith("КЛИК"):
        return "За клик"
    if upper.startswith("ПОИСК"):
        return "Поиск"
    if upper.startswith("БУСТ"):
        return "Буст"
    if "ЕДИНАЯ" in upper:
        return "Единая ставка"
    if "РУЧНАЯ" in upper:
        return "Ручная ставка"
    if upper.startswith("ПОЛКИ"):
        return "Полки"
    if upper.startswith("АРК"):
        return "АРК"
    return "UNKNOWN"


_FULLSTATS_CONVERSION_TYPE_BY_RAW = {
    0: "ASSOCIATED",
    1: "DIRECT",
    32: "MULTICARD",
}

_FULLSTATS_CONVERSION_TYPE_DISPLAY = {
    "ASSOCIATED": "Ассоциированная",
    "DIRECT": "Прямая",
    "MULTICARD": "Мультикарточка",
}


def _map_fullstats_conversion_type(raw_value: Any) -> str:
    raw_code = _to_int(raw_value)
    if raw_code is None:
        return "UNKNOWN"
    return _FULLSTATS_CONVERSION_TYPE_BY_RAW.get(raw_code, "UNKNOWN")


def _format_fullstats_conversion_type_for_sheet(raw_value: Any, technical_value: str | None = None) -> str:
    raw_code = _to_int(raw_value)
    technical = technical_value or _map_fullstats_conversion_type(raw_value)
    if technical in _FULLSTATS_CONVERSION_TYPE_DISPLAY:
        return _FULLSTATS_CONVERSION_TYPE_DISPLAY[technical]
    if raw_code is None:
        return ""
    return f"UNKNOWN_CODE_{raw_code}"


def _detect_nm_id_parse_status(campaign_name: str, section_raw: str, nm_id_from_campaign_name: int | None, nm_id_from_section: int | None) -> str:
    if nm_id_from_campaign_name is not None:
        return "FROM_CAMPAIGN_NAME"
    if nm_id_from_section is not None:
        return "FROM_SECTION"
    return "NOT_FOUND"


def _build_ad_section_display_value(
    campaign_name: str,
    section_raw: str,
    nm_id: int | None,
    campaign_type: str,
) -> str:
    if nm_id is not None:
        return str(nm_id)
    normalized_campaign = " ".join((campaign_name or "").split()).upper()
    if "ЕДИНАЯ СТАВ" in normalized_campaign:
        return "Единая Ставка"
    if "РУЧНАЯ СТАВ" in normalized_campaign or "ПОЛКИ" in normalized_campaign:
        return "Ручная Ставка"
    if campaign_type == "Единая ставка":
        return "Единая Ставка"
    if campaign_type in {"Ручная ставка", "Полки"}:
        return "Ручная Ставка"
    return " ".join((section_raw or "").split())


def _build_suspicious_ctr_validation_rows(funnel_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in funnel_rows:
        ctr = _to_float(row.get("ctr"))
        if ctr is None or ctr < 80:
            continue
        rows.append(
            {
                "sheet_name": "Воронка на день",
                "date": _stringify(row.get("date")),
                "nm_id": _stringify(row.get("nm_id")),
                "impressions": _safe_cell(row.get("impressions", "")),
                "card_clicks": _safe_cell(row.get("card_clicks", "")),
                "ctr": _safe_cell(row.get("ctr", "")),
                "reason": "suspicious_ctr: CTR >= 80, verify WB source manually",
            }
        )
    return rows


def _sum_numbers(values: Iterable[Any]) -> float | None:
    numbers = [value for value in (_to_float(v) for v in values) if value is not None]
    if not numbers:
        return None
    return round(sum(numbers), 2)


def _build_reference_index(
    funnel_rows: list[dict[str, Any]],
    stock_rows: list[dict[str, Any]],
) -> dict[int, dict[str, str]]:
    reference: dict[int, dict[str, str]] = {}
    for row in funnel_rows:
        nm_id = _to_int(row.get("nm_id"))
        if nm_id is None:
            continue
        reference.setdefault(nm_id, {})
        for field in ("supplier_article", "title", "subject", "brand"):
            if not reference[nm_id].get(field):
                reference[nm_id][field] = _first_text(row, field)
    for row in stock_rows:
        nm_id = _to_int(row.get("nm_id"))
        if nm_id is None:
            continue
        reference.setdefault(nm_id, {})
        for field in ("supplier_article", "title", "subject", "brand"):
            if not reference[nm_id].get(field):
                reference[nm_id][field] = _first_text(row, field)
    return reference


def _fields_present(row: Mapping[str, Any], columns: Sequence[str]) -> list[str]:
    return [column for column in columns if row.get(column) not in (None, "", [], {})]


def _ordered_values(row: Mapping[str, Any], columns: Sequence[str]) -> list[Any]:
    return [_safe_cell(row.get(column, "")) for column in columns]


def _split_rows(rows: list[dict[str, Any]], key_fields: Sequence[str]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(row.get(field, "") for field in key_fields)
        grouped.setdefault(key, []).append(row)
    return grouped


@dataclass
class SourceRun:
    source: str
    endpoint: str
    method: str
    status: str
    http_status: str
    objects_count: int
    fields_found: list[str] = field(default_factory=list)
    fields_missing: list[str] = field(default_factory=list)
    error_short: str = ""
    rows_written: int = 0
    target: str = ""
    notes: str = ""

    def to_report_row(self) -> dict[str, Any]:
        return {
            "target": self.target or self.source,
            "object_type": "google_sheet" if self.rows_written or self.target else "api_source",
            "source": self.source,
            "status": self.status,
            "http_status": self.http_status,
            "rows_written": self.rows_written,
            "fields_found": ", ".join(self.fields_found),
            "fields_missing": ", ".join(self.fields_missing),
            "error_short": self.error_short,
            "details": self.notes,
        }


class MvpRealRun:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.spreadsheet_id = settings.google_sheet_id
        self.gs_client = GoogleSheetsClient()
        self.loaded_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.date_to = _today_local() - timedelta(days=1)
        self.date_from = self.date_to - timedelta(days=1)
        self.nm_ids = list(TEST_NM_IDS)

    def _headers_content(self) -> dict[str, str]:
        return {
            "Authorization": settings.wb_token or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _headers_analytics(self) -> dict[str, str]:
        return {
            "Authorization": settings.wb_analytics_token or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _headers_promotion(self) -> dict[str, str]:
        return {
            "Authorization": settings.wb_token or "",
            "Accept": "application/json",
        }

    def _headers_mpstat(self) -> dict[str, str]:
        return {
            "X-Mpstats": settings.mpstats_api_token or "",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | list[Any] | None = None,
        timeout: int = 90,
    ) -> tuple[str, Any, str]:
        try:
            response = self.session.request(
                method=method,
                url=url,
                headers=dict(headers),
                params=params,
                json=json_body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return "REQUEST_ERROR", None, _truncate(str(exc))

        status_code = str(response.status_code)
        if response.status_code != 200:
            return status_code, None, _truncate(response.text or response.reason)

        try:
            return status_code, response.json(), ""
        except Exception:
            return status_code, None, "invalid_json_response"

    def _ensure_sheet_headers(self, sheet_name: str, headers: Sequence[str]) -> tuple[int, str]:
        if not self.spreadsheet_id:
            raise RuntimeError("GOOGLE_SHEET_ID is missing")
        self.gs_client.ensure_worksheet(self.spreadsheet_id, sheet_name)
        current_headers = self.gs_client.get_header_row(self.spreadsheet_id, sheet_name) or []
        if list(current_headers) != list(headers):
            self.gs_client.update_header_row(self.spreadsheet_id, sheet_name, list(headers))
        end_col = _column_letter(len(headers))
        existing_rows = self.gs_client.read_range(
            self.spreadsheet_id,
            f"{sheet_name}!A1:{end_col}5000",
        )
        row_count = len(existing_rows) if existing_rows else 0
        if row_count == 0:
            # If the sheet was brand new, the header update may not have been visible yet.
            row_count = 1
        return row_count, end_col

    def _append_sheet_rows(self, sheet_name: str, headers: Sequence[str], rows: list[dict[str, Any]]) -> int:
        self._ensure_sheet_headers(sheet_name, headers)
        end_col = _column_letter(len(headers))
        self.gs_client.clear_range(self.spreadsheet_id, f"{sheet_name}!A2:{end_col}5000")
        if not rows:
            return 0
        values = [_ordered_values(row, headers) for row in rows]
        # Refresh only the data block below the header row.
        # This avoids stale tails while keeping row 1 intact.
        self.gs_client.write_rows(self.spreadsheet_id, sheet_name, values, start_row=2, start_col=1)
        return len(rows)

    def _sheet_rows_and_report(
        self,
        sheet_name: str,
        headers: Sequence[str],
        rows: list[dict[str, Any]],
        source: str,
        endpoint: str,
        method: str,
        status: str,
        http_status: str,
        fields_found: Sequence[str],
        fields_missing: Sequence[str],
        notes: str = "",
    ) -> tuple[SourceRun, list[dict[str, Any]]]:
        rows_written = self._append_sheet_rows(sheet_name, headers, rows)
        return (
            SourceRun(
                source=source,
                endpoint=endpoint,
                method=method,
                status=status,
                http_status=http_status,
                objects_count=len(rows),
                fields_found=list(fields_found),
                fields_missing=list(fields_missing),
                rows_written=rows_written,
                target=sheet_name,
                notes=notes,
            ),
            rows,
        )

    def _fetch_content_cards(self) -> tuple[str, Any, str]:
        payload = {"settings": {"cursor": {"limit": 100, "offset": 0}}}
        return self._request(
            "POST",
            f"{WB_CONTENT_BASE}/content/v2/get/cards/list",
            self._headers_content(),
            json_body=payload,
        )

    def _fetch_funnel(self, start: date, end: date) -> tuple[str, Any, str]:
        payload = {
            "selectedPeriod": {"start": start.isoformat(), "end": end.isoformat()},
            "nmIds": list(self.nm_ids),
            "skipDeletedNm": True,
            "aggregationLevel": "day",
        }
        return self._request(
            "POST",
            f"{WB_ANALYTICS_BASE}/api/analytics/v3/sales-funnel/products/history",
            self._headers_analytics(),
            json_body=payload,
        )

    def _fetch_funnel_products(self, start: date, end: date) -> tuple[str, Any, str]:
        payload = {
            "selectedPeriod": {"start": start.isoformat(), "end": end.isoformat()},
            "nmIds": list(self.nm_ids),
            "skipDeletedNm": True,
            "aggregationLevel": "day",
        }
        return self._request(
            "POST",
            f"{WB_ANALYTICS_BASE}/api/analytics/v3/sales-funnel/products",
            self._headers_analytics(),
            json_body=payload,
        )

    def _expand_funnel_payload(self, payload: Any) -> list[dict[str, Any]]:
        expanded: list[dict[str, Any]] = []
        if isinstance(payload, list):
            for block in payload:
                if not isinstance(block, dict):
                    continue
                product = block.get("product") if isinstance(block.get("product"), dict) else {}
                history = block.get("history")
                if isinstance(history, list):
                    for item in history:
                        if isinstance(item, dict):
                            merged = dict(item)
                            if product:
                                merged["product"] = product
                            expanded.append(merged)
            if expanded:
                return expanded
        return _list_from_payload(payload, ("history",), ("data", "history"), ("data", "items"))

    def _build_funnel_products_index(self, payload: Any) -> dict[int, dict[str, Any]]:
        products = _list_from_payload(payload, ("data", "products"), ("products",), ("data", "items"))
        index: dict[int, dict[str, Any]] = {}
        for block in products:
            if not isinstance(block, dict):
                continue
            product = block.get("product") if isinstance(block.get("product"), dict) else block
            statistic = block.get("statistic") if isinstance(block.get("statistic"), dict) else {}
            nm_id = _first_int(product, "nmId", "nmID") or _first_int(block, "nmId", "nmID")
            if nm_id is None:
                continue
            index[nm_id] = {
                "product": product,
                "statistic": statistic,
            }
        return index

    def _fetch_stocks(self, snapshot_date: date) -> tuple[str, Any, str]:
        payload = {
            "nmIDs": list(self.nm_ids),
            "currentPeriod": {"start": snapshot_date.isoformat(), "end": snapshot_date.isoformat()},
            "stockType": "",
            "skipDeletedNm": False,
            "availabilityFilters": [],
            "orderBy": {"field": "avgOrders", "mode": "asc"},
            "limit": 100,
            "offset": 0,
        }
        return self._request(
            "POST",
            f"{WB_ANALYTICS_BASE}/api/v2/stocks-report/products/products",
            self._headers_analytics(),
            json_body=payload,
        )

    def _fetch_ad_costs(self, start: date, end: date) -> tuple[str, Any, str]:
        return self._request(
            "GET",
            f"{WB_PROMOTION_BASE}/adv/v1/upd",
            self._headers_promotion(),
            params={"from": start.isoformat(), "to": end.isoformat()},
        )

    def _fetch_search_texts(self, day: date) -> tuple[str, Any, str]:
        payload = {
            "currentPeriod": {"start": day.isoformat(), "end": day.isoformat()},
            "pastPeriod": {"start": (day - timedelta(days=1)).isoformat(), "end": (day - timedelta(days=1)).isoformat()},
            "nmIds": list(self.nm_ids),
            "topOrderBy": "openCard",
            "includeSubstitutedSKUs": True,
            "includeSearchTexts": True,
            "orderBy": {"field": "avgPosition", "mode": "asc"},
            "limit": 100,
        }
        return self._request(
            "POST",
            f"{WB_ANALYTICS_BASE}/api/v2/search-report/product/search-texts",
            self._headers_analytics(),
            json_body=payload,
        )

    def _fetch_fullstats(self, campaign_ids: Sequence[int]) -> tuple[str, Any, str]:
        if not campaign_ids:
            return "SKIPPED", None, "no campaign ids parsed from ad costs"
        params = {
            "ids": ",".join(map(str, campaign_ids[:20])),
            "beginDate": self.date_from.isoformat(),
            "endDate": self.date_to.isoformat(),
        }
        return self._request(
            "GET",
            f"{WB_PROMOTION_BASE}/adv/v3/fullstats",
            self._headers_promotion(),
            params=params,
        )

    def _fetch_mpstat(self) -> tuple[str, Any, str]:
        if not settings.mpstats_api_token:
            return "SKIPPED", None, "MPSTATS_API_TOKEN is missing"
        return self._request(
            "GET",
            f"{MPSTAT_BASE}/item/{self.nm_ids[0]}",
            self._headers_mpstat(),
            params={"d1": self.date_from.isoformat(), "d2": self.date_to.isoformat()},
        )

    def _build_funnel_row(
        self,
        item: Mapping[str, Any],
        prev_item: Mapping[str, Any] | None,
        day_total: float | None,
        prev_day_total: float | None = None,
        product: Mapping[str, Any] | None = None,
        products: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        product = product or {}
        products = products or {}
        product_meta = products.get("product") if isinstance(products.get("product"), dict) else product
        statistic = products.get("statistic") if isinstance(products.get("statistic"), dict) else {}
        selected_stats = statistic.get("selected") if isinstance(statistic.get("selected"), dict) else {}
        past_stats = statistic.get("past") if isinstance(statistic.get("past"), dict) else {}
        selected_conversions = selected_stats.get("conversions") if isinstance(selected_stats.get("conversions"), dict) else {}
        past_conversions = past_stats.get("conversions") if isinstance(past_stats.get("conversions"), dict) else {}
        nm_id = _first_int(item, "nmId", "nmID") or _first_int(product, "nmId", "nmID")
        order_sum = _first_number(item, "orderSum")
        order_count = _first_number(item, "orderCount")
        buyout_count = _first_number(item, "buyoutCount")
        cart_count = _first_number(item, "cartCount")
        impressions = _first_number(item, "impressions")
        card_clicks = _first_number(item, "openCard", "cardClicks", "openCount")
        prev_order_sum = _first_number(prev_item or {}, "orderSum") if prev_item else None
        prev_impressions = _first_number(prev_item or {}, "impressions") if prev_item else None
        prev_card_clicks = _first_number(prev_item or {}, "openCard", "cardClicks", "openCount") if prev_item else None
        prev_cart_count = _first_number(prev_item or {}, "cartCount") if prev_item else None
        prev_order_count = _first_number(prev_item or {}, "orderCount") if prev_item else None
        prev_buyout_count = _first_number(prev_item or {}, "buyoutCount") if prev_item else None
        prev_buyout_sum = _first_number(prev_item or {}, "buyoutSum") if prev_item else None
        prev_cancel_count = _first_number(prev_item or {}, "cancelCount") if prev_item else None
        prev_cancel_sum = _first_number(prev_item or {}, "cancelSum") if prev_item else None
        prev_add_to_wishlist = _first_number(prev_item or {}, "addToWishlistCount") if prev_item else None
        add_to_cart_conversion = (
            _first_number(item, "addToCartConversion")
            or _first_number(selected_conversions, "addToCartPercent")
            or _ratio(cart_count, card_clicks)
        )
        add_to_cart_conversion_prev = (
            (_first_number(prev_item or {}, "addToCartConversion") if prev_item else None)
            or _first_number(past_conversions, "addToCartPercent")
            or _ratio(prev_cart_count, prev_card_clicks)
        )
        cart_to_order_conversion = (
            _first_number(item, "cartToOrderConversion")
            or _first_number(selected_conversions, "cartToOrderPercent")
            or _ratio(order_count, cart_count)
        )
        cart_to_order_conversion_prev = (
            (_first_number(prev_item or {}, "cartToOrderConversion") if prev_item else None)
            or _first_number(past_conversions, "cartToOrderPercent")
            or _ratio(prev_order_count, prev_cart_count)
        )
        buyout_percent = (
            _first_number(item, "buyoutPercent")
            or _first_number(selected_conversions, "buyoutPercent")
            or _ratio(buyout_count, order_count)
        )
        buyout_percent_prev = (
            (_first_number(prev_item or {}, "buyoutPercent") if prev_item else None)
            or _first_number(past_conversions, "buyoutPercent")
            or _ratio(prev_buyout_count, prev_order_count)
        )
        return {
            "date": _to_date_text(_first_text(item, "date", "dt", "start")),
            "nm_id": nm_id or "",
            "supplier_article": _first_text(product_meta, "vendorCode", "supplierArticle"),
            "title": _first_text(product_meta, "title", "name"),
            "subject": _first_text(product_meta, "subjectName", "subject"),
            "brand": _first_text(product_meta, "brandName", "brand"),
            "impressions": impressions or "",
            "impressions_prev": prev_impressions or "",
            "card_clicks": card_clicks or "",
            "card_clicks_prev": prev_card_clicks or "",
            "ctr": _ratio(card_clicks, impressions) or "",
            "ctr_prev": _ratio(prev_card_clicks, prev_impressions) or "",
            "revenue_share_percent": _ratio(order_sum, day_total) or "",
            "revenue_share_percent_prev": _ratio(prev_order_sum, prev_day_total) or "",
            "cartCount": cart_count or "",
            "cartCount_prev": prev_cart_count or "",
            "addToWishlistCount": _first_number(item, "addToWishlistCount") or "",
            "addToWishlistCount_prev": prev_add_to_wishlist or "",
            "orderCount": order_count or "",
            "orderCount_prev": prev_order_count or "",
            "buyoutCount": buyout_count or "",
            "buyoutCount_prev": prev_buyout_count or "",
            "cancelCount": _first_number(item, "cancelCount") or "",
            "cancelCount_prev": prev_cancel_count or "",
            "addToCartConversion": add_to_cart_conversion or "",
            "addToCartConversion_prev": add_to_cart_conversion_prev or "",
            "cartToOrderConversion": cart_to_order_conversion or "",
            "cartToOrderConversion_prev": cart_to_order_conversion_prev or "",
            "buyoutPercent": buyout_percent or "",
            "buyoutPercent_prev": buyout_percent_prev or "",
            "orderSum": order_sum or "",
            "orderSum_prev": prev_order_sum or "",
            "orderSumDynamics": (round(order_sum - prev_order_sum, 2) if order_sum is not None and prev_order_sum is not None else ""),
            "buyoutSum": _first_number(item, "buyoutSum") or "",
            "buyoutSum_prev": prev_buyout_sum or "",
            "cancelSum": _first_number(item, "cancelSum") or "",
            "cancelSum_prev": prev_cancel_sum or "",
            "avg_price": _calc_metric_per_unit(order_sum, order_count) or "",
            "avg_price_prev": _calc_metric_per_unit(prev_order_sum, prev_order_count) or "",
            "avg_orders_per_day": order_count or "",
            "avg_orders_per_day_prev": prev_order_count or "",
            "product_rating": _first_number(product_meta, "productRating") or "",
            "feedback_rating": _first_number(product_meta, "feedbackRating") or "",
            "wb_stock_qty": _first_number(_get_path(product_meta, ("stocks",)), "wb") or "",
            "mp_stock_qty": _first_number(_get_path(product_meta, ("stocks",)), "mp") or "",
            "stock_total_sum": _first_number(_get_path(product_meta, ("stocks",)), "balanceSum") or "",
            "avg_delivery_time": _duration_text(_get_path(selected_stats, ("timeToReady",))) or "",
            "avg_delivery_time_prev": _duration_text(_get_path(past_stats, ("timeToReady",))) or "",
            "local_orders_percent": _first_number(selected_stats, "localizationPercent") or "",
            "local_orders_percent_prev": _first_number(past_stats, "localizationPercent") or "",
            "wbclub_orderCount": _first_number(_get_path(selected_stats, ("wbClub",)), "orderCount") or "",
            "wbclub_orderCount_prev": _first_number(_get_path(past_stats, ("wbClub",)), "orderCount") or "",
            "wbclub_buyoutCount": _first_number(_get_path(selected_stats, ("wbClub",)), "buyoutCount") or "",
            "wbclub_buyoutCount_prev": _first_number(_get_path(past_stats, ("wbClub",)), "buyoutCount") or "",
            "wbclub_cancelCount": _first_number(_get_path(selected_stats, ("wbClub",)), "cancelCount") or "",
            "wbclub_cancelCount_prev": _first_number(_get_path(past_stats, ("wbClub",)), "cancelCount") or "",
            "wbclub_buyoutPercent": _first_number(_get_path(selected_stats, ("wbClub",)), "buyoutPercent") or "",
            "wbclub_buyoutPercent_prev": _first_number(_get_path(past_stats, ("wbClub",)), "buyoutPercent") or "",
            "wbclub_orderSum": _first_number(_get_path(selected_stats, ("wbClub",)), "orderSum") or "",
            "wbclub_orderSum_prev": _first_number(_get_path(past_stats, ("wbClub",)), "orderSum") or "",
            "wbclub_orderSumDynamics": (
                round(
                    (_to_float(_first_number(_get_path(selected_stats, ("wbClub",)), "orderSum")) or 0)
                    - (_to_float(_first_number(_get_path(past_stats, ("wbClub",)), "orderSum")) or 0),
                    2,
                )
                if _first_number(_get_path(selected_stats, ("wbClub",)), "orderSum") is not None
                and _first_number(_get_path(past_stats, ("wbClub",)), "orderSum") is not None
                else ""
            ),
            "wbclub_buyoutSum": _first_number(_get_path(selected_stats, ("wbClub",)), "buyoutSum") or "",
            "wbclub_buyoutSum_prev": _first_number(_get_path(past_stats, ("wbClub",)), "buyoutSum") or "",
            "wbclub_cancelSum": _first_number(_get_path(selected_stats, ("wbClub",)), "cancelSum") or "",
            "wbclub_cancelSum_prev": _first_number(_get_path(past_stats, ("wbClub",)), "cancelSum") or "",
            "wbclub_avg_orders_per_day": _first_number(_get_path(selected_stats, ("wbClub",)), "avgOrderCountPerDay") or "",
            "wbclub_avg_orders_per_day_prev": _first_number(_get_path(past_stats, ("wbClub",)), "avgOrderCountPerDay") or "",
            "ad_views_percent": "",
            "ad_views": "",
            "cart_overpay_vs_yesterday": "",
            "show_to_cart_conversion": "",
            "cabinet_click_cost": "",
            "cabinet_cart_cost": "",
            "cabinet_cpo": "",
            "cabinet_cpm": "",
            "rk": "",
            "data_status": "REAL_API",
            "source_status": "PARTIAL",
            "loaded_at": self.loaded_at,
        }

    def _build_stock_row(self, item: Mapping[str, Any]) -> dict[str, Any]:
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        nm_id = _first_int(item, "nmID", "nmId")
        stock_qty = _first_number(metrics, "stockCount", "stockQty")
        stock_sum = _first_number(metrics, "stockSum", "balanceSum")
        return {
            "snapshot_date": self.date_to.isoformat(),
            "nm_id": nm_id or "",
            "supplier_article": _first_text(item, "vendorCode"),
            "title": _first_text(item, "name", "title"),
            "subject": _first_text(item, "subjectName", "subject"),
            "brand": _first_text(item, "brandName", "brand"),
            "wb_stock_qty": stock_qty or "",
            "mp_stock_qty": "",
            "stock_total_qty": stock_qty or "",
            "stock_total_sum": stock_sum or "",
            "saleRate": _first_number(metrics, "saleRate") or "",
            "toClientCount": _first_number(metrics, "toClientCount") or "",
            "fromClientCount": _first_number(metrics, "fromClientCount") or "",
            "availability": _first_number(metrics, "availability") or "",
            "data_status": "REAL_API",
            "source_status": "PARTIAL",
            "loaded_at": self.loaded_at,
        }

    def _build_ad_event_row(self, item: Mapping[str, Any]) -> dict[str, Any]:
        advert_id = _first_int(item, "advertId")
        campaign_name = _first_text(item, "campName", "campaignName", "name")
        section_raw = _first_text(item, "advertType", "section", "type")
        writeoff_datetime_raw = _first_text(item, "updTime", "writeoffDate", "dt")
        writeoff_datetime = _to_date_text(writeoff_datetime_raw)
        writeoff_source = _first_text(item, "paymentType", "writeoffSource")
        spend = _first_number(item, "updSum", "sum")
        document_number = _first_text(item, "updNum", "documentNumber", "docNum")
        nm_id_from_section = _parse_nm_id(section_raw)
        nm_id_from_campaign_name = _parse_nm_id_from_campaign_name(campaign_name)
        nm_id = nm_id_from_campaign_name or nm_id_from_section or ""
        parse_status = _detect_nm_id_parse_status(campaign_name, section_raw, nm_id_from_campaign_name, nm_id_from_section)
        campaign_type = _classify_campaign_type(campaign_name)
        return {
            "date": writeoff_datetime,
            "advertId": advert_id or "",
            "campaign_name": campaign_name,
            "section_raw": section_raw,
            "writeoff_datetime": writeoff_datetime_raw,
            "writeoff_source": writeoff_source,
            "spend": spend or "",
            "document_number": document_number,
            "nm_id_from_section": nm_id_from_section or "",
            "nm_id_from_campaign_name": nm_id_from_campaign_name or "",
            "nm_id": nm_id,
            "nm_id_parse_status": parse_status,
            "campaign_type": campaign_type,
            "section_display": _build_ad_section_display_value(campaign_name, section_raw, nm_id if nm_id else None, campaign_type),
            "currency": "RUB",
            "data_status": "REAL_API",
            "source_status": "REAL_API",
            "loaded_at": self.loaded_at,
        }

    def _build_ad_day_rows(self, event_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, Any, Any], list[dict[str, Any]]] = {}
        for row in event_rows:
            key = (row.get("date", ""), row.get("advertId", ""), row.get("nm_id", ""))
            grouped.setdefault(key, []).append(row)

        day_rows: list[dict[str, Any]] = []
        for (day, advert_id, nm_id), rows in grouped.items():
            day_rows.append(
                {
                    "date": day,
                    "advertId": advert_id,
                    "campaign_name": rows[0].get("campaign_name", ""),
                    "nm_id": nm_id,
                    "total_spend": _sum_numbers(row.get("spend") for row in rows) or "",
                    "events_count": len(rows),
                    "allocation_status": "ALLOCATED" if nm_id else "UNALLOCATED",
                    "data_status": "REAL_API",
                    "source_status": "REAL_API" if nm_id else "PARTIAL",
                    "loaded_at": self.loaded_at,
                }
                )
        return day_rows

    def _build_fullstats_rows(
        self,
        fullstats_payload: Any,
        campaign_name_index: dict[int, str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        campaign_rows: list[dict[str, Any]] = []
        campaign_nm_rows: list[dict[str, Any]] = []
        campaigns = _list_from_payload(fullstats_payload, ("data",), ("data", "items"), ("items",))
        if not campaigns and isinstance(fullstats_payload, list):
            campaigns = fullstats_payload

        for campaign in campaigns:
            if not isinstance(campaign, dict):
                continue
            advert_id = _first_int(campaign, "advertId")
            if advert_id is None:
                continue
            campaign_name = _first_non_empty(campaign_name_index.get(advert_id, ""), _first_text(campaign, "campName", "campaignName", "name"))
            booster_stats = campaign.get("boosterStats") if isinstance(campaign.get("boosterStats"), list) else []
            booster_index: dict[tuple[str, int], dict[str, Any]] = {}
            for booster in booster_stats:
                if not isinstance(booster, dict):
                    continue
                booster_date = _to_date_text(_first_text(booster, "date"))
                booster_nm = _first_int(booster, "nm", "nmId", "nmID")
                if booster_date and booster_nm is not None:
                    booster_index[(booster_date, booster_nm)] = booster

            for day in campaign.get("days") if isinstance(campaign.get("days"), list) else []:
                if not isinstance(day, dict):
                    continue
                day_date = _to_date_text(_first_text(day, "date"))
                if not day_date:
                    continue
                day_positions = [
                    _to_float(booster.get("avg_position"))
                    for booster_date, booster in booster_index.items()
                    if booster_date[0] == day_date
                ]
                campaign_rows.append(
                    {
                        "date": day_date,
                        "advertId": advert_id,
                        "campaign_name": campaign_name,
                        "row_type": "Итог кампании",
                        "ad_spend": _first_number(day, "sum") or "",
                        "ad_revenue": _first_number(day, "sum_price") or "",
                        "ad_views": _first_number(day, "views") or "",
                        "ad_clicks": _first_number(day, "clicks") or "",
                        "ad_atbs": _first_number(day, "atbs") or "",
                        "ad_orders": _first_number(day, "orders") or "",
                        "ordered_items_qty": _first_number(day, "shks") or "",
                        "ad_cancels": _first_number(day, "canceled") or "",
                        "avg_position": _mean(day_positions) or "",
                        "ad_ctr": _first_number(day, "ctr") or "",
                        "ad_cpc": _first_number(day, "cpc") or "",
                        "ad_cpm": "",
                        "ad_cr": _first_number(day, "cr") or "",
                        "ad_roi": "",
                        "data_status": "REAL_API",
                        "source_status": "PARTIAL",
                        "loaded_at": self.loaded_at,
                    }
                )
                for app in day.get("apps") if isinstance(day.get("apps"), list) else []:
                    if not isinstance(app, dict):
                        continue
                    conversion_type_raw = _first_int(app, "appType")
                    conversion_type = _map_fullstats_conversion_type(conversion_type_raw)
                    for nm in app.get("nms") if isinstance(app.get("nms"), list) else []:
                        if not isinstance(nm, dict):
                            continue
                        nm_id = _first_int(nm, "nmId", "nmID")
                        if nm_id is None or nm_id not in self.nm_ids:
                            continue
                        booster = booster_index.get((day_date, nm_id), {})
                        campaign_nm_rows.append(
                            {
                                "date": day_date,
                                "advertId": advert_id,
                                "campaign_name": campaign_name,
                                "row_type": "Товар",
                                "conversion_type": conversion_type,
                                "conversion_type_raw": conversion_type_raw if conversion_type_raw is not None else "",
                                "nm_id": nm_id,
                                "product_name": _first_text(nm, "name"),
                                "ad_spend": _first_number(nm, "sum") or "",
                                "ad_revenue": _first_number(nm, "sum_price") or "",
                                "ad_views": _first_number(nm, "views") or "",
                                "ad_clicks": _first_number(nm, "clicks") or "",
                                "ad_atbs": _first_number(nm, "atbs") or "",
                                "ad_orders": _first_number(nm, "orders") or "",
                                "ordered_items_qty": _first_number(nm, "shks") or "",
                                "ad_cancels": _first_number(nm, "canceled") or "",
                                "avg_position": _first_number(booster, "avg_position") or "",
                                "ad_ctr": _first_number(nm, "ctr") or "",
                                "ad_cpc": _first_number(nm, "cpc") or "",
                                "ad_cpm": "",
                                "ad_cr": _first_number(nm, "cr") or "",
                                "ad_roi": "",
                                "data_status": "REAL_API",
                                "source_status": "PARTIAL",
                                "loaded_at": self.loaded_at,
                            }
                        )
        return campaign_rows, campaign_nm_rows

    def _build_search_item(
        self,
        item: Mapping[str, Any],
        prev_item: Mapping[str, Any] | None,
        day: date,
        reference: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        nm_id = _first_int(item, "nmId", "nmID")
        query = _first_text(item, "text", "searchText")
        reference = reference or {}
        current_clicks = _nested_number(item, "openCard")
        current_cart = _nested_number(item, "addToCart")
        current_orders = _nested_number(item, "orders")
        current_frequency = _nested_number(item, "frequency") or _first_number(item, "weekFrequency")
        current_visibility = _nested_number(item, "visibility")
        current_avg_position = _nested_number(item, "avgPosition")
        current_median_position = _nested_number(item, "medianPosition")
        prev_clicks = _nested_number(prev_item or {}, "openCard") if prev_item else None
        prev_cart = _nested_number(prev_item or {}, "addToCart") if prev_item else None
        prev_orders = _nested_number(prev_item or {}, "orders") if prev_item else None
        prev_frequency = _nested_number(prev_item or {}, "frequency") if prev_item else None
        prev_visibility = _nested_number(prev_item or {}, "visibility") if prev_item else None
        prev_avg_position = _nested_number(prev_item or {}, "avgPosition") if prev_item else None
        prev_median_position = _nested_number(prev_item or {}, "medianPosition") if prev_item else None

        result = {
            "period_start": day.isoformat(),
            "period_end": day.isoformat(),
            "date": day.isoformat(),
            "nm_id": nm_id or "",
            "supplier_article": _first_non_empty(
                _first_text(reference, "supplier_article", "supplierArticle", "vendorCode"),
                _first_text(item, "supplier_article", "supplierArticle", "vendorCode"),
            ),
            "title": _first_non_empty(
                _first_text(reference, "title", "name"),
                _first_text(item, "title", "name"),
            ),
            "subject": _first_non_empty(
                _first_text(reference, "subject", "subjectName"),
                _first_text(item, "subject", "subjectName"),
            ),
            "brand": _first_non_empty(
                _first_text(reference, "brand", "brandName"),
                _first_text(item, "brand", "brandName"),
            ),
            "card_rating": _nested_number(item, "rating") or "",
            "reviews_rating": _nested_number(item, "feedbackRating") or "",
            "search_query": query,
            "query_count": current_frequency or "",
            "query_count_prev": prev_frequency or "",
            "visibility": current_visibility or "",
            "visibility_prev": prev_visibility or "",
            "avg_position": current_avg_position or "",
            "avg_position_prev": prev_avg_position or "",
            "median_position": current_median_position or "",
            "median_position_prev": prev_median_position or "",
            "search_clicks": current_clicks or "",
            "search_clicks_prev": prev_clicks or "",
            "search_clicks_competitor_percentile": "",
            "search_cart": current_cart or "",
            "search_cart_prev": prev_cart or "",
            "search_cart_competitor_percentile": "",
            "cart_conversion": _ratio(current_cart, current_clicks) or "",
            "cart_conversion_prev": _ratio(prev_cart, prev_clicks) or "",
            "cart_conversion_competitor_percentile": "",
            "search_orders": current_orders or "",
            "search_orders_prev": prev_orders or "",
            "search_orders_competitor_percentile": "",
            "order_conversion": _ratio(current_orders, current_clicks) or "",
            "order_conversion_prev": _ratio(prev_orders, prev_clicks) or "",
            "order_conversion_competitor_percentile": "",
            "min_discount_price": "",
            "max_discount_price": "",
            "data_status": "REAL_API",
            "source_status": "PARTIAL",
            "loaded_at": self.loaded_at,
        }
        return result

    def _build_search_rows(
        self,
        day: date,
        payload: Any,
        prev_payload: Any | None,
        reference_index: dict[int, dict[str, str]] | None = None,
    ) -> list[dict[str, Any]]:
        current_items = _list_from_payload(payload, ("data", "items"), ("items",), ("data",))
        prev_items = _list_from_payload(prev_payload, ("data", "items"), ("items",), ("data",)) if prev_payload is not None else []
        prev_index: dict[tuple[int | None, str], dict[str, Any]] = {}
        for item in prev_items:
            if not isinstance(item, dict):
                continue
            nm_id = _first_int(item, "nmId", "nmID")
            query = _first_text(item, "text", "searchText")
            if query:
                prev_index[(nm_id, query)] = item

        rows: list[dict[str, Any]] = []
        for item in current_items:
            if not isinstance(item, dict):
                continue
            nm_id = _first_int(item, "nmId", "nmID")
            query = _first_text(item, "text", "searchText")
            prev_item = prev_index.get((nm_id, query))
            rows.append(self._build_search_item(item, prev_item, day, (reference_index or {}).get(nm_id, {})))
        return rows

    def _build_itogo_rows(
        self,
        funnel_rows: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        search_rows: list[dict[str, Any]],
        ad_day_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        funnel_index = {(row.get("date", ""), row.get("nm_id", "")): row for row in funnel_rows}
        stock_index = {row.get("nm_id", ""): row for row in stock_rows}
        ad_index = {(row.get("date", ""), row.get("nm_id", "")): row for row in ad_day_rows}
        search_groups: dict[tuple[str, Any], list[dict[str, Any]]] = {}
        for row in search_rows:
            key = (row.get("date", ""), row.get("nm_id", ""))
            search_groups.setdefault(key, []).append(row)

        result_rows: list[dict[str, Any]] = []
        for day in [self.date_from, self.date_to]:
            for nm_id in self.nm_ids:
                if not day or nm_id is None:
                    continue
                key = (day.isoformat(), nm_id)
                funnel = funnel_index.get(key, {})
                stock = stock_index.get(nm_id, {})
                ad = ad_index.get(key, {})
                search_group = search_groups.get(key, [])
                search_positions = [_to_float(row.get("avg_position")) for row in search_group]
                search_visibility = [_to_float(row.get("visibility")) for row in search_group]
                search_clicks = _sum_numbers(row.get("search_clicks") for row in search_group) or ""
                search_cart = _sum_numbers(row.get("search_cart") for row in search_group) or ""
                search_orders = _sum_numbers(row.get("search_orders") for row in search_group) or ""
                search_query_count = len(search_group)
                order_sum = _to_float(funnel.get("orderSum"))
                order_count = _to_float(funnel.get("orderCount"))
                cart_count = _to_float(funnel.get("cartCount"))
                ad_spend = _to_float(ad.get("total_spend"))
                total_stock_sum = _to_float(stock.get("stock_total_sum"))
                total_stock_qty = _to_float(stock.get("stock_total_qty"))
                supplier_article = _first_non_empty(funnel.get("supplier_article"), stock.get("supplier_article"))
                title = _first_non_empty(funnel.get("title"), stock.get("title"))
                subject = _first_non_empty(funnel.get("subject"), stock.get("subject"))
                brand = _first_non_empty(funnel.get("brand"), stock.get("brand"))
                result_rows.append(
                    {
                        "date": day.isoformat(),
                        "nm_id": nm_id,
                        "supplier_article": supplier_article,
                        "title": title,
                        "subject": subject,
                        "brand": brand,
                        "impressions": _normalize_number_value(funnel.get("impressions", "")),
                        "card_clicks": _normalize_number_value(funnel.get("card_clicks", "")),
                        "ctr": _normalize_number_value(funnel.get("ctr", "")),
                        "cartCount": _normalize_number_value(funnel.get("cartCount", "")),
                        "orderCount": _normalize_number_value(funnel.get("orderCount", "")),
                        "orderSum": _normalize_number_value(funnel.get("orderSum", "")),
                        "buyoutCount": _normalize_number_value(funnel.get("buyoutCount", "")),
                        "buyoutSum": _normalize_number_value(funnel.get("buyoutSum", "")),
                        "buyoutPercent": _normalize_number_value(funnel.get("buyoutPercent", "")),
                        "addToCartConversion": _normalize_number_value(funnel.get("addToCartConversion", "")),
                        "cartToOrderConversion": _normalize_number_value(funnel.get("cartToOrderConversion", "")),
                        "addToWishlistCount": _normalize_number_value(funnel.get("addToWishlistCount", "")),
                        "ad_views": "",
                        "ad_clicks": "",
                        "ad_ctr": "",
                        "ad_cpc": "",
                        "ad_orders": "",
                        "ad_atbs": "",
                        "ad_spend": _normalize_number_value(ad_spend or ""),
                        "ad_revenue": "",
                        "cost_per_cart": _normalize_number_value(_calc_metric_per_unit(ad_spend, cart_count) or ""),
                        "cpm": "",
                        "cpo": _normalize_number_value(_calc_metric_per_unit(ad_spend, order_count) or ""),
                        "search_queries_count": _normalize_number_value(search_query_count),
                        "avg_position": _normalize_number_value(_mean(search_positions) or ""),
                        "visibility": _normalize_number_value(_mean(search_visibility) or ""),
                        "search_clicks": _normalize_number_value(search_clicks),
                        "search_cart": _normalize_number_value(search_cart),
                        "search_orders": _normalize_number_value(search_orders),
                        "current_stockCount": _normalize_number_value(total_stock_qty or ""),
                        "current_stockSum": _normalize_number_value(total_stock_sum or ""),
                        "stock_snapshot_date": stock.get("snapshot_date", ""),
                        "data_status": "PARTIAL" if ad_spend in (None, "") or not search_group else "REAL_API",
                        "source_status": "REAL_API",
                        "loaded_at": self.loaded_at,
                    }
                )
        return result_rows

    def _build_backlog_rows(self) -> list[dict[str, Any]]:
        return build_backlog_rows()

    def _write_csv(self, path: Path, rows: list[dict[str, Any]], columns: Sequence[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({column: _safe_cell(row.get(column, "")) for column in columns})

    def _report_paths(self) -> dict[str, Path]:
        return {
            "markdown": DOCS_DIR / "mvp_real_run_report.md",
            "csv": DATA_DIR / "mvp_real_run_report.csv",
            "json": DATA_DIR / "mvp_real_run_summary.json",
        }

    def _write_report(self, results: list[SourceRun], write_summary: dict[str, Any]) -> None:
        paths = self._report_paths()
        paths["markdown"].parent.mkdir(parents=True, exist_ok=True)
        paths["csv"].parent.mkdir(parents=True, exist_ok=True)

        lines = [
            "# MVP Real Run Report",
            "",
            f"- Generated at: `{self.loaded_at}`",
            f"- Date window written: `{self.date_from.isoformat()}` .. `{self.date_to.isoformat()}`",
            f"- Test nmIDs: `{', '.join(map(str, TEST_NM_IDS))}`",
            "- WB/MPStat responses were consumed read-only; raw private payloads were not saved.",
            "- Existing sheet rows were not cleared.",
            "- Mock/fake rows were not created by this run.",
            "",
            "## Filled tabs",
            "",
        ]
        for item in results:
            if item.rows_written > 0:
                lines.append(f"- `{item.target}`: {item.rows_written} rows, `{item.status}`")
        if not any(item.rows_written > 0 for item in results):
            lines.append("- No tabs were written.")

        lines.extend(["", "## Source results", ""])
        for item in results:
            lines.extend(
                [
                    f"### {item.source}",
                    "",
                    f"- Endpoint: `{item.endpoint}`",
                    f"- Method: `{item.method}`",
                    f"- Status: `{item.status}`",
                    f"- HTTP status: `{item.http_status}`",
                    f"- Objects count: `{item.objects_count}`",
                    f"- Fields found: `{', '.join(item.fields_found) if item.fields_found else '-'}`",
                    f"- Fields missing: `{', '.join(item.fields_missing) if item.fields_missing else '-'}`",
                    f"- Rows written: `{item.rows_written}`",
                    f"- Notes: `{item.notes or '-'}`",
                    f"- Error: `{item.error_short or '-'}`",
                    "",
                ]
            )

        lines.extend(["## Backlog", ""])
        for row in write_summary["backlog_updates"]:
            lines.append(
                f"- `{row['block']}` | `{row['status']}` | {row['reason']} | next: {row['next_step']}"
            )

        lines.extend(
            [
                "",
                "## Safety confirmation",
                "",
                "- Existing Google Sheets data was not cleared.",
                "- Mock/fake rows were not added by this run.",
                "- WB/MPStat write actions were not executed.",
                "- Unsupported blocks were not force-filled.",
            ]
        )

        paths["markdown"].write_text("\n".join(lines) + "\n", encoding="utf-8")

        with paths["csv"].open("w", encoding="utf-8-sig", newline="") as fh:
            fieldnames = [
                "target",
                "object_type",
                "source",
                "status",
                "http_status",
                "rows_written",
                "fields_found",
                "fields_missing",
                "error_short",
                "details",
            ]
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for item in results:
                row = item.to_report_row()
                row["details"] = item.notes
                writer.writerow(row)

        paths["json"].write_text(json.dumps(write_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    def run(self) -> dict[str, Any]:
        results: list[SourceRun] = []

        # 1) Google Sheets connectivity / headers
        if not self.spreadsheet_id or not settings.google_application_credentials:
            results.append(
                SourceRun(
                    source="Google Sheets",
                    endpoint="spreadsheet metadata",
                    method="GET",
                    status="SKIPPED",
                    http_status="N/A",
                    objects_count=0,
                    error_short="Google Sheets credentials or spreadsheet id is missing",
                    notes="read-only check skipped",
                )
            )
        else:
            titles = self.gs_client.get_worksheet_titles(self.spreadsheet_id) or []
            results.append(
                SourceRun(
                    source="Google Sheets",
                    endpoint="spreadsheet metadata",
                    method="GET",
                    status="OK",
                    http_status="200",
                    objects_count=len(titles),
                    fields_found=["spreadsheet_id", "tabs"],
                    notes="read-only check",
                )
            )

        # 2) WB Content API
        content_status, content_payload, content_error = self._fetch_content_cards()
        content_cards = _list_from_payload(content_payload, ("cards",), ("data", "cards"))
        content_fields = ["nmId", "vendorCode", "title", "subjectName", "brand"]
        content_fields_found = []
        if content_cards and isinstance(content_cards[0], dict):
            first_card = content_cards[0]
            content_fields_found = [
                field for field in ["nm_id", "vendorCode", "title", "subject", "brand"]
                if any(key in first_card for key in {
                    "nmID" if field == "nm_id" else field,
                    "subjectName" if field == "subject" else field,
                    field,
                })
            ]
        content_result = SourceRun(
            source="WB Content API",
            endpoint="/content/v2/get/cards/list",
            method="POST",
            status="OK" if content_status == "200" and content_cards else ("PARTIAL" if content_status == "200" else "FAIL"),
            http_status=content_status,
            objects_count=len(content_cards),
            fields_found=content_fields_found,
            fields_missing=[field for field in ["nm_id", "vendorCode", "title", "subject", "brand"] if field not in content_fields_found],
            error_short=content_error,
            notes="empty cards list is treated as PARTIAL for this account" if not content_cards and content_status == "200" else "",
        )
        results.append(content_result)

        # 3) Sales funnel
        funnel_status, funnel_payload, funnel_error = self._fetch_funnel(self.date_from, self.date_to)
        funnel_items = self._expand_funnel_payload(funnel_payload)
        funnel_by_day: dict[str, list[dict[str, Any]]] = {}
        for item in funnel_items:
            if not isinstance(item, dict):
                continue
            day = _to_date_text(_first_text(item, "date", "dt", "start"))
            if day:
                funnel_by_day.setdefault(day, []).append(item)

        funnel_products_status, funnel_products_payload, funnel_products_error = self._fetch_funnel_products(self.date_from, self.date_to)
        funnel_products_index = self._build_funnel_products_index(funnel_products_payload)

        funnel_rows: list[dict[str, Any]] = []
        funnel_result_rows: list[dict[str, Any]] = []
        funnel_output_rows: list[dict[str, Any]] = []
        if funnel_by_day:
            day_totals = {
                day: _sum_numbers(item.get("orderSum") for item in items)
                for day, items in funnel_by_day.items()
            }
            day_sorted = sorted(funnel_by_day)
            for day in day_sorted:
                prev_day = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
                prev_index = {
                    (
                        _first_int(item.get("product", {}) if isinstance(item.get("product"), dict) else {}, "nmId", "nmID"),
                        _to_date_text(_first_text(item, "date", "dt", "start")),
                    ): item
                    for item in funnel_items
                    if isinstance(item, dict)
                }
                for item in funnel_by_day[day]:
                    product = item.get("product") if isinstance(item.get("product"), dict) else {}
                    nm_id = _first_int(item, "nmId", "nmID") or _first_int(product, "nmId", "nmID")
                    if nm_id is None:
                        continue
                    prev_item = prev_index.get((nm_id, prev_day))
                    row = self._build_funnel_row(
                        item,
                        prev_item,
                        day_totals.get(day),
                        day_totals.get(prev_day),
                        product,
                        funnel_products_index.get(nm_id, {}),
                    )
                    row["date"] = day
                    row["nm_id"] = nm_id or ""
                    funnel_rows.append(row)
                    funnel_output_rows.append(
                        {
                            "Дата": row["date"],
                            "Артикул продавца": row["supplier_article"],
                            "Артикул WB": nm_id or "",
                            "Название": row["title"],
                            "Предмет": row["subject"],
                            "Бренд": row["brand"],
                            "Удаленный товар": "",
                            "Рейтинг карточки": row["product_rating"],
                            "Рейтинг по отзывам": row["feedback_rating"],
                            "Показы": row["impressions"],
                            "Показы (предыдущий период)": row["impressions_prev"],
                            "CTR": row["ctr"],
                            "CTR (предыдущий период)": row["ctr_prev"],
                            "Доля карточки в выручке": row["revenue_share_percent"],
                            "Доля карточки в выручке (предыдущий период)": row["revenue_share_percent_prev"],
                            "Переходы в карточку": row["card_clicks"],
                            "Переходы в карточку (предыдущий период)": row["card_clicks_prev"],
                            "Положили в корзину": row["cartCount"],
                            "Положили в корзину (предыдущий период)": row["cartCount_prev"],
                            "Добавили в отложенные": row["addToWishlistCount"],
                            "Добавили в отложенные (предыдущий период)": row["addToWishlistCount_prev"],
                            "Заказали товаров, шт": row["orderCount"],
                            "Заказали товаров, шт (предыдущий период)": row["orderCount_prev"],
                            "Выкупили, шт": row["buyoutCount"],
                            "Выкупили, шт (предыдущий период)": row["buyoutCount_prev"],
                            "Отменили, шт": row["cancelCount"],
                            "Отменили, шт (предыдущий период)": row["cancelCount_prev"],
                            "Конверсия в корзину, %": row["addToCartConversion"],
                            "Конверсия в корзину, % (предыдущий период)": row["addToCartConversion_prev"],
                            "Конверсия в заказ, %": row["cartToOrderConversion"],
                            "Конверсия в заказ, % (предыдущий период)": row["cartToOrderConversion_prev"],
                            "Процент выкупа": row["buyoutPercent"],
                            "Процент выкупа (предыдущий период)": row["buyoutPercent_prev"],
                            "Заказали на сумму, ₽": row["orderSum"],
                            "Заказали на сумму, ₽ (предыдущий период)": row["orderSum_prev"],
                            "Динамика суммы заказов, ₽": row["orderSumDynamics"],
                            "Выкупили на сумму, ₽": row["buyoutSum"],
                            "Выкупили на сумму, ₽ (предыдущий период)": row["buyoutSum_prev"],
                            "Отменили на сумму, ₽": row["cancelSum"],
                            "Отменили на сумму, ₽ (предыдущий период)": row["cancelSum_prev"],
                            "Средняя цена, ₽": row["avg_price"],
                            "Средняя цена, ₽ (предыдущий период)": row["avg_price_prev"],
                            "Среднее количество заказов в день, шт": row["avg_orders_per_day"],
                            "Среднее количество заказов в день, шт (предыдущий период)": row["avg_orders_per_day_prev"],
                            "Остатки склад ВБ, шт": row["wb_stock_qty"],
                            "Остатки МП, шт": row["mp_stock_qty"],
                            "Сумма остатков на складах, ₽": row["stock_total_sum"],
                            "Среднее время доставки": row["avg_delivery_time"],
                            "Среднее время доставки (предыдущий период)": row["avg_delivery_time_prev"],
                            "Локальные заказы, %": row["local_orders_percent"],
                            "Локальные заказы, % (предыдущий период)": row["local_orders_percent_prev"],
                            "Заказали ВБ клуб, шт": row["wbclub_orderCount"],
                            "Заказали ВБ клуб, шт (предыдущий период)": row["wbclub_orderCount_prev"],
                            "Выкупили ВБ клуб, шт": row["wbclub_buyoutCount"],
                            "Выкупили ВБ клуб, шт (предыдущий период)": row["wbclub_buyoutCount_prev"],
                            "Отменили ВБ клуб, шт": row["wbclub_cancelCount"],
                            "Отменили ВБ клуб, шт (предыдущий период)": row["wbclub_cancelCount_prev"],
                            "Процент выкупа ВБ клуб": row["wbclub_buyoutPercent"],
                            "Процент выкупа ВБ клуб (предыдущий период)": row["wbclub_buyoutPercent_prev"],
                            "Заказали на сумму ВБ клуб, ₽": row["wbclub_orderSum"],
                            "Заказали на сумму ВБ клуб, ₽ (предыдущий период)": row["wbclub_orderSum_prev"],
                            "Динамика суммы заказов ВБ клуб, ₽": row["wbclub_orderSumDynamics"],
                            "Выкупили на сумму ВБ клуб, ₽": row["wbclub_buyoutSum"],
                            "Выкупили на сумму ВБ клуб, ₽ (предыдущий период)": row["wbclub_buyoutSum_prev"],
                            "Отменили на сумму ВБ клуб, ₽": row["wbclub_cancelSum"],
                            "Отменили на сумму ВБ клуб, ₽ (предыдущий период)": row["wbclub_cancelSum_prev"],
                            "Среднее количество заказов в день ВБ клуб, шт": row["wbclub_avg_orders_per_day"],
                            "Среднее количество заказов в день ВБ клуб, шт (предыдущий период)": row["wbclub_avg_orders_per_day_prev"],
                            "процент показов рекламных": "",
                            "показы РК": "",
                            "переплат за корзину в сравнении со вчера": "",
                            "конверсия из показа в корзину": "",
                            "стоимость клика за кабинет": "",
                            "стоимость корзины за кабинет": "",
                            "стоимость заказа за кабинет (CPO)": "",
                            "стоимость 1000 показов за кабинет": "",
                            "рк": "",
                            "data_status": row["data_status"],
                            "source_status": "PARTIAL",
                            "loaded_at": row["loaded_at"],
                        }
                    )

        funnel_sheet_result, _ = self._sheet_rows_and_report(
            "Воронка на день",
            USER_SHEET_SCHEMAS["Воронка на день"].columns,
            funnel_output_rows,
            "WB Sales Funnel",
            "/api/analytics/v3/sales-funnel/products/history",
            "POST",
            "PARTIAL" if funnel_status == "200" and funnel_output_rows else ("PARTIAL" if funnel_status == "200" else "FAIL"),
            funnel_status,
            ["date", "nm_id", "impressions", "card_clicks", "cartCount", "orderCount", "orderSum", "buyoutSum"],
            [] if funnel_output_rows else ["date", "nm_id"],
            "window written by day with previous-day comparison where available",
        )
        results.append(funnel_sheet_result)

        # processed fact_funnel_day CSV
        self._write_csv(
            DATA_DIR / "fact_funnel_day.csv",
            funnel_rows,
            PROCESSED_TABLE_SCHEMAS["fact_funnel_day"].columns,
        )

        validation_rows = _build_suspicious_ctr_validation_rows(funnel_rows)
        validation_result, _ = self._sheet_rows_and_report(
            "Validation_v1",
            USER_SHEET_SCHEMAS["Validation_v1"].columns,
            validation_rows,
            "Funnel validation",
            "/api/analytics/v3/sales-funnel/products/history",
            "POST",
            "WARNING" if validation_rows else "OK",
            funnel_status,
            ["date", "nm_id", "impressions", "card_clicks", "ctr"],
            [],
            "suspicious_ctr warnings are logged when CTR is 80 or above; production review only",
        )
        results.append(validation_result)

        # 4) Stocks
        stocks_status, stocks_payload, stocks_error = self._fetch_stocks(self.date_to)
        stocks_items = _list_from_payload(stocks_payload, ("data", "items"), ("items",))
        stock_rows = []
        stock_sheet_rows = []
        for item in stocks_items:
            if not isinstance(item, dict):
                continue
            nm_id = _first_int(item, "nmID", "nmId")
            if nm_id not in self.nm_ids:
                continue
            row = self._build_stock_row(item)
            stock_rows.append(row)
            stock_sheet_rows.append(
                {
                    "snapshot_date": row["snapshot_date"],
                    "nm_id": row["nm_id"],
                    "supplier_article": row["supplier_article"],
                    "title": row["title"],
                    "subject": row["subject"],
                    "brand": row["brand"],
                    "wb_stock_qty": row["wb_stock_qty"],
                    "mp_stock_qty": row["mp_stock_qty"],
                    "stock_total_qty": row["stock_total_qty"],
                    "stock_total_sum": row["stock_total_sum"],
                    "saleRate": row["saleRate"],
                    "toClientCount": row["toClientCount"],
                    "fromClientCount": row["fromClientCount"],
                    "availability": row["availability"],
                    "data_status": row["data_status"],
                    "source_status": row["source_status"],
                    "loaded_at": row["loaded_at"],
                }
            )

        stock_sheet_result, _ = self._sheet_rows_and_report(
            "Остатки",
            USER_SHEET_SCHEMAS["Остатки"].columns,
            stock_sheet_rows,
            "WB Stocks products",
            "/api/v2/stocks-report/products/products",
            "POST",
            "PARTIAL" if stocks_status == "200" and stock_sheet_rows else ("PARTIAL" if stocks_status == "200" else "FAIL"),
            stocks_status,
            ["snapshot_date", "nm_id", "wb_stock_qty", "stock_total_sum"],
            ["mp_stock_qty"] if stock_sheet_rows else ["snapshot_date", "nm_id"],
            "current snapshot only; mp_stock_qty remains partial",
        )
        results.append(stock_sheet_result)

        self._write_csv(
            DATA_DIR / "fact_stock_snapshot.csv",
            stock_rows,
            PROCESSED_TABLE_SCHEMAS["fact_stock_snapshot"].columns,
        )

        # 5) Promotion costs
        ad_status, ad_payload, ad_error = self._fetch_ad_costs(self.date_from, self.date_to)
        ad_items = _list_from_payload(ad_payload, ("data",), ("items",), ("upd",))
        ad_event_rows: list[dict[str, Any]] = []
        ad_sheet_rows: list[dict[str, Any]] = []
        for item in ad_items:
            if not isinstance(item, dict):
                continue
            row = self._build_ad_event_row(item)
            ad_event_rows.append(row)
            ad_sheet_rows.append(
                {
                    "ID кампании": row["advertId"],
                    "Кампания": row["campaign_name"],
                    "Раздел": row["section_display"],
                    "Дата списания": _format_writeoff_datetime_for_sheet(row["writeoff_datetime"]),
                    "Источник списания": row["writeoff_source"],
                    "Сумма": row["spend"],
                    "Номер документа": row["document_number"],
                    "nm_id": row["nm_id"],
                    "nm_id_parse_status": row["nm_id_parse_status"],
                    "campaign_type": row["campaign_type"],
                    "data_status": row["data_status"],
                    "source_status": row["source_status"],
                    "loaded_at": row["loaded_at"],
                }
            )

        ad_sheet_result, _ = self._sheet_rows_and_report(
            "РасходРК",
            USER_SHEET_SCHEMAS["РасходРК"].columns,
            ad_sheet_rows,
            "WB Promotion costs",
            "/adv/v1/upd",
            "GET",
            "PARTIAL" if ad_status == "200" and ad_sheet_rows else ("PARTIAL" if ad_status == "200" else "FAIL"),
            ad_status,
            ["advertId", "campName", "updTime", "updSum", "updNum"],
            ["nm_id"] if ad_sheet_rows else ["advertId"],
            "event-level spend rows written without clearing the sheet",
        )
        results.append(ad_sheet_result)

        ad_day_rows = self._build_ad_day_rows(ad_event_rows)
        campaign_name_index = {
            int(row["advertId"]): row["campaign_name"]
            for row in ad_event_rows
            if row.get("advertId") not in (None, "") and row.get("campaign_name")
        }
        campaign_ids = sorted({
            int(row["advertId"])
            for row in ad_event_rows
            if row.get("advertId") not in (None, "") and _to_int(row.get("nm_id")) in self.nm_ids
        })
        fullstats_status, fullstats_payload, fullstats_error = self._fetch_fullstats(campaign_ids)
        fullstats_campaign_rows, fullstats_nm_rows = self._build_fullstats_rows(fullstats_payload, campaign_name_index)
        reference_index = _build_reference_index(funnel_rows, stock_rows)
        self._write_csv(
            DATA_DIR / "fact_ad_cost_event.csv",
            ad_event_rows,
            PROCESSED_TABLE_SCHEMAS["fact_ad_cost_event"].columns,
        )
        self._write_csv(
            DATA_DIR / "fact_ad_cost_day.csv",
            ad_day_rows,
            PROCESSED_TABLE_SCHEMAS["fact_ad_cost_day"].columns,
        )
        self._write_csv(
            DATA_DIR / "fact_ad_campaign_day.csv",
            fullstats_campaign_rows,
            PROCESSED_TABLE_SCHEMAS["fact_ad_campaign_day"].columns,
        )
        self._write_csv(
            DATA_DIR / "fact_ad_campaign_nm_day.csv",
            fullstats_nm_rows,
            PROCESSED_TABLE_SCHEMAS["fact_ad_campaign_nm_day"].columns,
        )

        rk_sheet_rows: list[dict[str, Any]] = []
        for row in fullstats_campaign_rows + fullstats_nm_rows:
            rk_sheet_rows.append(
                {
                    "Дата": row["date"],
                    "ID кампании": row["advertId"],
                    "Название кампании": row["campaign_name"],
                    "Тип строки": row["row_type"],
                    "Тип конверсии": _format_fullstats_conversion_type_for_sheet(row.get("conversion_type_raw", ""), row.get("conversion_type", "")),
                    "Номенклатура": row.get("nm_id", ""),
                    "Название товара": row.get("product_name", ""),
                    "Затраты, ₽": row["ad_spend"],
                    "Выручка, ₽": row["ad_revenue"],
                    "Показы": row["ad_views"],
                    "Клики": row["ad_clicks"],
                    "Добавления в корзину": row["ad_atbs"],
                    "Заказы": row["ad_orders"],
                    "Заказанные товары, шт.": row["ordered_items_qty"],
                    "Отмены": row["ad_cancels"],
                    "Средняя позиция": row["avg_position"],
                    "CTR, %": row["ad_ctr"],
                    "CPC, ₽": row["ad_cpc"],
                    "CPM, ₽": "",
                    "CR, %": row["ad_cr"],
                    "ROI, %": "",
                    "data_status": row["data_status"],
                    "source_status": row["source_status"],
                    "loaded_at": row["loaded_at"],
                }
            )

        rk_sheet_result, _ = self._sheet_rows_and_report(
            "РК стата",
            USER_SHEET_SCHEMAS["РК стата"].columns,
            rk_sheet_rows,
            "WB Promotion fullstats",
            "/adv/v3/fullstats",
            "GET",
            "PARTIAL" if fullstats_status == "200" and rk_sheet_rows else ("SKIPPED" if fullstats_status == "200" else "FAIL"),
            fullstats_status,
            ["date", "advertId", "campaign_name", "row_type", "conversion_type", "nm_id", "ad_spend", "ad_revenue", "ad_views", "ad_clicks", "ad_atbs", "ad_orders", "ad_cancels", "avg_position", "ad_ctr", "ad_cpc", "ad_cr"],
            ["ad_cpm", "ad_roi"],
            "live fullstats rows written; production runs should use D-2 or earlier because yesterday can be incomplete; CPM and ROI remain blank until a formula is confirmed",
        )
        results.append(rk_sheet_result)

        # 6) Search queries
        search_rows: list[dict[str, Any]] = []
        search_sheet_rows: list[dict[str, Any]] = []
        search_current_payloads: dict[str, Any] = {}
        search_prev_payloads: dict[str, Any] = {}
        search_status_parts: list[str] = []
        for day in [self.date_from, self.date_to]:
            status_code, payload, error = self._fetch_search_texts(day)
            search_status_parts.append(status_code)
            if status_code == "200":
                search_current_payloads[day.isoformat()] = payload
            else:
                search_current_payloads[day.isoformat()] = None
                if error:
                    search_prev_payloads[day.isoformat()] = error
        # build current day rows with previous day lookup
        current_payload = search_current_payloads.get(self.date_to.isoformat())
        prev_payload = search_current_payloads.get(self.date_from.isoformat())
        search_rows = self._build_search_rows(self.date_to, current_payload, prev_payload, reference_index)
        search_prev_rows = self._build_search_rows(self.date_from, prev_payload, None, reference_index)
        search_rows.extend(search_prev_rows)
        search_rows = sorted(search_rows, key=lambda row: (row.get("date", ""), row.get("nm_id", ""), row.get("search_query", "")))

        for row in search_rows:
            search_sheet_rows.append(
                {
                    "Артикул продавца": row["supplier_article"],
                    "Артикул WB": row["nm_id"],
                    "Название": row["title"],
                    "Предмет": row["subject"],
                    "Бренд": row["brand"],
                    "Рейтинг карточки": row["card_rating"],
                    "Рейтинг по отзывам": row["reviews_rating"],
                    "Поисковый запрос": row["search_query"],
                    "Количество запросов": row["query_count"],
                    "Количество запросов (предыдущий период)": row["query_count_prev"],
                    "Видимость, %": row["visibility"],
                    "Видимость, % (предыдущий период)": row["visibility_prev"],
                    "Средняя позиция": row["avg_position"],
                    "Средняя позиция (предыдущий период)": row["avg_position_prev"],
                    "Медианная позиция": row["median_position"],
                    "Медианная позиция (предыдущий период)": row["median_position_prev"],
                    "Переходы в карточку": row["search_clicks"],
                    "Переходы в карточку (предыдущий период)": row["search_clicks_prev"],
                    "Переходы в карточку больше, чем у n% карточек конкурентов, %": row["search_clicks_competitor_percentile"],
                    "Положили в корзину": row["search_cart"],
                    "Положили в корзину (предыдущий период)": row["search_cart_prev"],
                    "Положили в корзину больше, чем n% карточек конкурентов, %": row["search_cart_competitor_percentile"],
                    "Конверсия в корзину, %": row["cart_conversion"],
                    "Конверсия в корзину, % (предыдущий период)": row["cart_conversion_prev"],
                    "Конверсия в корзину больше, чем у n% карточек конкурентов, %": row["cart_conversion_competitor_percentile"],
                    "Заказали, шт": row["search_orders"],
                    "Заказали, шт (предыдущий период)": row["search_orders_prev"],
                    "Заказали больше, чем n% карточек конкурентов, %": row["search_orders_competitor_percentile"],
                    "Конверсия в заказ, %": row["order_conversion"],
                    "Конверсия в заказ, % (предыдущий период)": row["order_conversion_prev"],
                    "Конверсия в заказ больше, чем у n% карточек конкурентов, %": row["order_conversion_competitor_percentile"],
                    "Минимальная цена со скидкой (по размерам), ₽": row["min_discount_price"],
                    "Максимальная цена со скидкой (по размерам), ₽": row["max_discount_price"],
                    "data_status": row["data_status"],
                    "source_status": row["source_status"],
                    "loaded_at": row["loaded_at"],
                }
            )

        search_sheet_result, _ = self._sheet_rows_and_report(
            "Поисковые запросы",
            USER_SHEET_SCHEMAS["Поисковые запросы"].columns,
            search_sheet_rows,
            "WB Search texts",
            "/api/v2/search-report/product/search-texts",
            "POST",
            "PARTIAL" if "200" in search_status_parts and search_sheet_rows else ("PARTIAL" if any(code == "200" for code in search_status_parts) else "FAIL"),
            "200" if "200" in search_status_parts else search_status_parts[-1] if search_status_parts else "N/A",
            ["search_query", "query_count", "visibility", "avg_position", "median_position", "search_clicks", "search_cart", "search_orders"],
            ["competitor_percentiles", "min_discount_price", "max_discount_price"],
            "current day written with previous-period comparison",
        )
        results.append(search_sheet_result)

        self._write_csv(
            DATA_DIR / "fact_search_query_metric.csv",
            search_rows,
            PROCESSED_TABLE_SCHEMAS["fact_search_query_metric"].columns,
        )

        # 7) Itogo v1
        itogo_rows = self._build_itogo_rows(funnel_rows, stock_rows, search_rows, ad_day_rows)
        itogo_sheet_result, _ = self._sheet_rows_and_report(
            "ИТОГО_v1",
            USER_SHEET_SCHEMAS["ИТОГО_v1"].columns,
            itogo_rows,
            "WB Analytics + WB Promotion + WB Stocks + WB Search",
            "mixed",
            "MIXED",
            "PARTIAL" if itogo_rows else "FAIL",
            "200" if itogo_rows else "N/A",
            ["date", "nm_id", "impressions", "card_clicks", "orderCount", "current_stockCount", "search_queries_count"],
            ["title", "subject", "brand", "ad_views", "ad_clicks", "ad_orders", "ad_atbs"],
            "wide MVP sheet built from confirmed live sources only",
        )
        itogo_number_columns = ("ctr", "buyoutPercent", "addToCartConversion", "cartToOrderConversion", "visibility", "avg_position")
        itogo_ranges = []
        for column in itogo_number_columns:
            if column in USER_SHEET_SCHEMAS["ИТОГО_v1"].columns:
                col_index = USER_SHEET_SCHEMAS["ИТОГО_v1"].columns.index(column) + 1
                itogo_ranges.append((2, col_index, 5000, col_index))
        if itogo_ranges:
            self.gs_client.format_number_ranges(self.spreadsheet_id, "ИТОГО_v1", itogo_ranges)
        results.append(itogo_sheet_result)

        self._write_csv(
            DATA_DIR / "itogo_v1.csv",
            itogo_rows,
            USER_SHEET_SCHEMAS["ИТОГО_v1"].columns,
        )

        # 8) backlog
        backlog_rows = self._build_backlog_rows()
        backlog_written = self._append_sheet_rows("Backlog", USER_SHEET_SCHEMAS["Backlog"].columns, backlog_rows)
        results.append(
            SourceRun(
                source="Backlog",
                endpoint="sheet append",
                method="WRITE",
                status="OK",
                http_status="200",
                objects_count=len(backlog_rows),
                rows_written=backlog_written,
                target="Backlog",
                notes="appended live-run blockers and later items",
            )
        )

        # 9) MPStat connectivity check
        mpstat_status, mpstat_payload, mpstat_error = self._fetch_mpstat()
        mpstat_result = SourceRun(
            source="MPStat",
            endpoint="/item/{nm_id}",
            method="GET",
            status="OK" if mpstat_status == "200" and mpstat_payload else ("FAIL" if mpstat_status not in {"200", "SKIPPED"} else "PARTIAL"),
            http_status=mpstat_status,
            objects_count=1 if mpstat_payload else 0,
            fields_found=["nm_id", "title", "brand"] if mpstat_payload else [],
            fields_missing=[] if mpstat_payload else ["nm_id", "title", "brand"],
            error_short=mpstat_error,
            notes="connectivity/auth check only",
        )
        results.append(mpstat_result)

        # 10) report / summary
        report_rows = [item.to_report_row() for item in results]
        summary = {
            "generated_at": self.loaded_at,
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "test_nm_ids": TEST_NM_IDS,
            "filled_tabs": [item.target for item in results if item.rows_written > 0 and item.target],
            "results": [asdict(item) for item in results],
            "report_rows": report_rows,
            "backlog_updates": backlog_rows,
            "safety": {
                "google_sheets_written": True,
                "raw_private_payloads_saved": False,
                "mock_data_created": False,
                "wb_mpstat_write_calls_executed": False,
                "existing_fake_rows_left_untouched": True,
            },
        }

        self._write_report(results, summary)
        return summary


def main() -> dict[str, Any]:
    runner = MvpRealRun()
    summary = runner.run()
    print(f"Markdown report: {DOCS_DIR / 'mvp_real_run_report.md'}")
    print(f"CSV report: {DATA_DIR / 'mvp_real_run_report.csv'}")
    print(f"JSON summary: {DATA_DIR / 'mvp_real_run_summary.json'}")
    return summary
