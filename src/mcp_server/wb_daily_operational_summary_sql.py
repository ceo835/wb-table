from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


CORE_SOURCE_QUERIES: tuple[tuple[str, str], ...] = (
    ("mart_total_report", "select max(report_date) as max_date from mart_total_report"),
    ("fact_funnel_day", "select max(date) as max_date from fact_funnel_day"),
    ("fact_ad_cost_day", "select max(date) as max_date from fact_ad_cost_day"),
    ("fact_ad_campaign_nm_day", "select max(date) as max_date from fact_ad_campaign_nm_day"),
    ("fact_stock_warehouse_snapshot", "select max(snapshot_date) as max_date from fact_stock_warehouse_snapshot"),
    ("fact_search_query_metric", "select max(date) as max_date from fact_search_query_metric"),
)


def _increment(query_counter: dict[str, int]) -> None:
    query_counter["count"] = int(query_counter.get("count") or 0) + 1



def fetch_core_source_freshness(session: Session, query_counter: dict[str, int]) -> list[dict[str, Any]]:
    union_sql = " union all ".join(
        f"select '{source}' as source_name, ({sql}) as max_date" for source, sql in CORE_SOURCE_QUERIES
    )
    _increment(query_counter)
    return [dict(row) for row in session.execute(text(union_sql)).mappings().all()]



def fetch_mart_daily_overview(
    session: Session,
    report_date: date,
    compare_date: date,
    query_counter: dict[str, int],
) -> list[dict[str, Any]]:
    sql = text(
        """
        select
            report_date,
            count(*) as rows_count,
            count(distinct nm_id) as nm_count,
            sum(impressions) as impressions,
            sum(card_clicks) as card_clicks,
            case when sum(impressions) > 0 then sum(card_clicks) / nullif(sum(impressions), 0) * 100 end as ctr,
            sum(cart_count) as cart_count,
            case when sum(card_clicks) > 0 then sum(cart_count) / nullif(sum(card_clicks), 0) * 100 end as add_to_cart_conversion,
            sum(order_count) as order_count,
            case when sum(cart_count) > 0 then sum(order_count) / nullif(sum(cart_count), 0) * 100 end as cart_to_order_conversion,
            sum(order_sum) as order_sum,
            case when sum(order_count) > 0 then sum(order_sum) / nullif(sum(order_count), 0) end as avg_check,
            sum(buyout_count) as buyout_count,
            sum(buyout_sum) as buyout_sum,
            sum(ad_cost_writeoff_total) as ad_spend,
            sum(ad_views_total) as ad_views,
            sum(ad_clicks_total) as ad_clicks,
            sum(ad_atbs_total) as ad_atbs,
            sum(ad_orders_total) as ad_orders,
            case when sum(order_sum) > 0 then sum(ad_cost_writeoff_total) / nullif(sum(order_sum), 0) * 100 end as drr,
            case when sum(ad_clicks_total) > 0 then sum(ad_cost_writeoff_total) / nullif(sum(ad_clicks_total), 0) end as cpc,
            case when sum(ad_views_total) > 0 then sum(ad_cost_writeoff_total) / nullif(sum(ad_views_total), 0) * 1000 end as cpm,
            case when sum(ad_orders_total) > 0 then sum(ad_cost_writeoff_total) / nullif(sum(ad_orders_total), 0) end as cpo,
            case when sum(ad_atbs_total) > 0 then sum(ad_cost_writeoff_total) / nullif(sum(ad_atbs_total), 0) end as cost_per_cart,
            avg(search_avg_position) filter (where search_avg_position is not null) as search_avg_position,
            avg(search_visibility) filter (where search_visibility is not null) as search_visibility,
            sum(search_clicks) as search_clicks,
            sum(search_cart) as search_cart,
            sum(search_orders) as search_orders
        from mart_total_report
        where report_date >= :history_from and report_date <= :report_date
        group by report_date
        order by report_date asc
        """
    )
    _increment(query_counter)
    history_from = report_date - timedelta(days=14)
    return [dict(row) for row in session.execute(sql, {"report_date": report_date, "compare_date": compare_date, "history_from": history_from}).mappings().all()]



def fetch_mart_window_overview(
    session: Session,
    trend_current_from: date,
    trend_current_to: date,
    trend_previous_from: date,
    trend_previous_to: date,
    query_counter: dict[str, int],
) -> list[dict[str, Any]]:
    sql = text(
        """
        with scoped as (
            select
                case
                    when report_date >= :trend_current_from and report_date <= :trend_current_to then 'current'
                    when report_date >= :trend_previous_from and report_date <= :trend_previous_to then 'previous'
                    else null
                end as bucket,
                *
            from mart_total_report
            where report_date >= :trend_previous_from and report_date <= :trend_current_to
        )
        select
            bucket,
            count(distinct report_date) as days_count,
            count(distinct nm_id) as nm_count,
            sum(impressions) as impressions,
            sum(card_clicks) as card_clicks,
            case when sum(impressions) > 0 then sum(card_clicks) / nullif(sum(impressions), 0) * 100 end as ctr,
            sum(cart_count) as cart_count,
            case when sum(card_clicks) > 0 then sum(cart_count) / nullif(sum(card_clicks), 0) * 100 end as add_to_cart_conversion,
            sum(order_count) as order_count,
            case when sum(cart_count) > 0 then sum(order_count) / nullif(sum(cart_count), 0) * 100 end as cart_to_order_conversion,
            sum(order_sum) as order_sum,
            case when sum(order_count) > 0 then sum(order_sum) / nullif(sum(order_count), 0) end as avg_check,
            sum(buyout_count) as buyout_count,
            sum(buyout_sum) as buyout_sum,
            sum(ad_cost_writeoff_total) as ad_spend,
            sum(ad_views_total) as ad_views,
            sum(ad_clicks_total) as ad_clicks,
            sum(ad_atbs_total) as ad_atbs,
            sum(ad_orders_total) as ad_orders,
            case when sum(order_sum) > 0 then sum(ad_cost_writeoff_total) / nullif(sum(order_sum), 0) * 100 end as drr,
            case when sum(ad_clicks_total) > 0 then sum(ad_cost_writeoff_total) / nullif(sum(ad_clicks_total), 0) end as cpc,
            case when sum(ad_views_total) > 0 then sum(ad_cost_writeoff_total) / nullif(sum(ad_views_total), 0) * 1000 end as cpm,
            case when sum(ad_orders_total) > 0 then sum(ad_cost_writeoff_total) / nullif(sum(ad_orders_total), 0) end as cpo,
            case when sum(ad_atbs_total) > 0 then sum(ad_cost_writeoff_total) / nullif(sum(ad_atbs_total), 0) end as cost_per_cart,
            avg(search_avg_position) filter (where search_avg_position is not null) as search_avg_position,
            avg(search_visibility) filter (where search_visibility is not null) as search_visibility,
            sum(search_clicks) as search_clicks,
            sum(search_cart) as search_cart,
            sum(search_orders) as search_orders
        from scoped
        where bucket is not null
        group by bucket
        order by bucket asc
        """
    )
    _increment(query_counter)
    return [dict(row) for row in session.execute(sql, {
        "trend_current_from": trend_current_from,
        "trend_current_to": trend_current_to,
        "trend_previous_from": trend_previous_from,
        "trend_previous_to": trend_previous_to,
    }).mappings().all()]



def fetch_assortment_changes(
    session: Session,
    report_date: date,
    compare_date: date,
    query_counter: dict[str, int],
) -> list[dict[str, Any]]:
    sql = text(
        """
        with current_day as (
            select
                nm_id,
                max(supplier_article) as supplier_article,
                max(title) as title,
                sum(order_sum) as order_sum,
                sum(order_count) as order_count,
                sum(ad_cost_writeoff_total) as ad_spend,
                sum(current_stock_qty) as current_stock_qty
            from mart_total_report
            where report_date = :report_date
            group by nm_id
        ),
        previous_day as (
            select
                nm_id,
                max(supplier_article) as supplier_article,
                max(title) as title,
                sum(order_sum) as order_sum,
                sum(order_count) as order_count,
                sum(ad_cost_writeoff_total) as ad_spend,
                sum(current_stock_qty) as current_stock_qty
            from mart_total_report
            where report_date = :compare_date
            group by nm_id
        )
        select
            coalesce(c.nm_id, p.nm_id) as nm_id,
            coalesce(c.supplier_article, p.supplier_article) as supplier_article,
            coalesce(c.title, p.title) as title,
            coalesce(c.order_sum, 0) as order_sum_current,
            coalesce(p.order_sum, 0) as order_sum_previous,
            coalesce(c.order_sum, 0) - coalesce(p.order_sum, 0) as order_sum_delta,
            coalesce(c.order_count, 0) as order_count_current,
            coalesce(p.order_count, 0) as order_count_previous,
            coalesce(c.ad_spend, 0) as ad_spend_current,
            coalesce(c.current_stock_qty, 0) as current_stock_qty
        from current_day c
        full outer join previous_day p on p.nm_id = c.nm_id
        """
    )
    _increment(query_counter)
    history_from = report_date - timedelta(days=14)
    return [dict(row) for row in session.execute(sql, {"report_date": report_date, "compare_date": compare_date, "history_from": history_from}).mappings().all()]



def fetch_problem_campaigns(
    session: Session,
    report_date: date,
    compare_date: date,
    query_counter: dict[str, int],
) -> list[dict[str, Any]]:
    sql = text(
        """
        select
            advert_id,
            max(campaign_name) as campaign_name,
            sum(case when date = :report_date then coalesce(ad_spend, 0) else 0 end) as spend_current,
            sum(case when date = :compare_date then coalesce(ad_spend, 0) else 0 end) as spend_previous,
            sum(case when date = :report_date then coalesce(ad_orders, 0) else 0 end) as orders_current,
            sum(case when date = :compare_date then coalesce(ad_orders, 0) else 0 end) as orders_previous,
            sum(case when date = :report_date then coalesce(ad_atbs, 0) else 0 end) as carts_current,
            sum(case when date = :report_date then coalesce(ad_clicks, 0) else 0 end) as clicks_current,
            sum(case when date = :report_date then coalesce(ad_views, 0) else 0 end) as views_current,
            sum(case when date = :report_date then coalesce(ad_revenue, 0) else 0 end) as revenue_current,
            max(row_type) filter (where date = :report_date) as row_type
        from fact_ad_campaign_nm_day
        where date in (:report_date, :compare_date)
        group by advert_id
        """
    )
    _increment(query_counter)
    history_from = report_date - timedelta(days=14)
    return [dict(row) for row in session.execute(sql, {"report_date": report_date, "compare_date": compare_date, "history_from": history_from}).mappings().all()]



def fetch_stock_risks(
    session: Session,
    report_date: date,
    trend_current_from: date,
    query_counter: dict[str, int],
) -> list[dict[str, Any]]:
    sql = text(
        """
        with sales_7d as (
            select
                nm_id,
                max(supplier_article) as supplier_article,
                max(title) as title,
                avg(coalesce(order_count, 0)) as avg_orders_7d,
                sum(coalesce(order_count, 0)) as orders_7d
            from mart_total_report
            where report_date >= :trend_current_from and report_date <= :report_date
            group by nm_id
        ),
        stock_day as (
            select
                nm_id,
                warehouse_name,
                sum(coalesce(stock_qty, 0)) as stock_qty
            from fact_stock_warehouse_snapshot
            where snapshot_date = :report_date
            group by nm_id, warehouse_name
        )
        select
            s.nm_id,
            s.supplier_article,
            s.title,
            d.warehouse_name,
            d.stock_qty,
            s.avg_orders_7d,
            s.orders_7d,
            case when s.avg_orders_7d > 0 then d.stock_qty / nullif(s.avg_orders_7d, 0) end as days_of_supply
        from stock_day d
        join sales_7d s on s.nm_id = d.nm_id
        where s.orders_7d > 0
        """
    )
    _increment(query_counter)
    return [dict(row) for row in session.execute(sql, {
        "report_date": report_date,
        "trend_current_from": trend_current_from,
    }).mappings().all()]



def fetch_search_movers(
    session: Session,
    report_date: date,
    compare_date: date,
    query_counter: dict[str, int],
) -> list[dict[str, Any]]:
    sql = text(
        """
        with current_day as (
            select
                nm_id,
                max(supplier_article) as supplier_article,
                max(title) as title,
                avg(avg_position) filter (where avg_position is not null) as avg_position,
                avg(visibility) filter (where visibility is not null) as visibility,
                sum(coalesce(search_clicks, 0)) as search_clicks,
                sum(coalesce(search_orders, 0)) as search_orders
            from fact_search_query_metric
            where date = :report_date
            group by nm_id
        ),
        previous_day as (
            select
                nm_id,
                avg(avg_position) filter (where avg_position is not null) as avg_position,
                avg(visibility) filter (where visibility is not null) as visibility,
                sum(coalesce(search_clicks, 0)) as search_clicks,
                sum(coalesce(search_orders, 0)) as search_orders
            from fact_search_query_metric
            where date = :compare_date
            group by nm_id
        )
        select
            coalesce(c.nm_id, p.nm_id) as nm_id,
            c.supplier_article,
            c.title,
            c.avg_position as avg_position_current,
            p.avg_position as avg_position_previous,
            c.visibility as visibility_current,
            p.visibility as visibility_previous,
            c.search_clicks as search_clicks_current,
            p.search_clicks as search_clicks_previous,
            c.search_orders as search_orders_current,
            p.search_orders as search_orders_previous
        from current_day c
        full outer join previous_day p on p.nm_id = c.nm_id
        """
    )
    _increment(query_counter)
    history_from = report_date - timedelta(days=14)
    return [dict(row) for row in session.execute(sql, {"report_date": report_date, "compare_date": compare_date, "history_from": history_from}).mappings().all()]



def fetch_profit_overview(
    session: Session,
    report_date: date,
    compare_date: date,
    trend_current_from: date,
    trend_current_to: date,
    trend_previous_from: date,
    trend_previous_to: date,
    query_counter: dict[str, int],
) -> dict[str, Any]:
    daily_sql = text(
        """
        select
            day,
            sum(coalesce(operating_profit, 0)) as operating_profit,
            sum(coalesce(organic_sales, 0)) as organic_sales,
            case when sum(coalesce(organic_sales, 0)) > 0 then sum(coalesce(operating_profit, 0)) / nullif(sum(coalesce(organic_sales, 0)), 0) end as profit_per_unit
        from fact_vvbromo_product_day
        where day in (:report_date, :compare_date)
        group by day
        order by day asc
        """
    )
    _increment(query_counter)
    daily_rows = [dict(row) for row in session.execute(daily_sql, {"report_date": report_date, "compare_date": compare_date}).mappings().all()]

    trend_sql = text(
        """
        select
            case
                when day >= :trend_current_from and day <= :trend_current_to then 'current'
                when day >= :trend_previous_from and day <= :trend_previous_to then 'previous'
                else null
            end as bucket,
            max(day) as max_day,
            sum(coalesce(operating_profit, 0)) as operating_profit,
            sum(coalesce(organic_sales, 0)) as organic_sales,
            case when sum(coalesce(organic_sales, 0)) > 0 then sum(coalesce(operating_profit, 0)) / nullif(sum(coalesce(organic_sales, 0)), 0) end as profit_per_unit
        from fact_vvbromo_product_day
        where day >= :trend_previous_from and day <= :trend_current_to
        group by bucket
        order by bucket asc
        """
    )
    _increment(query_counter)
    trend_rows = [dict(row) for row in session.execute(trend_sql, {
        "trend_current_from": trend_current_from,
        "trend_current_to": trend_current_to,
        "trend_previous_from": trend_previous_from,
        "trend_previous_to": trend_previous_to,
    }).mappings().all()]

    freshness_sql = text("select max(day) as max_day from fact_vvbromo_product_day")
    _increment(query_counter)
    freshness_row = session.execute(freshness_sql).mappings().one()
    return {
        "daily": daily_rows,
        "trend": trend_rows,
        "max_day": freshness_row.get("max_day"),
    }

