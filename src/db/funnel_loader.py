from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import FactFunnelDay
from src.db.session import session_scope, upsert_rows
from src.pipelines.mvp_real_run import MvpRealRun, TEST_NM_IDS, _first_int, _first_text, _sum_numbers, _to_date_text


FACT_FUNNEL_DAY_CONFLICT_COLUMNS = ("date", "nm_id")
SUPPORTED_NM_IDS = tuple(TEST_NM_IDS)


def _resolve_nm_ids(nm_ids: Sequence[int] | None = None) -> tuple[int, ...]:
    return tuple(nm_ids) if nm_ids else tuple(SUPPORTED_NM_IDS)


def _to_decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ArithmeticError, InvalidOperation, ValueError):
        return None


def _to_datetime_or_none(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError(f"Unsupported datetime value: {value!r}")


def _to_date_or_none(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"Unsupported date value: {value!r}")


def _duration_text_to_hours(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float, Decimal)):
        return _to_decimal_or_none(value)
    if not isinstance(value, str):
        return None

    parts = value.replace(",", ".").split()
    total_hours = Decimal("0")
    index = 0
    while index + 1 < len(parts):
        number = _to_decimal_or_none(parts[index])
        unit = parts[index + 1].lower()
        index += 2
        if number is None:
            continue
        if unit.startswith("д"):
            total_hours += number * Decimal("24")
        elif unit.startswith("ч"):
            total_hours += number
        elif unit.startswith("мин"):
            total_hours += number / Decimal("60")
    return total_hours if total_hours != Decimal("0") or "0" in value else None


def build_fact_funnel_day_db_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "date": _to_date_or_none(row.get("date")),
        "nm_id": _first_int(row, "nm_id", "nmId", "nmID"),
        "impressions": _to_decimal_or_none(row.get("impressions")),
        "impressions_prev": _to_decimal_or_none(row.get("impressions_prev")),
        "card_clicks": _to_decimal_or_none(row.get("card_clicks")),
        "card_clicks_prev": _to_decimal_or_none(row.get("card_clicks_prev")),
        "ctr": _to_decimal_or_none(row.get("ctr")),
        "ctr_prev": _to_decimal_or_none(row.get("ctr_prev")),
        "revenue_share_percent": _to_decimal_or_none(row.get("revenue_share_percent")),
        "revenue_share_percent_prev": _to_decimal_or_none(row.get("revenue_share_percent_prev")),
        "cart_count": _to_decimal_or_none(row.get("cartCount")),
        "cart_count_prev": _to_decimal_or_none(row.get("cartCount_prev")),
        "wishlist_count": _to_decimal_or_none(row.get("addToWishlistCount")),
        "wishlist_count_prev": _to_decimal_or_none(row.get("addToWishlistCount_prev")),
        "order_count": _to_decimal_or_none(row.get("orderCount")),
        "order_count_prev": _to_decimal_or_none(row.get("orderCount_prev")),
        "buyout_count": _to_decimal_or_none(row.get("buyoutCount")),
        "buyout_count_prev": _to_decimal_or_none(row.get("buyoutCount_prev")),
        "cancel_count": _to_decimal_or_none(row.get("cancelCount")),
        "cancel_count_prev": _to_decimal_or_none(row.get("cancelCount_prev")),
        "add_to_cart_conversion": _to_decimal_or_none(row.get("addToCartConversion")),
        "add_to_cart_conversion_prev": _to_decimal_or_none(row.get("addToCartConversion_prev")),
        "cart_to_order_conversion": _to_decimal_or_none(row.get("cartToOrderConversion")),
        "cart_to_order_conversion_prev": _to_decimal_or_none(row.get("cartToOrderConversion_prev")),
        "buyout_percent": _to_decimal_or_none(row.get("buyoutPercent")),
        "buyout_percent_prev": _to_decimal_or_none(row.get("buyoutPercent_prev")),
        "order_sum": _to_decimal_or_none(row.get("orderSum")),
        "order_sum_prev": _to_decimal_or_none(row.get("orderSum_prev")),
        "buyout_sum": _to_decimal_or_none(row.get("buyoutSum")),
        "buyout_sum_prev": _to_decimal_or_none(row.get("buyoutSum_prev")),
        "cancel_sum": _to_decimal_or_none(row.get("cancelSum")),
        "cancel_sum_prev": _to_decimal_or_none(row.get("cancelSum_prev")),
        "avg_price": _to_decimal_or_none(row.get("avg_price")),
        "avg_price_prev": _to_decimal_or_none(row.get("avg_price_prev")),
        "avg_orders_per_day": _to_decimal_or_none(row.get("avg_orders_per_day")),
        "avg_orders_per_day_prev": _to_decimal_or_none(row.get("avg_orders_per_day_prev")),
        "avg_delivery_time": _duration_text_to_hours(row.get("avg_delivery_time")),
        "avg_delivery_time_prev": _duration_text_to_hours(row.get("avg_delivery_time_prev")),
        "local_orders_percent": _to_decimal_or_none(row.get("local_orders_percent")),
        "local_orders_percent_prev": _to_decimal_or_none(row.get("local_orders_percent_prev")),
        "data_status": row.get("data_status") or None,
        "source_status": row.get("source_status") or None,
        "loaded_at": _to_datetime_or_none(row.get("loaded_at")),
    }


def prepare_fact_funnel_day_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: dict[tuple[date, int], dict[str, Any]] = {}
    for row in rows:
        mapped = build_fact_funnel_day_db_row(row)
        key = (mapped.get("date"), mapped.get("nm_id"))
        if key[0] is None or key[1] is None:
            continue
        prepared[key] = mapped
    return list(prepared.values())


def collect_funnel_rows(
    runner: MvpRealRun,
    start: date,
    end: date,
    nm_ids: Sequence[int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    runner.nm_ids = list(resolved_nm_ids)
    funnel_status, funnel_payload, funnel_error = runner._fetch_funnel(start, end)
    if funnel_status != "200":
        raise RuntimeError(f"Funnel history request failed: {funnel_status} {funnel_error}")

    funnel_items = runner._expand_funnel_payload(funnel_payload)
    funnel_by_day: dict[str, list[dict[str, Any]]] = {}
    prev_index: dict[tuple[int | None, str], dict[str, Any]] = {}
    for item in funnel_items:
        if not isinstance(item, dict):
            continue
        day = _to_date_text(_first_text(item, "date", "dt", "start"))
        product = item.get("product") if isinstance(item.get("product"), dict) else {}
        nm_id = _first_int(item, "nmId", "nmID") or _first_int(product, "nmId", "nmID")
        if day:
            funnel_by_day.setdefault(day, []).append(item)
        if day and nm_id is not None:
            prev_index[(nm_id, day)] = item

    funnel_products_status, funnel_products_payload, funnel_products_error = runner._fetch_funnel_products(start, end)
    funnel_products_index = runner._build_funnel_products_index(funnel_products_payload) if funnel_products_status == "200" else {}

    funnel_rows: list[dict[str, Any]] = []
    if funnel_by_day:
        day_totals = {day_key: _sum_numbers(item.get("orderSum") for item in items) for day_key, items in funnel_by_day.items()}
        for day_key in sorted(funnel_by_day):
            prev_day_key = (date.fromisoformat(day_key) - timedelta(days=1)).isoformat()
            for item in funnel_by_day[day_key]:
                product = item.get("product") if isinstance(item.get("product"), dict) else {}
                nm_id = _first_int(item, "nmId", "nmID") or _first_int(product, "nmId", "nmID")
                if nm_id is None or nm_id not in resolved_nm_ids:
                    continue
                prev_item = prev_index.get((nm_id, prev_day_key))
                row = runner._build_funnel_row(
                    item,
                    prev_item,
                    day_totals.get(day_key),
                    day_totals.get(prev_day_key),
                    product,
                    funnel_products_index.get(nm_id, {}),
                )
                row["date"] = day_key
                row["nm_id"] = nm_id
                funnel_rows.append(row)

    metadata = {
        "history_status": funnel_status,
        "products_status": funnel_products_status,
        "history_error": funnel_error,
        "products_error": funnel_products_error,
        "rows_fetched": len(funnel_rows),
    }
    return funnel_rows, metadata


def upsert_fact_funnel_day(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_fact_funnel_day_upsert_rows(rows)
    upsert_rows(
        session=session,
        model=FactFunnelDay,
        rows=prepared_rows,
        conflict_columns=FACT_FUNNEL_DAY_CONFLICT_COLUMNS,
    )
    return len(prepared_rows)


def count_fact_funnel_day_rows(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactFunnelDay)
        .where(FactFunnelDay.date >= start, FactFunnelDay.date <= end, FactFunnelDay.nm_id.in_(list(resolved_nm_ids)))
    )
    return int(session.execute(stmt).scalar_one())


def count_fact_funnel_day_duplicates(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    dup_stmt = (
        select(FactFunnelDay.date, FactFunnelDay.nm_id)
        .where(FactFunnelDay.date >= start, FactFunnelDay.date <= end, FactFunnelDay.nm_id.in_(list(resolved_nm_ids)))
        .group_by(FactFunnelDay.date, FactFunnelDay.nm_id)
        .having(func.count() > 1)
    )
    return len(session.execute(dup_stmt).all())


def count_suspicious_fallback_ctr_rows(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactFunnelDay)
        .where(
            FactFunnelDay.date >= start,
            FactFunnelDay.date <= end,
            FactFunnelDay.nm_id.in_(list(resolved_nm_ids)),
            FactFunnelDay.ctr == Decimal("100"),
            FactFunnelDay.card_clicks.is_not(None),
            FactFunnelDay.impressions.is_not(None),
            FactFunnelDay.card_clicks == FactFunnelDay.impressions,
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_null_card_clicks_rows(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactFunnelDay)
        .where(
            FactFunnelDay.date >= start,
            FactFunnelDay.date <= end,
            FactFunnelDay.nm_id.in_(list(resolved_nm_ids)),
            FactFunnelDay.card_clicks.is_(None),
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_null_ctr_rows(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactFunnelDay)
        .where(
            FactFunnelDay.date >= start,
            FactFunnelDay.date <= end,
            FactFunnelDay.nm_id.in_(list(resolved_nm_ids)),
            FactFunnelDay.ctr.is_(None),
        )
    )
    return int(session.execute(stmt).scalar_one())


def load_funnel_to_db(start: date, end: date, nm_ids: Sequence[int] | None = None) -> dict[str, Any]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    runner = MvpRealRun()
    runner.date_from = start
    runner.date_to = end
    funnel_rows, metadata = collect_funnel_rows(runner, start, end, nm_ids=resolved_nm_ids)

    with session_scope() as session:
        upserted_rows = upsert_fact_funnel_day(session, funnel_rows)
        total_rows = count_fact_funnel_day_rows(session, start, end, resolved_nm_ids)
        duplicate_keys = count_fact_funnel_day_duplicates(session, start, end, resolved_nm_ids)
        fallback_ctr_rows = count_suspicious_fallback_ctr_rows(session, start, end, resolved_nm_ids)
        null_card_clicks_rows = count_null_card_clicks_rows(session, start, end, resolved_nm_ids)
        null_ctr_rows = count_null_ctr_rows(session, start, end, resolved_nm_ids)

    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "nm_ids": list(resolved_nm_ids),
        "rows_fetched": metadata["rows_fetched"],
        "rows_upserted": upserted_rows,
        "rows_in_db": total_rows,
        "duplicate_keys": duplicate_keys,
        "suspicious_fallback_ctr_rows": fallback_ctr_rows,
        "null_card_clicks_rows": null_card_clicks_rows,
        "null_ctr_rows": null_ctr_rows,
        "history_status": metadata["history_status"],
        "products_status": metadata["products_status"],
    }
