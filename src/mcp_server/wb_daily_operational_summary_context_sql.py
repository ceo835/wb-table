from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Any, Iterable, Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

LOW_STOCK_DAYS = Decimal("3")
HIGH_STOCK_DAYS = Decimal("45")
FINANCE_STATUS_NOTE = "Finance rows are partial because operation_date is derived from rr_dt/sale_dt order and may lag order day."
SELLER_PRICE_ROLLUP_RULE = (
    "Use seller_price as article-level value only when all chrt_id rows for date+nm_id have the same seller_price; "
    "otherwise keep the min/max range as PARTIAL context."
)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _record_query(query_counter: dict[str, Any], query_name: str, started_at: float) -> None:
    query_counter["count"] = int(query_counter.get("count") or 0) + 1
    elapsed_ms = int((perf_counter() - started_at) * 1000)
    query_counter.setdefault("timings", []).append({"query": query_name, "ms": elapsed_ms})


def _execute_mappings(session: Session, sql, params: dict[str, Any], query_counter: dict[str, Any], query_name: str) -> list[dict[str, Any]]:
    started_at = perf_counter()
    rows = [dict(row) for row in session.execute(sql, params).mappings().all()]
    _record_query(query_counter, query_name, started_at)
    return rows


def _unique_nm_ids(nm_ids: Sequence[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in nm_ids:
        try:
            nm_id = int(value)
        except (TypeError, ValueError):
            continue
        if nm_id <= 0 or nm_id in seen:
            continue
        seen.add(nm_id)
        result.append(nm_id)
    return result


def _trend_points(rows: Iterable[dict[str, Any]], *, date_key: str, metric_keys: Sequence[str]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: item.get(date_key) or date.min):
        point = {date_key: row.get(date_key), "date": row.get(date_key)}
        for key in metric_keys:
            point[key] = row.get(key)
        points.append(point)
    return points


def fetch_additional_source_freshness(session: Session, query_counter: dict[str, Any]) -> list[dict[str, Any]]:
    sql = text(
        """
        select 'fact_wb_site_price_snapshot' as source_name, max(snapshot_date) as max_date from fact_wb_site_price_snapshot
        union all
        select 'fact_wb_seller_price_snapshot' as source_name, max(snapshot_date) as max_date from fact_wb_seller_price_snapshot
        union all
        select 'fact_finance_realization_line' as source_name, max(operation_date) as max_date from fact_finance_realization_line
        union all
        select 'fact_entry_point_day' as source_name, max(date) as max_date from fact_entry_point_day
        """
    )
    return _execute_mappings(session, sql, {}, query_counter, "additional_source_freshness")


def fetch_article_context(session: Session, *, report_date: date, history_from: date, nm_ids: Sequence[int], query_counter: dict[str, Any]) -> list[dict[str, Any]]:
    if not nm_ids:
        return []
    sql = text(
        """
        with warehouse_agg as (
            select
                snapshot_date as report_date,
                nm_id,
                sum(coalesce(stock_qty, 0)) as warehouse_stock_qty,
                count(distinct case when coalesce(stock_qty, 0) > 0 then warehouse_id end) as warehouses_with_stock,
                count(distinct case when coalesce(stock_qty, 0) = 0 then warehouse_id end) as warehouses_zero_stock
            from fact_stock_warehouse_snapshot
            where snapshot_date >= :history_from and snapshot_date <= :report_date and nm_id in :nm_ids
            group by snapshot_date, nm_id
        )
        select
            m.report_date,
            m.nm_id,
            m.supplier_article,
            m.title,
            m.subject,
            m.brand,
            coalesce(m.impressions, m.entry_impressions_total) as impressions,
            coalesce(m.card_clicks, m.entry_card_clicks_total) as card_clicks,
            m.cart_count,
            m.order_count,
            m.order_sum,
            m.ad_spend_total,
            m.search_avg_position,
            m.search_visibility,
            m.current_stock_qty,
            m.stock_snapshot_date,
            coalesce(w.warehouse_stock_qty, m.current_stock_qty) as warehouse_stock_qty,
            w.warehouses_with_stock,
            w.warehouses_zero_stock,
            m.buyout_count,
            m.buyout_sum
        from mart_total_report m
        left join warehouse_agg w on w.report_date = m.report_date and w.nm_id = m.nm_id
        where m.report_date >= :history_from and m.report_date <= :report_date and m.nm_id in :nm_ids
        order by m.nm_id asc, m.report_date asc
        """
    ).bindparams(bindparam("nm_ids", expanding=True))
    rows = _execute_mappings(session, sql, {"report_date": report_date, "history_from": history_from, "nm_ids": list(nm_ids)}, query_counter, "article_context")
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["nm_id"])].append(row)

    ranked: list[dict[str, Any]] = []
    for nm_id in nm_ids:
        group_rows = grouped.get(int(nm_id), [])
        row_by_date = {row["report_date"]: row for row in group_rows}
        current = row_by_date.get(report_date)
        if not current:
            continue
        ranked.append({
            "report_date": report_date,
            "nm_id": int(nm_id),
            "supplier_article": current.get("supplier_article"),
            "title": current.get("title"),
            "subject": current.get("subject"),
            "brand": current.get("brand"),
            "impressions": current.get("impressions"),
            "card_clicks": current.get("card_clicks"),
            "cart_count": current.get("cart_count"),
            "order_count": current.get("order_count"),
            "order_sum": current.get("order_sum"),
            "ad_spend_total": current.get("ad_spend_total"),
            "search_avg_position": current.get("search_avg_position"),
            "search_visibility": current.get("search_visibility"),
            "current_stock_qty": current.get("current_stock_qty"),
            "stock_snapshot_date": current.get("stock_snapshot_date"),
            "warehouse_stock_qty": current.get("warehouse_stock_qty"),
            "warehouses_with_stock": current.get("warehouses_with_stock"),
            "warehouses_zero_stock": current.get("warehouses_zero_stock"),
            "buyout_count": current.get("buyout_count"),
            "buyout_sum": current.get("buyout_sum"),
            "trend_14d": _trend_points(group_rows, date_key="report_date", metric_keys=("impressions", "card_clicks", "cart_count", "order_count", "order_sum", "ad_spend_total", "search_avg_position", "search_visibility", "warehouse_stock_qty", "warehouses_with_stock", "warehouses_zero_stock")),
        })
    ranked.sort(key=lambda row: (_to_decimal(row.get("order_sum")) or Decimal("0"), _to_decimal(row.get("order_count")) or Decimal("0")), reverse=True)
    return ranked


def fetch_price_context(
    session: Session,
    *,
    report_date: date,
    compare_date: date,
    trend_current_from: date,
    nm_ids: Sequence[int],
    query_counter: dict[str, Any],
) -> list[dict[str, Any]]:
    if not nm_ids:
        return []
    site_sql = text(
        """
        select snapshot_date, snapshot_at, nm_id, buyer_visible_price, availability_status, fetch_status
        from fact_wb_site_price_snapshot
        where snapshot_date >= :trend_current_from and snapshot_date <= :report_date and nm_id in :nm_ids
        order by nm_id asc, snapshot_date asc, snapshot_at asc
        """
    ).bindparams(bindparam("nm_ids", expanding=True))
    seller_sql = text(
        """
        select snapshot_date, nm_id, count(*) as seller_rows_count, count(distinct chrt_id) as seller_variants_count,
               min(seller_price) as seller_price_min, max(seller_price) as seller_price_max
        from fact_wb_seller_price_snapshot
        where snapshot_date = :report_date and nm_id in :nm_ids
        group by snapshot_date, nm_id
        """
    ).bindparams(bindparam("nm_ids", expanding=True))
    site_rows = _execute_mappings(session, site_sql, {"trend_current_from": trend_current_from, "report_date": report_date, "nm_ids": list(nm_ids)}, query_counter, "price_context_site")
    seller_rows = _execute_mappings(session, seller_sql, {"report_date": report_date, "nm_ids": list(nm_ids)}, query_counter, "price_context_seller_partial")
    seller_by_nm = {int(row["nm_id"]): row for row in seller_rows}
    site_by_nm: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in site_rows:
        site_by_nm[int(row["nm_id"])].append(row)

    result: list[dict[str, Any]] = []
    for nm_id in nm_ids:
        rows = site_by_nm.get(int(nm_id), [])
        row_by_date = {row["snapshot_date"]: row for row in rows}
        current_row = row_by_date.get(report_date)
        previous_row = row_by_date.get(compare_date)
        current_price = _to_decimal(current_row.get("buyer_visible_price")) if current_row else None
        previous_price = _to_decimal(previous_row.get("buyer_visible_price")) if previous_row else None
        seller_row = seller_by_nm.get(int(nm_id), {})
        seller_min = _to_decimal(seller_row.get("seller_price_min"))
        seller_max = _to_decimal(seller_row.get("seller_price_max"))
        seller_status = "MISSING"
        if seller_row:
            seller_status = "OK" if seller_min is not None and seller_max is not None and seller_min == seller_max else "PARTIAL"
        result.append({
            "nm_id": int(nm_id),
            "context_date": report_date,
            "buyer_visible_price": current_price,
            "previous_buyer_visible_price": previous_price,
            "price_delta_day": (current_price - previous_price) if current_price is not None and previous_price is not None else None,
            "wallet_price": None,
            "wallet_price_status": "MISSING",
            "availability_status": current_row.get("availability_status") if current_row else None,
            "fetch_status": current_row.get("fetch_status") if current_row else None,
            "source_status": "OK" if current_row and current_row.get("fetch_status") == "success" and current_price is not None else ("PARTIAL" if current_row else "MISSING"),
            "trend_7d": _trend_points(rows, date_key="snapshot_date", metric_keys=("buyer_visible_price", "fetch_status")),
            "seller_price_status": seller_status,
            "seller_price_min": seller_min,
            "seller_price_max": seller_max,
            "seller_variants_count": seller_row.get("seller_variants_count"),
            "seller_rows_count": seller_row.get("seller_rows_count"),
            "seller_price_rollup_rule": SELLER_PRICE_ROLLUP_RULE,
        })
    return result


def fetch_logistics_context(
    session: Session,
    *,
    report_date: date,
    compare_date: date,
    trend_current_from: date,
    nm_ids: Sequence[int],
    query_counter: dict[str, Any],
) -> list[dict[str, Any]]:
    if not nm_ids:
        return []
    sql = text(
        """
        select
            operation_date,
            nm_id,
            sum(coalesce(delivery_rub, 0)) as delivery_rub,
            sum(coalesce(rebill_logistic_cost, 0)) as rebill_logistic_cost,
            sum(coalesce(storage_fee, 0)) as storage_fee,
            sum(coalesce(acceptance, 0)) as acceptance,
            sum(coalesce(penalty, 0)) as penalty,
            sum(coalesce(deduction, 0)) as deduction,
            sum(coalesce(additional_payment, 0)) as additional_payment,
            max(operation_date_source) as operation_date_source
        from fact_finance_realization_line
        where operation_date >= :trend_current_from and operation_date <= :report_date and nm_id in :nm_ids
        group by operation_date, nm_id
        order by nm_id asc, operation_date asc
        """
    ).bindparams(bindparam("nm_ids", expanding=True))
    rows = _execute_mappings(session, sql, {"trend_current_from": trend_current_from, "report_date": report_date, "nm_ids": list(nm_ids)}, query_counter, "logistics_context")
    by_nm: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_nm[int(row["nm_id"])].append(row)

    result: list[dict[str, Any]] = []
    metric_keys = ("delivery_rub", "rebill_logistic_cost", "storage_fee", "acceptance", "penalty", "deduction", "additional_payment")
    for nm_id in nm_ids:
        nm_rows = by_nm.get(int(nm_id), [])
        row_by_date = {row["operation_date"]: row for row in nm_rows}
        current = row_by_date.get(report_date, {})
        previous = row_by_date.get(compare_date, {})
        current_total = sum(_to_decimal(current.get(key)) or Decimal("0") for key in metric_keys)
        previous_total = sum(_to_decimal(previous.get(key)) or Decimal("0") for key in metric_keys)
        result.append({
            "nm_id": int(nm_id),
            "context_date": report_date,
            "delivery_rub": _to_decimal(current.get("delivery_rub")),
            "rebill_logistic_cost": _to_decimal(current.get("rebill_logistic_cost")),
            "storage_fee": _to_decimal(current.get("storage_fee")),
            "acceptance": _to_decimal(current.get("acceptance")),
            "penalty": _to_decimal(current.get("penalty")),
            "deduction": _to_decimal(current.get("deduction")),
            "additional_payment": _to_decimal(current.get("additional_payment")),
            "total_logistics_cost": current_total,
            "previous_total_logistics_cost": previous_total,
            "total_logistics_delta_day": current_total - previous_total,
            "operation_date_source": current.get("operation_date_source") or "missing",
            "source_status": "PARTIAL",
            "source_note": FINANCE_STATUS_NOTE,
            "trend_7d": [{"date": row.get("operation_date"), "total_logistics_cost": sum(_to_decimal(row.get(key)) or Decimal("0") for key in metric_keys)} for row in nm_rows],
        })
    return result


def fetch_warehouse_context(
    session: Session,
    *,
    report_date: date,
    trend_current_from: date,
    nm_ids: Sequence[int],
    top_n: int,
    query_counter: dict[str, Any],
) -> list[dict[str, Any]]:
    if not nm_ids:
        return []
    sql = text(
        """
        with warehouse_day as (
            select snapshot_date, nm_id, warehouse_id, warehouse_name, sum(coalesce(stock_qty, 0)) as stock_qty
            from fact_stock_warehouse_snapshot
            where snapshot_date = :report_date and nm_id in :nm_ids
            group by snapshot_date, nm_id, warehouse_id, warehouse_name
        ),
        totals as (
            select nm_id, sum(stock_qty) as total_stock_qty
            from warehouse_day
            group by nm_id
        ),
        demand as (
            select nm_id, avg(coalesce(order_count, 0)) as avg_orders_7d, max(supplier_article) as supplier_article, max(title) as title
            from mart_total_report
            where report_date >= :trend_current_from and report_date <= :report_date and nm_id in :nm_ids
            group by nm_id
        )
        select
            w.snapshot_date,
            w.nm_id,
            d.supplier_article,
            d.title,
            w.warehouse_name,
            w.stock_qty,
            t.total_stock_qty,
            d.avg_orders_7d,
            case when t.total_stock_qty > 0 then w.stock_qty / nullif(t.total_stock_qty, 0) end as stock_share,
            case when d.avg_orders_7d > 0 then w.stock_qty / nullif(d.avg_orders_7d, 0) end as days_of_supply
        from warehouse_day w
        join totals t on t.nm_id = w.nm_id
        left join demand d on d.nm_id = w.nm_id
        order by w.nm_id asc, w.stock_qty desc, w.warehouse_name asc
        """
    ).bindparams(bindparam("nm_ids", expanding=True))
    rows = _execute_mappings(session, sql, {"report_date": report_date, "trend_current_from": trend_current_from, "nm_ids": list(nm_ids)}, query_counter, "warehouse_context")

    ranked: list[dict[str, Any]] = []
    for row in rows:
        stock_qty = _to_decimal(row.get("stock_qty")) or Decimal("0")
        days_of_supply = _to_decimal(row.get("days_of_supply"))
        stock_share = _to_decimal(row.get("stock_share"))
        if stock_qty <= 0:
            risk_type = "OUT_OF_STOCK"
            severity = 3
        elif days_of_supply is not None and days_of_supply <= LOW_STOCK_DAYS:
            risk_type = "LOW_STOCK"
            severity = 2
        elif days_of_supply is not None and days_of_supply >= HIGH_STOCK_DAYS:
            risk_type = "OVERSTOCK"
            severity = 1
        else:
            risk_type = "NORMAL"
            severity = 0
        if severity == 0 and (stock_share is None or stock_share < Decimal("0.25")):
            continue
        ranked.append({
            "report_date": row.get("snapshot_date"),
            "nm_id": row.get("nm_id"),
            "supplier_article": row.get("supplier_article"),
            "title": row.get("title"),
            "warehouse_name": row.get("warehouse_name"),
            "stock_qty": stock_qty,
            "total_stock_qty": _to_decimal(row.get("total_stock_qty")),
            "stock_share": stock_share,
            "avg_orders_7d_article": _to_decimal(row.get("avg_orders_7d")),
            "days_of_supply_estimate": days_of_supply,
            "risk_type": risk_type,
            "demand_scope": "article_total_7d_average",
            "note": "Demand is article-level 7d average; warehouse-specific sales are not available.",
            "severity": severity,
        })
    ranked.sort(key=lambda item: (-int(item["severity"]), -(item.get("stock_share") or Decimal("0")), item.get("warehouse_name") or ""))
    limit = max(top_n * max(len(nm_ids), 1), top_n)
    return [{key: value for key, value in row.items() if key != "severity"} for row in ranked[:limit]]


def fetch_campaign_context(
    session: Session,
    *,
    report_date: date,
    compare_date: date,
    trend_current_from: date,
    nm_ids: Sequence[int],
    top_n: int,
    query_counter: dict[str, Any],
) -> list[dict[str, Any]]:
    if not nm_ids:
        return []
    sql = text(
        """
        select
            date,
            nm_id,
            advert_id,
            max(campaign_name) as campaign_name,
            max(row_type) as row_type,
            sum(coalesce(ad_spend, 0)) as ad_spend,
            sum(coalesce(ad_views, 0)) as ad_views,
            sum(coalesce(ad_clicks, 0)) as ad_clicks,
            sum(coalesce(ad_atbs, 0)) as ad_atbs,
            sum(coalesce(ad_orders, 0)) as ad_orders,
            sum(coalesce(ad_revenue, 0)) as ad_revenue
        from fact_ad_campaign_nm_day
        where date >= :trend_current_from and date <= :report_date and nm_id in :nm_ids
        group by date, nm_id, advert_id
        order by nm_id asc, advert_id asc, date asc
        """
    ).bindparams(bindparam("nm_ids", expanding=True))
    rows = _execute_mappings(session, sql, {"trend_current_from": trend_current_from, "report_date": report_date, "nm_ids": list(nm_ids)}, query_counter, "campaign_context")
    article_spend_current: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        nm_id = int(row["nm_id"])
        if row.get("date") == report_date:
            article_spend_current[nm_id] += _to_decimal(row.get("ad_spend")) or Decimal("0")
        grouped[(nm_id, int(row["advert_id"]))].append(row)

    result: list[dict[str, Any]] = []
    for (nm_id, advert_id), group_rows in grouped.items():
        row_by_date = {row["date"]: row for row in group_rows}
        current = row_by_date.get(report_date, {})
        previous = row_by_date.get(compare_date, {})
        spend_current = _to_decimal(current.get("ad_spend")) or Decimal("0")
        spend_previous = _to_decimal(previous.get("ad_spend")) or Decimal("0")
        orders_current = _to_decimal(current.get("ad_orders")) or Decimal("0")
        revenue_current = _to_decimal(current.get("ad_revenue")) or Decimal("0")
        clicks_current = _to_decimal(current.get("ad_clicks")) or Decimal("0")
        views_current = _to_decimal(current.get("ad_views")) or Decimal("0")
        result.append({
            "report_date": report_date,
            "nm_id": nm_id,
            "advert_id": advert_id,
            "campaign_name": current.get("campaign_name") or next((row.get("campaign_name") for row in reversed(group_rows) if row.get("campaign_name")), None),
            "row_type": current.get("row_type") or next((row.get("row_type") for row in reversed(group_rows) if row.get("row_type")), None),
            "ad_spend": spend_current,
            "ad_views": views_current,
            "ad_clicks": clicks_current,
            "ad_atbs": _to_decimal(current.get("ad_atbs")) or Decimal("0"),
            "ad_orders": orders_current,
            "cpc": (spend_current / clicks_current) if clicks_current > 0 else None,
            "cpm": (spend_current / views_current * Decimal("1000")) if views_current > 0 else None,
            "cpo": (spend_current / orders_current) if orders_current > 0 else None,
            "drr": (spend_current / revenue_current * Decimal("100")) if revenue_current > 0 else None,
            "spend_delta_day": spend_current - spend_previous,
            "share_of_article_spend": (spend_current / article_spend_current[nm_id] * Decimal("100")) if article_spend_current[nm_id] > 0 else None,
            "trend_7d": _trend_points(group_rows, date_key="date", metric_keys=("ad_spend", "ad_orders", "ad_clicks", "ad_atbs")),
        })
    result.sort(key=lambda item: (-(item.get("ad_spend") or Decimal("0")), -abs(item.get("spend_delta_day") or Decimal("0")), item.get("advert_id") or 0))
    return result[:top_n]


def fetch_search_query_context(
    session: Session,
    *,
    report_date: date,
    compare_date: date,
    trend_current_from: date,
    nm_ids: Sequence[int],
    top_n: int,
    query_counter: dict[str, Any],
) -> list[dict[str, Any]]:
    if not nm_ids:
        return []
    sql = text(
        """
        with daily_base as (
            select
                date,
                nm_id,
                search_query,
                max(supplier_article) as supplier_article,
                max(title) as title,
                avg(avg_position) filter (where avg_position is not null) as avg_position,
                avg(avg_position_prev) filter (where avg_position_prev is not null) as avg_position_prev,
                avg(visibility) filter (where visibility is not null) as visibility,
                avg(visibility_prev) filter (where visibility_prev is not null) as visibility_prev,
                sum(coalesce(search_clicks, 0)) as search_clicks,
                sum(coalesce(search_cart, 0)) as search_cart,
                sum(coalesce(search_orders, 0)) as search_orders,
                sum(coalesce(search_clicks_prev, 0)) as search_clicks_prev,
                sum(coalesce(search_cart_prev, 0)) as search_cart_prev,
                sum(coalesce(search_orders_prev, 0)) as search_orders_prev
            from fact_search_query_metric
            where date >= :trend_current_from and date <= :report_date and nm_id in :nm_ids
            group by date, nm_id, search_query
        ),
        current_day as (
            select *
            from daily_base
            where date = :report_date
        ),
        previous_day as (
            select *
            from daily_base
            where date = :compare_date
        ),
        ranked_candidates as (
            select
                ranked.nm_id,
                ranked.search_query
            from (
                select
                    c.nm_id,
                    c.search_query,
                    case
                        when c.avg_position is not null and coalesce(c.avg_position_prev, p.avg_position) is not null
                            then c.avg_position - coalesce(c.avg_position_prev, p.avg_position)
                    end as position_delta_day,
                    c.search_clicks - coalesce(c.search_clicks_prev, p.search_clicks, 0) as clicks_delta_day,
                    c.search_orders - coalesce(c.search_orders_prev, p.search_orders, 0) as orders_delta_day,
                    case
                        when c.avg_position is not null
                             and coalesce(c.avg_position_prev, p.avg_position) is not null
                             and c.avg_position - coalesce(c.avg_position_prev, p.avg_position) <= 0
                             and (
                                 c.search_clicks - coalesce(c.search_clicks_prev, p.search_clicks, 0) > 0
                                 or c.search_orders - coalesce(c.search_orders_prev, p.search_orders, 0) > 0
                             )
                            then 1
                        else 0
                    end as positive_rank_flag
                from current_day c
                left join previous_day p
                    on p.nm_id = c.nm_id
                   and p.search_query = c.search_query
            ) ranked
            order by
                positive_rank_flag asc,
                position_delta_day desc nulls last,
                abs(orders_delta_day) desc,
                abs(clicks_delta_day) desc,
                nm_id asc,
                search_query asc
            limit :top_n
        )
        select
            d.date,
            d.nm_id,
            d.search_query,
            d.supplier_article,
            d.title,
            d.avg_position,
            d.avg_position_prev,
            d.visibility,
            d.visibility_prev,
            d.search_clicks,
            d.search_cart,
            d.search_orders,
            d.search_clicks_prev,
            d.search_cart_prev,
            d.search_orders_prev
        from daily_base d
        join ranked_candidates r
          on r.nm_id = d.nm_id
         and r.search_query = d.search_query
        order by d.nm_id asc, d.search_query asc, d.date asc
        """
    ).bindparams(bindparam("nm_ids", expanding=True))
    rows = _execute_mappings(
        session,
        sql,
        {
            "trend_current_from": trend_current_from,
            "report_date": report_date,
            "compare_date": compare_date,
            "nm_ids": list(nm_ids),
            "top_n": top_n,
        },
        query_counter,
        "search_query_context",
    )
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["nm_id"]), str(row["search_query"]))].append(row)

    ranked: list[dict[str, Any]] = []
    for (nm_id, search_query), group_rows in grouped.items():
        row_by_date = {row["date"]: row for row in group_rows}
        current = row_by_date.get(report_date)
        if not current:
            continue
        previous = row_by_date.get(compare_date, {})
        current_position = _to_decimal(current.get("avg_position"))
        previous_position = _to_decimal(current.get("avg_position_prev")) or _to_decimal(previous.get("avg_position"))
        current_clicks = _to_decimal(current.get("search_clicks")) or Decimal("0")
        previous_clicks = _to_decimal(current.get("search_clicks_prev")) or _to_decimal(previous.get("search_clicks")) or Decimal("0")
        current_orders = _to_decimal(current.get("search_orders")) or Decimal("0")
        previous_orders = _to_decimal(current.get("search_orders_prev")) or _to_decimal(previous.get("search_orders")) or Decimal("0")
        position_delta = (current_position - previous_position) if current_position is not None and previous_position is not None else None
        clicks_delta = current_clicks - previous_clicks
        orders_delta = current_orders - previous_orders
        signal_kind = "negative"
        if position_delta is not None and position_delta <= 0 and (clicks_delta > 0 or orders_delta > 0):
            signal_kind = "positive"
        ranked.append({
            "report_date": report_date,
            "nm_id": nm_id,
            "search_query": search_query,
            "supplier_article": current.get("supplier_article"),
            "title": current.get("title"),
            "avg_position": current_position,
            "previous_avg_position": previous_position,
            "position_delta_day": position_delta,
            "visibility": _to_decimal(current.get("visibility")),
            "previous_visibility": _to_decimal(current.get("visibility_prev")) or _to_decimal(previous.get("visibility")),
            "search_clicks": current_clicks,
            "search_cart": _to_decimal(current.get("search_cart")),
            "search_orders": current_orders,
            "clicks_delta_day": clicks_delta,
            "orders_delta_day": orders_delta,
            "signal_kind": signal_kind,
            "trend_7d": _trend_points(group_rows, date_key="date", metric_keys=("avg_position", "visibility", "search_clicks", "search_cart", "search_orders")),
        })
    ranked.sort(key=lambda item: (0 if item.get("signal_kind") == "negative" else 1, -(item.get("position_delta_day") or Decimal("0")), abs(item.get("orders_delta_day") or Decimal("0")), abs(item.get("clicks_delta_day") or Decimal("0"))))
    return ranked[:top_n]


def fetch_entry_point_context(session: Session, *, report_date: date, top_n: int, nm_ids: Sequence[int], query_counter: dict[str, Any]) -> dict[str, Any]:
    freshness_sql = text("select max(date) as max_date from fact_entry_point_day")
    freshness_rows = _execute_mappings(session, freshness_sql, {}, query_counter, "entry_point_context_freshness")
    max_date = freshness_rows[0].get("max_date") if freshness_rows else None
    if max_date is None or not nm_ids:
        return {"rows": [], "context_date": None, "status": "MISSING"}
    context_date = min(max_date, report_date)
    compare_date = context_date - timedelta(days=1)
    trend_from = context_date - timedelta(days=6)
    sql = text(
        """
        select
            date,
            nm_id,
            section,
            entry_point,
            max(supplier_article) as supplier_article,
            max(title) as title,
            sum(coalesce(card_clicks, 0)) as card_clicks,
            sum(coalesce(cart_count, 0)) as cart_count,
            sum(coalesce(order_count, 0)) as order_count,
            sum(coalesce(revenue, 0)) as revenue,
            avg(order_conversion) filter (where order_conversion is not null) as order_conversion
        from fact_entry_point_day
        where date >= :trend_from and date <= :context_date and nm_id in :nm_ids
        group by date, nm_id, section, entry_point
        order by nm_id asc, section asc, entry_point asc, date asc
        """
    ).bindparams(bindparam("nm_ids", expanding=True))
    rows = _execute_mappings(session, sql, {"trend_from": trend_from, "context_date": context_date, "nm_ids": list(nm_ids)}, query_counter, "entry_point_context")
    grouped: dict[tuple[int, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["nm_id"]), str(row["section"]), str(row["entry_point"]))].append(row)

    ranked: list[dict[str, Any]] = []
    for (nm_id, section, entry_point), group_rows in grouped.items():
        row_by_date = {row["date"]: row for row in group_rows}
        current = row_by_date.get(context_date)
        if not current:
            continue
        previous = row_by_date.get(compare_date, {})
        current_clicks = _to_decimal(current.get("card_clicks")) or Decimal("0")
        current_orders = _to_decimal(current.get("order_count")) or Decimal("0")
        previous_clicks = _to_decimal(previous.get("card_clicks")) or Decimal("0")
        previous_orders = _to_decimal(previous.get("order_count")) or Decimal("0")
        ranked.append({
            "context_date": context_date,
            "report_date": report_date,
            "nm_id": nm_id,
            "section": section,
            "entry_point": entry_point,
            "supplier_article": current.get("supplier_article"),
            "title": current.get("title"),
            "card_clicks": current_clicks,
            "cart_count": _to_decimal(current.get("cart_count")),
            "order_count": current_orders,
            "revenue": _to_decimal(current.get("revenue")),
            "order_conversion": _to_decimal(current.get("order_conversion")),
            "clicks_delta_day": current_clicks - previous_clicks,
            "orders_delta_day": current_orders - previous_orders,
            "trend_7d": _trend_points(group_rows, date_key="date", metric_keys=("card_clicks", "cart_count", "order_count", "revenue")),
            "source_status": "OK" if context_date == report_date else "PARTIAL",
        })
    ranked.sort(key=lambda item: (-(item.get("order_count") or Decimal("0")), -(item.get("card_clicks") or Decimal("0")), item.get("entry_point") or ""))
    return {"rows": ranked[:top_n], "context_date": context_date, "status": "OK" if context_date == report_date else "PARTIAL"}


def build_extended_context(
    session: Session,
    *,
    report_date: date,
    compare_date: date,
    trend_current_from: date,
    top_n: int,
    nm_ids: Sequence[int],
    query_counter: dict[str, Any],
) -> dict[str, Any]:
    resolved_nm_ids = _unique_nm_ids(nm_ids)
    additional_freshness = fetch_additional_source_freshness(session, query_counter)
    if not resolved_nm_ids:
        return {
            "additional_source_freshness": additional_freshness,
            "article_context": [],
            "warehouse_context": [],
            "campaign_context": [],
            "search_query_context": [],
            "entry_point_context": [],
            "price_context": [],
            "logistics_context": [],
            "data_gaps": [
                {"kind": "context_scope", "status": "MISSING", "message": "No candidate nm_id rows were selected for extended context."},
                {"kind": "buyout_semantics", "status": "PARTIAL", "message": "Buyout metrics remain excluded from causal reasoning until source semantics are confirmed."},
            ],
        }

    history_from = report_date - timedelta(days=14)
    article_rows = fetch_article_context(session, report_date=report_date, history_from=history_from, nm_ids=resolved_nm_ids, query_counter=query_counter)
    price_context = fetch_price_context(session, report_date=report_date, compare_date=compare_date, trend_current_from=trend_current_from, nm_ids=resolved_nm_ids, query_counter=query_counter)
    logistics_context = fetch_logistics_context(session, report_date=report_date, compare_date=compare_date, trend_current_from=trend_current_from, nm_ids=resolved_nm_ids, query_counter=query_counter)
    warehouse_context = fetch_warehouse_context(session, report_date=report_date, trend_current_from=trend_current_from, nm_ids=resolved_nm_ids, top_n=top_n, query_counter=query_counter)
    campaign_context = fetch_campaign_context(session, report_date=report_date, compare_date=compare_date, trend_current_from=trend_current_from, nm_ids=resolved_nm_ids, top_n=top_n, query_counter=query_counter)
    search_query_context = fetch_search_query_context(session, report_date=report_date, compare_date=compare_date, trend_current_from=trend_current_from, nm_ids=resolved_nm_ids, top_n=top_n, query_counter=query_counter)
    entry_point_payload = fetch_entry_point_context(session, report_date=report_date, top_n=top_n, nm_ids=resolved_nm_ids, query_counter=query_counter)
    price_by_nm = {int(row["nm_id"]): row for row in price_context}
    logistics_by_nm = {int(row["nm_id"]): row for row in logistics_context}

    article_context: list[dict[str, Any]] = []
    for row in article_rows:
        nm_id = int(row["nm_id"])
        stock_snapshot_date = row.get("stock_snapshot_date")
        stock_status = "OK" if stock_snapshot_date == report_date and row.get("warehouse_stock_qty") is not None else ("PARTIAL" if stock_snapshot_date else "MISSING")
        price_row = price_by_nm.get(nm_id, {})
        logistics_row = logistics_by_nm.get(nm_id, {})
        article_context.append({
            "report_date": report_date,
            "nm_id": nm_id,
            "supplier_article": row.get("supplier_article"),
            "title": row.get("title"),
            "subject": row.get("subject"),
            "brand": row.get("brand"),
            "impressions": row.get("impressions"),
            "card_clicks": row.get("card_clicks"),
            "cart_count": row.get("cart_count"),
            "order_count": row.get("order_count"),
            "order_sum": row.get("order_sum"),
            "ad_spend_total": row.get("ad_spend_total"),
            "search_avg_position": row.get("search_avg_position"),
            "search_visibility": row.get("search_visibility"),
            "buyer_visible_price": price_row.get("buyer_visible_price"),
            "price_delta_day": price_row.get("price_delta_day"),
            "wallet_price": price_row.get("wallet_price"),
            "price_status": price_row.get("source_status", "MISSING"),
            "stock_qty_same_day": _to_decimal(row.get("warehouse_stock_qty")),
            "warehouses_with_stock": row.get("warehouses_with_stock"),
            "warehouses_zero_stock": row.get("warehouses_zero_stock"),
            "stock_status": stock_status,
            "stock_snapshot_date": stock_snapshot_date,
            "total_logistics_cost": logistics_row.get("total_logistics_cost"),
            "logistics_delta_day": logistics_row.get("total_logistics_delta_day"),
            "finance_status": logistics_row.get("source_status", "MISSING"),
            "buyout_count": row.get("buyout_count"),
            "buyout_sum": row.get("buyout_sum"),
            "buyout_status": "PARTIAL",
            "trend_14d": row.get("trend_14d") or [],
        })

    data_gaps: list[dict[str, Any]] = [
        {"kind": "buyout_semantics", "status": "PARTIAL", "message": "buyout_count and buyout_sum remain excluded from causal reasoning until source semantics are confirmed."},
        {"kind": "finance_semantics", "status": "PARTIAL", "message": FINANCE_STATUS_NOTE},
    ]
    missing_stock = [row for row in article_context if row.get("stock_status") != "OK"]
    if missing_stock:
        data_gaps.append({"kind": "same_day_stock", "status": "PARTIAL", "affected_nm_ids": [row.get("nm_id") for row in missing_stock], "message": "Same-day stock snapshot is missing for part of the selected articles; future stock fallback is not used."})
    missing_price = [row for row in price_context if row.get("source_status") != "OK"]
    if missing_price:
        data_gaps.append({"kind": "site_price_snapshot", "status": "PARTIAL", "affected_nm_ids": [row.get("nm_id") for row in missing_price], "message": "WB site price snapshot is missing or non-success for part of the selected articles."})
    seller_ambiguous = [row for row in price_context if row.get("seller_price_status") == "PARTIAL"]
    if seller_ambiguous:
        data_gaps.append({"kind": "seller_price_rollup", "status": "PARTIAL", "affected_nm_ids": [row.get("nm_id") for row in seller_ambiguous], "message": SELLER_PRICE_ROLLUP_RULE})
    if entry_point_payload.get("status") == "PARTIAL":
        data_gaps.append({"kind": "entry_point_freshness", "status": "PARTIAL", "context_date": entry_point_payload.get("context_date"), "message": "Entry-point block uses its own latest available date and is not treated as same-day data for the main report."})

    return {
        "additional_source_freshness": additional_freshness,
        "article_context": article_context,
        "warehouse_context": warehouse_context,
        "campaign_context": campaign_context,
        "search_query_context": search_query_context,
        "entry_point_context": entry_point_payload.get("rows", []),
        "price_context": price_context,
        "logistics_context": logistics_context,
        "data_gaps": data_gaps,
    }

