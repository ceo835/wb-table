from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.db.funnel_loader import _to_date_or_none, _to_datetime_or_none, _to_decimal_or_none
from src.db.models import FactStockWarehouseSnapshot, FactWbSearchQueryTextDay, SettingsProducts
from src.db.product_query_group_backfill import QUERY_GROUP_UNKNOWN, QUERY_GROUP_VALUES, normalize_query_group_value
from src.db.session import session_scope, upsert_rows
from src.tracked_products import TRACKED_PRODUCTS_PATH, get_tracked_nm_ids


WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"
WB_SEARCH_TEXTS_ENDPOINT = f"{WB_ANALYTICS_BASE}/api/v2/search-report/product/search-texts"
WB_SEARCH_TEXT_SOURCE = "wb_search_texts_api"
FACT_WB_SEARCH_QUERY_TEXT_DAY_CONFLICT_COLUMNS = ("day", "nm_id", "query_text")
DEFAULT_SEARCH_TEXT_LIMIT = 100
FALLBACK_SEARCH_TEXT_LIMIT = 30


def _to_int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _nested_current_value(payload: Mapping[str, Any] | None, key: str) -> Any:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get(key)
    if isinstance(value, Mapping):
        return value.get("current")
    return value


def _headers() -> dict[str, str]:
    if not settings.wb_analytics_token:
        raise RuntimeError("WB_ANALYTICS_TOKEN is missing")
    return {
        "Authorization": settings.wb_analytics_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def build_search_texts_payload(
    target_day: date,
    nm_ids: Sequence[int],
    *,
    limit: int = DEFAULT_SEARCH_TEXT_LIMIT,
) -> dict[str, Any]:
    if not nm_ids:
        raise ValueError("nm_ids must not be empty")
    previous_day = target_day - timedelta(days=1)
    if previous_day >= target_day:
        raise ValueError("pastPeriod must end before currentPeriod")
    return {
        "currentPeriod": {"start": target_day.isoformat(), "end": target_day.isoformat()},
        "pastPeriod": {"start": previous_day.isoformat(), "end": previous_day.isoformat()},
        "nmIds": [int(nm_id) for nm_id in nm_ids],
        "topOrderBy": "openCard",
        "includeSubstitutedSKUs": True,
        "includeSearchTexts": True,
        "orderBy": {"field": "avgPosition", "mode": "asc"},
        "limit": int(limit),
    }


def _list_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("items"), list):
        return [item for item in data["items"] if isinstance(item, Mapping)]
    if isinstance(payload.get("items"), list):
        return [item for item in payload["items"] if isinstance(item, Mapping)]
    return []


def fetch_search_texts_payload(
    *,
    target_day: date,
    nm_ids: Sequence[int],
    limit: int = DEFAULT_SEARCH_TEXT_LIMIT,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    if len(nm_ids) > 50:
        raise ValueError("nm_ids size cannot exceed 50")

    request_attempts: list[dict[str, Any]] = []
    session = requests.Session()
    attempt_limits = [int(limit)]
    if int(limit) != FALLBACK_SEARCH_TEXT_LIMIT:
        attempt_limits.append(FALLBACK_SEARCH_TEXT_LIMIT)

    for attempt_limit in attempt_limits:
        payload = build_search_texts_payload(target_day, nm_ids, limit=attempt_limit)
        response = session.post(
            WB_SEARCH_TEXTS_ENDPOINT,
            headers=_headers(),
            json=payload,
            timeout=timeout_seconds,
        )
        try:
            response_payload = response.json()
            error_text = ""
        except ValueError:
            response_payload = {"raw_text": response.text[:2000]}
            error_text = response.text[:500]
        if response.status_code != 200 and not error_text:
            error_text = json.dumps(response_payload, ensure_ascii=False)[:500]
        request_attempts.append(
            {
                "status": str(response.status_code),
                "limit": attempt_limit,
                "error": error_text,
            }
        )
        if response.status_code == 200:
            return {
                "status": "200",
                "items": _list_items(response_payload),
                "payload": response_payload,
                "error": "",
                "limit_used": attempt_limit,
                "fallback_used": attempt_limit != int(limit),
                "request_attempts": request_attempts,
            }

        if "nmIds" in error_text or "greater than maximum" in error_text:
            break

    last_attempt = request_attempts[-1]
    return {
        "status": last_attempt["status"],
        "items": [],
        "payload": None,
        "error": last_attempt["error"],
        "limit_used": last_attempt["limit"],
        "fallback_used": len(request_attempts) > 1,
        "request_attempts": request_attempts,
    }


def normalize_search_text_day_rows(
    *,
    payload: Any,
    target_day: date,
    query_group_by_nm: Mapping[int, str] | None = None,
    source: str = WB_SEARCH_TEXT_SOURCE,
    loaded_at: datetime | None = None,
) -> list[dict[str, Any]]:
    query_group_map = {int(nm_id): query_group for nm_id, query_group in (query_group_by_nm or {}).items()}
    loaded_at_value = loaded_at or datetime.now().astimezone()
    rows: list[dict[str, Any]] = []
    for item in _list_items(payload):
        nm_id = _to_int_or_none(item.get("nmId") or item.get("nmID") or item.get("nm_id"))
        query_text = _text_or_none(item.get("text") or item.get("searchText") or item.get("query"))
        if nm_id is None or query_text is None:
            continue
        rows.append(
            {
                "day": target_day,
                "nm_id": nm_id,
                "query_text": query_text,
                "query_group": normalize_query_group_value(query_group_map.get(nm_id)),
                "frequency_current": _to_int_or_none(_nested_current_value(item, "frequency")),
                "week_frequency": _to_int_or_none(item.get("weekFrequency")),
                "orders_current": _to_int_or_none(_nested_current_value(item, "orders")),
                "visibility_current": _to_decimal_or_none(_nested_current_value(item, "visibility")),
                "avg_position_current": _to_decimal_or_none(_nested_current_value(item, "avgPosition")),
                "open_card_current": _to_int_or_none(_nested_current_value(item, "openCard")),
                "add_to_cart_current": _to_int_or_none(_nested_current_value(item, "addToCart")),
                "source": source,
                "loaded_at": loaded_at_value,
                "raw_payload": dict(item),
            }
        )
    return rows


def prepare_fact_wb_search_query_text_day_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        mapped = {
            "day": _to_date_or_none(row.get("day")),
            "nm_id": _to_int_or_none(row.get("nm_id")),
            "query_text": _text_or_none(row.get("query_text")),
            "query_group": normalize_query_group_value(row.get("query_group")),
            "frequency_current": _to_int_or_none(row.get("frequency_current")),
            "week_frequency": _to_int_or_none(row.get("week_frequency")),
            "orders_current": _to_int_or_none(row.get("orders_current")),
            "visibility_current": _to_decimal_or_none(row.get("visibility_current")),
            "avg_position_current": _to_decimal_or_none(row.get("avg_position_current")),
            "open_card_current": _to_int_or_none(row.get("open_card_current")),
            "add_to_cart_current": _to_int_or_none(row.get("add_to_cart_current")),
            "source": _text_or_none(row.get("source")) or WB_SEARCH_TEXT_SOURCE,
            "loaded_at": _to_datetime_or_none(row.get("loaded_at")) or datetime.now().astimezone(),
            "raw_payload": row.get("raw_payload"),
        }
        if mapped["day"] is None or mapped["nm_id"] is None or mapped["query_text"] is None:
            continue
        key = tuple(mapped[column_name] for column_name in FACT_WB_SEARCH_QUERY_TEXT_DAY_CONFLICT_COLUMNS)
        prepared[key] = mapped
    return list(prepared.values())


def upsert_fact_wb_search_query_text_day(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_fact_wb_search_query_text_day_upsert_rows(rows)
    if not prepared_rows:
        return 0
    upsert_rows(
        session=session,
        model=FactWbSearchQueryTextDay,
        rows=prepared_rows,
        conflict_columns=FACT_WB_SEARCH_QUERY_TEXT_DAY_CONFLICT_COLUMNS,
        batch_size=200,
    )
    return len(prepared_rows)


def filter_products_with_known_query_group(products: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    allowed_values = set(QUERY_GROUP_VALUES) - {QUERY_GROUP_UNKNOWN}
    filtered: list[dict[str, Any]] = []
    for product in products:
        nm_id = _to_int_or_none(product.get("nm_id"))
        query_group = normalize_query_group_value(product.get("query_group"))
        if nm_id is None or query_group not in allowed_values:
            continue
        filtered.append({**product, "nm_id": nm_id, "query_group": query_group})
    return filtered


def aggregate_search_text_rows_by_query_group(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    aggregated: dict[tuple[date, str, str], dict[str, Any]] = {}
    nm_sets: dict[tuple[date, str, str], set[int]] = {}
    for row in rows:
        day_value = _to_date_or_none(row.get("day"))
        query_group = _text_or_none(row.get("query_group"))
        query_text = _text_or_none(row.get("query_text"))
        nm_id = _to_int_or_none(row.get("nm_id"))
        if day_value is None or query_group is None or query_text is None or nm_id is None:
            continue
        key = (day_value, query_group, query_text)
        bucket = aggregated.setdefault(
            key,
            {
                "day": day_value,
                "query_group": query_group,
                "query_text": query_text,
                "frequency_current": None,
                "week_frequency": None,
                "orders_current": None,
                "visibility_current": None,
                "avg_position_current": None,
                "open_card_current": None,
                "add_to_cart_current": None,
            },
        )
        nm_sets.setdefault(key, set()).add(nm_id)
        for field_name in (
            "frequency_current",
            "week_frequency",
            "orders_current",
            "visibility_current",
            "avg_position_current",
            "open_card_current",
            "add_to_cart_current",
        ):
            value = row.get(field_name)
            if value is None:
                continue
            if bucket.get(field_name) is None or value > bucket[field_name]:
                bucket[field_name] = value

    result: list[dict[str, Any]] = []
    for key, bucket in aggregated.items():
        bucket["nm_id_count"] = len(nm_sets.get(key, set()))
        result.append(bucket)
    return sorted(result, key=lambda row: (row["day"], row["query_group"], row["query_text"]))


def count_loaded_search_text_rows(session: Session, target_day: date, nm_ids: Sequence[int]) -> int:
    stmt = select(func.count()).select_from(FactWbSearchQueryTextDay).where(FactWbSearchQueryTextDay.day == target_day)
    if nm_ids:
        stmt = stmt.where(FactWbSearchQueryTextDay.nm_id.in_([int(nm_id) for nm_id in nm_ids]))
    return int(session.execute(stmt).scalar_one())


def load_search_scope_products(
    *,
    nm_id: int | None = None,
    tracked_products: bool = False,
    problem_products: bool = False,
    known_query_group_only: bool = False,
) -> list[dict[str, Any]]:
    tracked_nm_ids = set(get_tracked_nm_ids(TRACKED_PRODUCTS_PATH)) if tracked_products else set()

    with session_scope() as session:
        scope_nm_ids: set[int] = {int(nm_id)} if nm_id is not None else set()
        if tracked_products:
            scope_nm_ids |= tracked_nm_ids
        if problem_products:
            latest_snapshot_date = session.execute(select(func.max(FactStockWarehouseSnapshot.snapshot_date))).scalar_one_or_none()
            if latest_snapshot_date is not None:
                problem_nm_ids = session.execute(
                    select(FactStockWarehouseSnapshot.nm_id)
                    .where(FactStockWarehouseSnapshot.snapshot_date == latest_snapshot_date)
                    .group_by(FactStockWarehouseSnapshot.nm_id)
                    .having(func.coalesce(func.sum(FactStockWarehouseSnapshot.stock_qty), 0) <= 0)
                ).scalars().all()
                scope_nm_ids |= {int(value) for value in problem_nm_ids}
        if not scope_nm_ids:
            scope_nm_ids = tracked_nm_ids or {
                int(value)
                for value in session.execute(
                    select(SettingsProducts.nm_id).where(SettingsProducts.active.is_(True))
                ).scalars().all()
            }

        products = [
            {
                "nm_id": int(row.nm_id),
                "supplier_article": row.supplier_article,
                "title": row.title,
                "subject": row.subject,
                "brand": row.brand,
                "query_group": row.query_group,
                "active": row.active,
            }
            for row in session.execute(
                select(SettingsProducts)
                .where(SettingsProducts.nm_id.in_(sorted(scope_nm_ids)))
                .order_by(SettingsProducts.nm_id.asc())
            ).scalars()
        ]

    return filter_products_with_known_query_group(products) if known_query_group_only else products


def load_search_text_rows(
    *,
    target_day: date,
    products: Sequence[Mapping[str, Any]],
    apply: bool = False,
    limit: int = DEFAULT_SEARCH_TEXT_LIMIT,
    fetcher=None,
    nm_batch_size: int = 50,
    request_sleep_seconds: float = 2.0,
    max_retries: int = 1,
) -> dict[str, Any]:
    if nm_batch_size > 50:
        raise ValueError("nm_batch_size cannot exceed 50")

    scoped_products = list(products)
    nm_ids = sorted(
        {
            int(nm_id)
            for nm_id in (_to_int_or_none(product.get("nm_id")) for product in scoped_products)
            if nm_id is not None
        }
    )
    if not nm_ids:
        return {
            "target_day": target_day.isoformat(),
            "products_selected": 0,
            "rows_fetched": 0,
            "rows_prepared": 0,
            "rows_loaded": 0,
            "rows_in_db": 0,
            "write_executed": False,
            "api_status": "SKIPPED",
            "api_error": "NO_PRODUCTS_IN_SCOPE",
            "request_attempts": [],
            "aggregated_query_group_rows": [],
            "top_queries": [],
            "nm_batch_size": nm_batch_size,
            "batches_total": 0,
            "batches_succeeded": 0,
            "batches_failed": 0,
            "api_status_by_batch": [],
            "partial_write_prevented": False,
        }

    batches = [nm_ids[i : i + nm_batch_size] for i in range(0, len(nm_ids), nm_batch_size)]

    import time
    fetch_fn = fetcher or fetch_search_texts_payload

    all_items = []
    request_attempts = []
    api_status_by_batch = []
    batches_succeeded = 0
    batches_failed = 0

    last_fetch_result = None
    first_failed_result = None

    for idx, batch_nm_ids in enumerate(batches):
        if idx > 0 and request_sleep_seconds > 0:
            time.sleep(request_sleep_seconds)

        attempt = 0
        fetch_result = None
        while attempt <= max_retries:
            fetch_result = fetch_fn(target_day=target_day, nm_ids=batch_nm_ids, limit=limit)
            status = fetch_result.get("status")
            if status == "429":
                attempt += 1
                if attempt <= max_retries:
                    if request_sleep_seconds > 0:
                        time.sleep(request_sleep_seconds)
                    continue
            break

        status = fetch_result.get("status")
        api_status_by_batch.append(status)
        request_attempts.extend(fetch_result.get("request_attempts", []))
        last_fetch_result = fetch_result

        if status == "200":
            batches_succeeded += 1
            all_items.extend(fetch_result.get("items", []))
        else:
            batches_failed += 1
            first_failed_result = fetch_result
            break

    has_failed = batches_failed > 0
    partial_write_prevented = False

    rows = []
    prepared_rows = []
    rows_loaded = 0
    rows_in_db = 0
    write_executed = False

    if has_failed:
        if apply:
            partial_write_prevented = True
    else:
        rows = normalize_search_text_day_rows(
            payload={"data": {"items": all_items}},
            target_day=target_day,
            query_group_by_nm={
                int(product["nm_id"]): _text_or_none(product.get("query_group"))
                for product in scoped_products
                if product.get("nm_id") is not None
            },
        )
        prepared_rows = prepare_fact_wb_search_query_text_day_upsert_rows(rows)
        if apply and prepared_rows:
            with session_scope() as session:
                rows_loaded = upsert_fact_wb_search_query_text_day(session, prepared_rows)
                if hasattr(session, "execute"):
                    rows_in_db = count_loaded_search_text_rows(session, target_day, nm_ids)
                else:
                    rows_in_db = rows_loaded
            write_executed = True

    aggregated_rows = aggregate_search_text_rows_by_query_group(prepared_rows)
    final_result = first_failed_result if has_failed else last_fetch_result

    return {
        "target_day": target_day.isoformat(),
        "products_selected": len(scoped_products),
        "nm_ids": nm_ids,
        "api_status": final_result.get("status"),
        "api_error": final_result.get("error", ""),
        "limit_requested": int(limit),
        "limit_used": int(final_result.get("limit_used", limit)),
        "fallback_used": bool(final_result.get("fallback_used")),
        "request_attempts": request_attempts,
        "rows_fetched": len(all_items),
        "rows_prepared": len(prepared_rows),
        "rows_loaded": rows_loaded,
        "rows_in_db": rows_in_db,
        "write_executed": write_executed,
        "aggregated_query_group_rows": aggregated_rows,
        "top_queries": aggregated_rows[:20],
        "nm_batch_size": nm_batch_size,
        "batches_total": len(batches),
        "batches_succeeded": batches_succeeded,
        "batches_failed": batches_failed,
        "api_status_by_batch": api_status_by_batch,
        "partial_write_prevented": partial_write_prevented,
    }
