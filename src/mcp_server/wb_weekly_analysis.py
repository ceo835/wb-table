from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Sequence
from sqlalchemy import text
from sqlalchemy.orm import Session

def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None

def _safe_div(num: Decimal | None, denom: Decimal | None) -> Decimal | None:
    if num is None or denom in (None, Decimal("0")):
        return None
    return num / denom

def safe_sum(key: str, rows: Sequence[dict[str, Any]]) -> Decimal | None:
    vals = [row.get(key) for row in rows if row.get(key) is not None]
    if not vals:
        return None
    return sum(Decimal(str(v)) for v in vals)

def safe_avg(key: str, rows: Sequence[dict[str, Any]]) -> Decimal | None:
    vals = [row.get(key) for row in rows if row.get(key) is not None]
    if not vals:
        return None
    return sum(Decimal(str(v)) for v in vals) / len(vals)

def get_ad_attribution_cutoff(report_date: date) -> date:
    return report_date - timedelta(days=2)

def calculate_std_dev(values: list[Decimal], mean_val: Decimal) -> Decimal:
    if not values:
        return Decimal("0")
    variance = sum((v - mean_val) ** 2 for v in values) / len(values)
    return Decimal(str(math.sqrt(float(variance))))

def classify_series(dates: list[date], values: list[Decimal]) -> str:
    n = len(values)
    if n < 5:
        return "insufficient_data"
    avg_val = sum(values) / n
    if avg_val == 0:
        return "flat"

    std_dev = calculate_std_dev(values, avg_val)
    cv = std_dev / avg_val if avg_val else Decimal("0")
    if abs(cv) < Decimal("0.05"):
        return "flat"

    diffs = [values[i] - values[i - 1] for i in range(1, n)]
    days_up = sum(1 for d in diffs if d > 0)
    days_down = sum(1 for d in diffs if d < 0)

    # steady_growth
    if days_up >= n - 2 and days_down <= 1 and values[-1] > values[0]:
        # check no drop > 15% of mean
        has_big_drop = any(d < 0 and abs(d) > avg_val * Decimal("0.15") for d in diffs)
        if not has_big_drop:
            return "steady_growth"

    # steady_decline
    if days_down >= n - 2 and days_up <= 1 and values[-1] < values[0]:
        # check no growth > 15% of mean
        has_big_growth = any(d > 0 and d > avg_val * Decimal("0.15") for d in diffs)
        if not has_big_growth:
            return "steady_decline"

    # one_day_spike
    sorted_vals = sorted(values)
    median = sorted_vals[n // 2]
    max_val = max(values)
    min_val = min(values)

    if max_val > median * Decimal("2.5"):
        other_vals = [v for v in values if v != max_val]
        if other_vals:
            other_avg = sum(other_vals) / len(other_vals)
            other_std = calculate_std_dev(other_vals, other_avg)
            if other_std == 0 or (max_val - other_avg) / other_std > 3:
                # check that other days CV is < 15%
                if other_avg != 0 and (other_std / other_avg) < Decimal("0.15"):
                    return "one_day_spike"

    # one_day_drop
    if min_val < median * Decimal("0.3"):
        other_vals = [v for v in values if v != min_val]
        if other_vals:
            other_avg = sum(other_vals) / len(other_vals)
            other_std = calculate_std_dev(other_vals, other_avg)
            if other_std == 0 or (other_avg - min_val) / other_std > 3:
                if other_avg != 0 and (other_std / other_avg) < Decimal("0.15"):
                    return "one_day_drop"

    # recovery
    min_idx = values.index(min_val)
    if 0 < min_idx < n - 1:
        # decreasing before min, increasing after
        left_diffs = [values[i] - values[i - 1] for i in range(1, min_idx + 1)]
        right_diffs = [values[i] - values[i - 1] for i in range(min_idx + 1, n)]
        left_down = sum(1 for d in left_diffs if d < 0)
        right_up = sum(1 for d in right_diffs if d > 0)
        if left_down >= len(left_diffs) - 1 and right_up >= len(right_diffs) - 1:
            if values[-1] >= min_val * Decimal("1.2"):
                return "recovery"

    # volatile (sign changes >= 3)
    sign_changes = 0
    for i in range(1, len(diffs)):
        if (diffs[i] > 0 and diffs[i - 1] < 0) or (diffs[i] < 0 and diffs[i - 1] > 0):
            sign_changes += 1
    if sign_changes >= 3:
        return "volatile"

    return "volatile"

def _calc_trend_stats(dates: list[date], values: list[Decimal], change_vs_prev: Decimal | None) -> dict[str, Any]:
    if not values:
        return {"shape": "insufficient_data"}
    n = len(values)
    avg_val = sum(values) / n
    sorted_vals = sorted(values)
    median_val = sorted_vals[n // 2]
    
    diffs = [values[i] - values[i - 1] for i in range(1, n)]
    days_up = sum(1 for d in diffs if d > 0)
    days_down = sum(1 for d in diffs if d < 0)
    
    largest_daily_drop = Decimal("0")
    largest_daily_growth = Decimal("0")
    largest_drop_date = None
    largest_growth_date = None
    for i, d in enumerate(diffs):
        dt = dates[i + 1]
        if d < 0 and abs(d) > abs(largest_daily_drop):
            largest_daily_drop = d
            largest_drop_date = dt.isoformat()
        if d > 0 and d > largest_daily_growth:
            largest_daily_growth = d
            largest_growth_date = dt.isoformat()
            
    return {
        "days_up": days_up,
        "days_down": days_down,
        "first_day_value": values[0],
        "last_day_value": values[-1],
        "period_min": min(values),
        "period_max": max(values),
        "period_average": avg_val,
        "median": median_val,
        "change_current_vs_previous_week": change_vs_prev,
        "change_first_vs_last_day": values[-1] - values[0],
        "largest_daily_drop": largest_daily_drop if largest_daily_drop != 0 else None,
        "largest_daily_growth": largest_daily_growth if largest_daily_growth != 0 else None,
        "largest_drop_date": largest_drop_date,
        "largest_growth_date": largest_growth_date,
        "shape": classify_series(dates, values)
    }

def build_weekly_analysis(
    session: Session,
    *,
    window: Any,
    daily_rows: list[dict[str, Any]],
    logistics_summary: dict[str, Any],
    operating_profit_context: dict[str, Any],
    pricing_spp_context: dict[str, Any],
    query_counter: dict[str, Any],
) -> dict[str, Any]:
    current_from = window.trend_current_from
    current_to = window.trend_current_to
    previous_from = window.trend_previous_from
    previous_to = window.trend_previous_to
    report_date = window.report_date

    # 1. Separate daily rows by weeks
    curr_daily = [row for row in daily_rows if current_from <= row["report_date"] <= current_to]
    prev_daily = [row for row in daily_rows if previous_from <= row["report_date"] <= previous_to]
    
    curr_daily_by_date = {row["report_date"]: row for row in curr_daily}
    prev_daily_by_date = {row["report_date"]: row for row in prev_daily}

    # Helper for checking query count
    def _inc_queries(name: str):
        query_counter["count"] = int(query_counter.get("count") or 0) + 1
        query_counter.setdefault("timings", []).append({"query": name, "ms": 1})

    # Get ad attribution cutoff
    ad_cutoff = get_ad_attribution_cutoff(report_date)

    # 2. Completeness & DB checks
    # Profit days count from DB
    profit_check_sql = text(
        """
        select day, count(distinct nm_id) as cnt
        from fact_vvbromo_product_day
        where day >= :start and day <= :end
        group by day
        """
    )
    _inc_queries("weekly_profit_days_check")
    profit_db_rows = session.execute(profit_check_sql, {"start": previous_from, "end": current_to}).mappings().all()
    profit_days_by_week = defaultdict(int)
    profit_dates_current = []
    profit_dates_previous = []
    for r in profit_db_rows:
        day_val = r["day"]
        if current_from <= day_val <= current_to:
            profit_days_by_week["current"] += 1
            profit_dates_current.append(day_val)
        elif previous_from <= day_val <= previous_to:
            profit_days_by_week["previous"] += 1
            profit_dates_previous.append(day_val)

    # Search days count from DB
    search_check_sql = text(
        """
        select date, count(distinct nm_id) as cnt
        from fact_search_query_metric
        where date >= :start and date <= :end
        group by date
        """
    )
    _inc_queries("weekly_search_days_check")
    search_db_rows = session.execute(search_check_sql, {"start": previous_from, "end": current_to}).mappings().all()
    search_days_by_week = defaultdict(int)
    for r in search_db_rows:
        day_val = r["date"]
        if current_from <= day_val <= current_to:
            search_days_by_week["current"] += 1
        elif previous_from <= day_val <= previous_to:
            search_days_by_week["previous"] += 1

    # Mart days
    mart_days_current = len(curr_daily)
    mart_days_previous = len(prev_daily)
    
    # Ads days (those <= ad_cutoff)
    ads_days_current = sum(1 for r in curr_daily if r["report_date"] <= ad_cutoff)
    ads_days_previous = sum(1 for r in prev_daily if r["report_date"] <= ad_cutoff)

    completeness = {
        "mart_days_current": mart_days_current,
        "mart_days_previous": mart_days_previous,
        "ads_days_current": ads_days_current,
        "ads_days_previous": ads_days_previous,
        "search_days_current": search_days_by_week["current"],
        "search_days_previous": search_days_by_week["previous"],
        "profit_days_current": profit_days_by_week["current"],
        "profit_days_previous": profit_days_by_week["previous"],
    }

    # Determine status of weekly analysis
    # If key data is completely missing
    if mart_days_current == 0 and mart_days_previous == 0:
        return {"status": "UNAVAILABLE", "diagnostic": {"message": "No mart data for both weeks."}}

    status = "OK"
    if mart_days_current < 7 or mart_days_previous < 7:
        status = "PARTIAL"

    # 3. Aggregate Metrics calculations
    def calculate_week_aggs(rows: list[dict[str, Any]], profit_days_count: int, prefix: str, ad_days_limit: int) -> dict[str, Any]:
        res: dict[str, Any] = {}
        # Basic totals
        turnover = safe_sum("order_sum", rows)
        orders = safe_sum("order_count", rows)
        clicks = safe_sum("card_clicks", rows)
        carts = safe_sum("cart_count", rows)
        
        res["turnover"] = turnover
        res["orders"] = orders
        res["average_check"] = _safe_div(turnover, orders)
        res["clicks"] = clicks
        res["carts"] = carts
        res["conversion_click_to_cart"] = _safe_div(carts, clicks) * 100 if clicks else None
        res["conversion_cart_to_order"] = _safe_div(orders, carts) * 100 if carts else None

        # Ad metrics (using matched-window: first N days sorted by date)
        sorted_rows = sorted(rows, key=lambda r: r["report_date"])
        ad_rows = sorted_rows[:ad_days_limit]
        
        ad_spend = safe_sum("ad_spend", ad_rows)
        ad_writeoff_total = safe_sum("ad_writeoff_total", ad_rows)
        if ad_writeoff_total is None:
            ad_writeoff_total = ad_spend
            
        ad_campaign_spend_total = safe_sum("ad_campaign_spend_total", ad_rows)
        if ad_campaign_spend_total is None:
            ad_campaign_spend_total = ad_spend
            
        ad_revenue_total = safe_sum("ad_revenue_total", ad_rows)
        ad_turnover = safe_sum("order_sum", ad_rows)
        
        ad_impressions = safe_sum("ad_views", ad_rows)
        ad_clicks = safe_sum("ad_clicks", ad_rows)
        ad_carts = safe_sum("ad_atbs", ad_rows)
        ad_orders = safe_sum("ad_orders", ad_rows)
        
        res["ad_spend"] = ad_spend
        res["ad_writeoff_total"] = ad_writeoff_total
        res["ad_campaign_spend_total"] = ad_campaign_spend_total
        res["ad_revenue_total"] = ad_revenue_total
        res["ad_turnover"] = ad_turnover
        
        res["ad_impressions"] = ad_impressions
        res["ad_clicks"] = ad_clicks
        res["ad_carts"] = ad_carts
        res["ad_orders"] = ad_orders
        res["ad_days_count"] = len(ad_rows)
        
        # Calculate campaign conversions based on campaign statistics spend
        res["cpc"] = _safe_div(ad_campaign_spend_total, ad_clicks)
        res["cpo"] = _safe_div(ad_campaign_spend_total, ad_orders)
        res["cost_per_ad_cart"] = _safe_div(ad_campaign_spend_total, ad_carts)
        
        cpm_val = _safe_div(ad_campaign_spend_total, ad_impressions)
        res["cpm"] = cpm_val * 1000 if cpm_val is not None else None
        
        # Campaign DRR only if attributed revenue is available
        if ad_revenue_total and ad_revenue_total > 0:
            drr_val = _safe_div(ad_campaign_spend_total, ad_revenue_total)
            res["drr"] = drr_val * 100 if drr_val is not None else None
            res["campaign_spend_share"] = None
        else:
            res["drr"] = None
            share_val = _safe_div(ad_campaign_spend_total, turnover)
            res["campaign_spend_share"] = share_val * 100 if share_val is not None else None

        # Search metrics
        res["search_clicks"] = safe_sum("search_clicks", rows)
        res["search_carts"] = safe_sum("search_cart", rows)
        res["search_orders"] = safe_sum("search_orders", rows)
        res["search_avg_position"] = safe_avg("search_avg_position", rows)
        res["search_visibility"] = safe_avg("search_visibility", rows)

        # Profit metrics (only if fully covered, i.e., 7 days)
        if prefix == "current" and profit_days_count == 7:
            profit_trend = operating_profit_context.get("weekly_trend", {}) or {}
            res["operating_profit"] = _to_decimal(profit_trend.get("current_operating_profit"))
        elif prefix == "previous" and profit_days_count == 7:
            profit_trend = operating_profit_context.get("weekly_trend", {}) or {}
            res["operating_profit"] = _to_decimal(profit_trend.get("previous_operating_profit"))
        else:
            res["operating_profit"] = None
            
        # Logistics metrics
        if prefix == "current":
            log_trend = logistics_summary.get("weekly_trend", {}) or {}
            res["logistics_cost"] = _to_decimal(log_trend.get("current_total"))
        else:
            log_trend = logistics_summary.get("weekly_trend", {}) or {}
            res["logistics_cost"] = _to_decimal(log_trend.get("previous_total"))

        # Profit per unit if profit and organic sales are available
        res["profit_per_unit"] = None
        return res

    current_aggs = calculate_week_aggs(curr_daily, profit_days_by_week["current"], "current", ads_days_current)
    previous_aggs = calculate_week_aggs(prev_daily, profit_days_by_week["previous"], "previous", ads_days_current)

    # Profit per unit calculation on DB-level (weighted)
    def fetch_weighted_profit_aggs(start: date, end: date) -> tuple[Decimal | None, Decimal | None]:
        sql = text(
            """
            select
                sum(coalesce(operating_profit, 0)) as operating_profit,
                sum(coalesce(organic_sales, 0)) as organic_sales
            from fact_vvbromo_product_day
            where day >= :start and day <= :end
            """
        )
        _inc_queries("weekly_profit_weighted_aggs")
        row = session.execute(sql, {"start": start, "end": end}).mappings().one()
        return _to_decimal(row["operating_profit"]), _to_decimal(row["organic_sales"])

    if profit_days_by_week["current"] == 7:
        prof, sales = fetch_weighted_profit_aggs(current_from, current_to)
        current_aggs["profit_per_unit"] = _safe_div(prof, sales)
    if profit_days_by_week["previous"] == 7:
        prof, sales = fetch_weighted_profit_aggs(previous_from, previous_to)
        previous_aggs["profit_per_unit"] = _safe_div(prof, sales)

    # Compute deltas
    delta: dict[str, Any] = {}
    for key, curr_val in current_aggs.items():
        prev_val = previous_aggs.get(key)
        if curr_val is not None and prev_val is not None:
            delta[f"{key}_abs"] = curr_val - prev_val
            if prev_val != 0:
                delta[f"{key}_pct"] = (curr_val - prev_val) / prev_val * 100
            else:
                delta[f"{key}_pct"] = None
        else:
            delta[f"{key}_abs"] = None
            delta[f"{key}_pct"] = None

    # 4. Daily series (max 14 days)
    daily_series: list[dict[str, Any]] = []
    # Combine previous and current dates sequentially
    sorted_dates = sorted(list(curr_daily_by_date.keys() | prev_daily_by_date.keys()))
    
    # Load daily profits to avoid missing unit test fields
    daily_profit_sql = text(
        """
        select day, sum(coalesce(operating_profit, 0)) as operating_profit
        from fact_vvbromo_product_day
        where day >= :start and day <= :end
        group by day
        """
    )
    _inc_queries("weekly_daily_profits")
    profit_daily_rows = {r["day"]: _to_decimal(r["operating_profit"]) for r in session.execute(daily_profit_sql, {"start": previous_from, "end": current_to}).mappings().all()}

    for dt in sorted_dates:
        row = curr_daily_by_date.get(dt) or prev_daily_by_date.get(dt, {})
        day_data: dict[str, Any] = {
            "report_date": dt.isoformat(),
            "turnover": row.get("order_sum"),
            "orders": row.get("order_count"),
            "average_check": row.get("avg_check"),
            "clicks": row.get("card_clicks"),
            "carts": row.get("cart_count"),
            "search_clicks": row.get("search_clicks"),
        }
        # Ad mask
        if dt <= ad_cutoff:
            day_data["ad_spend"] = row.get("ad_spend")
            day_data["ad_orders"] = row.get("ad_orders")
        else:
            day_data["ad_spend"] = None
            day_data["ad_orders"] = None
            
        day_data["operating_profit"] = profit_daily_rows.get(dt)
        # remove None fields to optimize size
        day_data = {k: v for k, v in day_data.items() if v is not None}
        daily_series.append(day_data)

    # 5. Trend Quality (for turnover, orders, clicks, etc.)
    trend_quality: dict[str, Any] = {}
    for metric_key, field_name in [("turnover", "order_sum"), ("orders", "order_count"), ("clicks", "card_clicks")]:
        curr_vals = [Decimal(str(r[field_name])) for r in curr_daily if r.get(field_name) is not None]
        curr_dates = [r["report_date"] for r in curr_daily if r.get(field_name) is not None]
        pct_delta = delta.get(f"{metric_key}_pct")
        trend_quality[metric_key] = _calc_trend_stats(curr_dates, curr_vals, pct_delta)

    # 6. Article Contributions (max 5 positive, 5 negative)
    article_contrib_sql = text(
        """
        with current_week_data as (
            select
                nm_id,
                max(supplier_article) as supplier_article,
                max(title) as title,
                sum(order_sum) as order_sum,
                sum(order_count) as order_count,
                sum(ad_cost_writeoff_total) as ad_spend,
                sum(ad_orders_total) as ad_orders
            from mart_total_report
            where report_date >= :current_from and report_date <= :current_to
            group by nm_id
        ),
        previous_week_data as (
            select
                nm_id,
                max(supplier_article) as supplier_article,
                max(title) as title,
                sum(order_sum) as order_sum,
                sum(order_count) as order_count,
                sum(ad_cost_writeoff_total) as ad_spend,
                sum(ad_orders_total) as ad_orders
            from mart_total_report
            where report_date >= :previous_from and report_date <= :previous_to
            group by nm_id
        ),
        profit_current as (
            select
                nm_id,
                sum(coalesce(operating_profit, 0)) as operating_profit
            from fact_vvbromo_product_day
            where day >= :current_from and day <= :current_to
            group by nm_id
        ),
        profit_previous as (
            select
                nm_id,
                sum(coalesce(operating_profit, 0)) as operating_profit
            from fact_vvbromo_product_day
            where day >= :previous_from and day <= :previous_to
            group by nm_id
        )
        select
            coalesce(c.nm_id, p.nm_id) as nm_id,
            coalesce(c.title, p.title) as product_name,
            coalesce(c.supplier_article, p.supplier_article) as supplier_article,
            coalesce(c.order_sum, 0) as current_week_turnover,
            coalesce(p.order_sum, 0) as previous_week_turnover,
            coalesce(c.order_count, 0) as current_week_orders,
            coalesce(p.order_count, 0) as previous_week_orders,
            coalesce(c.ad_spend, 0) as current_week_ad_spend,
            coalesce(p.ad_spend, 0) as previous_week_ad_spend,
            coalesce(c.ad_orders, 0) as current_week_ad_orders,
            coalesce(p.ad_orders, 0) as previous_week_ad_orders,
            pc.operating_profit as current_week_operating_profit,
            pp.operating_profit as previous_week_operating_profit
        from current_week_data c
        full outer join previous_week_data p on p.nm_id = c.nm_id
        left join profit_current pc on pc.nm_id = coalesce(c.nm_id, p.nm_id)
        left join profit_previous pp on pp.nm_id = coalesce(c.nm_id, p.nm_id)
        """
    )
    _inc_queries("weekly_article_contributions")
    art_rows = session.execute(article_contrib_sql, {
        "current_from": current_from,
        "current_to": current_to,
        "previous_from": previous_from,
        "previous_to": previous_to
    }).mappings().all()

    enriched_arts = []
    for r in art_rows:
        curr_t = _to_decimal(r["current_week_turnover"]) or Decimal("0")
        prev_t = _to_decimal(r["previous_week_turnover"]) or Decimal("0")
        t_delta = curr_t - prev_t
        t_delta_pct = (t_delta / prev_t * 100) if prev_t > 0 else None
        
        curr_p = _to_decimal(r["current_week_operating_profit"])
        prev_p = _to_decimal(r["previous_week_operating_profit"])
        
        # Weighted check for profit availability
        profit_delta = None
        if profit_days_by_week["current"] == 7 and profit_days_by_week["previous"] == 7:
            if curr_p is not None and prev_p is not None:
                profit_delta = curr_p - prev_p
        else:
            # Mark unconfirmed profits as None
            curr_p = None
            prev_p = None

        enriched_arts.append({
            "nm_id": int(r["nm_id"]),
            "product_name": r["product_name"] or r["supplier_article"] or "н/д",
            "supplier_article": r["supplier_article"],
            "current_week_turnover": curr_t,
            "previous_week_turnover": prev_t,
            "turnover_delta_rub": t_delta,
            "turnover_delta_pct": t_delta_pct,
            "current_week_orders": int(r["current_week_orders"]),
            "previous_week_orders": int(r["previous_week_orders"]),
            "orders_delta": int(r["current_week_orders"]) - int(r["previous_week_orders"]),
            "current_week_ad_spend": _to_decimal(r["current_week_ad_spend"]),
            "previous_week_ad_spend": _to_decimal(r["previous_week_ad_spend"]),
            "current_week_ad_orders": int(r["current_week_ad_orders"]),
            "previous_week_ad_orders": int(r["previous_week_ad_orders"]),
            "current_week_operating_profit": curr_p,
            "previous_week_operating_profit": prev_p,
            "profit_delta_rub": profit_delta,
        })

    # Sort contributions by absolute delta of turnover
    enriched_arts.sort(key=lambda item: item["turnover_delta_rub"], reverse=True)
    top_pos_contrib = [item for item in enriched_arts if item["turnover_delta_rub"] > 0][:5]
    
    enriched_arts.sort(key=lambda item: item["turnover_delta_rub"])
    top_neg_contrib = [item for item in enriched_arts if item["turnover_delta_rub"] < 0][:5]

    article_contributions = {
        "top_positive": top_pos_contrib,
        "top_negative": top_neg_contrib,
    }

    # 7. Traffic Sources (max 5 sources)
    traffic_sources_sql = text(
        """
        with current_week as (
            select
                section as source_type,
                sum(coalesce(card_clicks, 0)) as clicks,
                sum(coalesce(cart_count, 0)) as carts,
                sum(coalesce(order_count, 0)) as orders
            from fact_entry_point_day
            where date >= :current_from and date <= :current_to
            group by section
        ),
        previous_week as (
            select
                section as source_type,
                sum(coalesce(card_clicks, 0)) as clicks,
                sum(coalesce(cart_count, 0)) as carts,
                sum(coalesce(order_count, 0)) as orders
            from fact_entry_point_day
            where date >= :previous_from and date <= :previous_to
            group by section
        )
        select
            coalesce(c.source_type, p.source_type) as source_type,
            coalesce(c.clicks, 0) as current_week_clicks,
            coalesce(p.clicks, 0) as previous_week_clicks,
            coalesce(c.carts, 0) as current_week_carts,
            coalesce(p.carts, 0) as previous_week_carts,
            coalesce(c.orders, 0) as current_week_orders,
            coalesce(p.orders, 0) as previous_week_orders
        from current_week c
        full outer join previous_week p on p.source_type = c.source_type
        """
    )
    _inc_queries("weekly_traffic_sources")
    ts_rows = session.execute(traffic_sources_sql, {
        "current_from": current_from,
        "current_to": current_to,
        "previous_from": previous_from,
        "previous_to": previous_to
    }).mappings().all()

    # Article details inside traffic sources (growth & decline, top 3)
    ts_art_sql = text(
        """
        with current_week_art as (
            select
                section as source_type,
                nm_id,
                max(supplier_article) as supplier_article,
                max(title) as title,
                sum(coalesce(card_clicks, 0)) as clicks
            from fact_entry_point_day
            where date >= :current_from and date <= :current_to
            group by section, nm_id
        ),
        previous_week_art as (
            select
                section as source_type,
                nm_id,
                max(supplier_article) as supplier_article,
                max(title) as title,
                sum(coalesce(card_clicks, 0)) as clicks
            from fact_entry_point_day
            where date >= :previous_from and date <= :previous_to
            group by section, nm_id
        )
        select
            coalesce(c.source_type, p.source_type) as source_type,
            coalesce(c.nm_id, p.nm_id) as nm_id,
            coalesce(c.title, p.title) as title,
            coalesce(c.supplier_article, p.supplier_article) as supplier_article,
            coalesce(c.clicks, 0) as current_week_clicks,
            coalesce(p.clicks, 0) as previous_week_clicks
        from current_week_art c
        full outer join previous_week_art p on p.source_type = c.source_type and p.nm_id = c.nm_id
        """
    )
    _inc_queries("weekly_traffic_sources_articles")
    ts_art_rows = session.execute(ts_art_sql, {
        "current_from": current_from,
        "current_to": current_to,
        "previous_from": previous_from,
        "previous_to": previous_to
    }).mappings().all()

    ts_arts_by_type = defaultdict(list)
    for r in ts_art_rows:
        curr_c = _to_decimal(r["current_week_clicks"]) or Decimal("0")
        prev_c = _to_decimal(r["previous_week_clicks"]) or Decimal("0")
        ts_arts_by_type[r["source_type"]].append({
            "nm_id": int(r["nm_id"]),
            "supplier_article": r["supplier_article"],
            "title": r["title"] or r["supplier_article"] or "н/д",
            "current_week_clicks": curr_c,
            "previous_week_clicks": prev_c,
            "clicks_delta": curr_c - prev_c,
        })

    traffic_sources = []
    for r in ts_rows:
        stype = r["source_type"]
        curr_c = _to_decimal(r["current_week_clicks"]) or Decimal("0")
        prev_c = _to_decimal(r["previous_week_clicks"]) or Decimal("0")
        
        art_list = ts_arts_by_type.get(stype, [])
        art_list.sort(key=lambda item: item["clicks_delta"], reverse=True)
        top_growth = [item for item in art_list if item["clicks_delta"] > 0][:3]
        
        art_list.sort(key=lambda item: item["clicks_delta"])
        top_decline = [item for item in art_list if item["clicks_delta"] < 0][:3]

        traffic_sources.append({
            "source_type": stype,
            "current_week_clicks": curr_c,
            "previous_week_clicks": prev_c,
            "clicks_delta": curr_c - prev_c,
            "current_week_carts": _to_decimal(r["current_week_carts"]),
            "previous_week_carts": _to_decimal(r["previous_week_carts"]),
            "carts_delta": (_to_decimal(r["current_week_carts"]) or Decimal("0")) - (_to_decimal(r["previous_week_carts"]) or Decimal("0")),
            "current_week_orders": _to_decimal(r["current_week_orders"]),
            "previous_week_orders": _to_decimal(r["previous_week_orders"]),
            "orders_delta": (_to_decimal(r["current_week_orders"]) or Decimal("0")) - (_to_decimal(r["previous_week_orders"]) or Decimal("0")),
            "top_growth_articles": top_growth,
            "top_decline_articles": top_decline,
        })

    # 8. Weekly Advertising (max 5 campaigns each)
    ad_campaigns_sql = text(
        """
        with current_week_ad as (
            select
                advert_id,
                max(campaign_name) as campaign_name,
                max(row_type) as row_type,
                sum(coalesce(ad_spend, 0)) as spend,
                sum(coalesce(ad_orders, 0)) as orders,
                sum(coalesce(ad_atbs, 0)) as carts,
                sum(coalesce(ad_clicks, 0)) as clicks,
                sum(coalesce(ad_views, 0)) as views,
                sum(coalesce(ad_revenue, 0)) as revenue
            from fact_ad_campaign_nm_day
            where date >= :current_from and date <= :current_to_lagged
            group by advert_id
        ),
        previous_week_ad as (
            select
                advert_id,
                max(campaign_name) as campaign_name,
                max(row_type) as row_type,
                sum(coalesce(ad_spend, 0)) as spend,
                sum(coalesce(ad_orders, 0)) as orders,
                sum(coalesce(ad_atbs, 0)) as carts,
                sum(coalesce(ad_clicks, 0)) as clicks,
                sum(coalesce(ad_views, 0)) as views,
                sum(coalesce(ad_revenue, 0)) as revenue
            from fact_ad_campaign_nm_day
            where date >= :previous_from and date <= :previous_to_lagged
            group by advert_id
        )
        select
            coalesce(c.advert_id, p.advert_id) as advert_id,
            coalesce(c.campaign_name, p.campaign_name) as campaign_name,
            coalesce(c.row_type, p.row_type) as row_type,
            coalesce(c.spend, 0) as current_week_spend,
            coalesce(p.spend, 0) as previous_week_spend,
            coalesce(c.orders, 0) as current_week_orders,
            coalesce(p.orders, 0) as previous_week_orders,
            coalesce(c.carts, 0) as current_week_carts,
            coalesce(p.carts, 0) as previous_week_carts,
            coalesce(c.clicks, 0) as current_week_clicks,
            coalesce(p.clicks, 0) as previous_week_clicks,
            coalesce(c.views, 0) as current_week_views,
            coalesce(p.views, 0) as previous_week_views,
            coalesce(c.revenue, 0) as current_week_revenue,
            coalesce(p.revenue, 0) as previous_week_revenue
        from current_week_ad c
        full outer join previous_week_ad p on p.advert_id = c.advert_id
        """
    )
    _inc_queries("weekly_advertising_campaigns")
    
    # Calculate lagged endpoints for advertising
    current_to_lagged = min(current_to, ad_cutoff)
    previous_to_lagged = min(previous_to, ad_cutoff)

    camp_rows = session.execute(ad_campaigns_sql, {
        "current_from": current_from,
        "current_to_lagged": current_to_lagged,
        "previous_from": previous_from,
        "previous_to_lagged": previous_to_lagged
    }).mappings().all()

    enriched_camps = []
    for r in camp_rows:
        curr_spend = _to_decimal(r["current_week_spend"]) or Decimal("0")
        prev_spend = _to_decimal(r["previous_week_spend"]) or Decimal("0")
        curr_orders = int(r["current_week_orders"])
        prev_orders = int(r["previous_week_orders"])
        
        cpo_curr = _safe_div(curr_spend, Decimal(curr_orders)) if curr_orders else None
        cpo_prev = _safe_div(prev_spend, Decimal(prev_orders)) if prev_orders else None
        
        drr_curr = _safe_div(curr_spend, _to_decimal(r["current_week_revenue"])) * 100 if r["current_week_revenue"] else None
        drr_prev = _safe_div(prev_spend, _to_decimal(r["previous_week_revenue"])) * 100 if r["previous_week_revenue"] else None

        enriched_camps.append({
            "advert_id": int(r["advert_id"]),
            "campaign_name": r["campaign_name"] or f"advert {r['advert_id']}",
            "row_type": r["row_type"] or "н/д",
            "current_week_spend": curr_spend,
            "previous_week_spend": prev_spend,
            "spend_delta": curr_spend - prev_spend,
            "current_week_orders": curr_orders,
            "previous_week_orders": prev_orders,
            "orders_delta": curr_orders - prev_orders,
            "current_week_carts": int(r["current_week_carts"]),
            "previous_week_carts": int(r["previous_week_carts"]),
            "current_week_cpo": cpo_curr,
            "previous_week_cpo": cpo_prev,
            "cpo_delta": _safe_div(curr_spend, Decimal(curr_orders)) - _safe_div(prev_spend, Decimal(prev_orders)) if (curr_orders and prev_orders) else None,
            "current_week_drr": drr_curr,
            "previous_week_drr": drr_prev,
            "drr_delta": drr_curr - drr_prev if (drr_curr is not None and drr_prev is not None) else None,
        })

    # Filter out inactive campaigns
    active_camps = [c for c in enriched_camps if c["current_week_spend"] > 0 or c["previous_week_spend"] > 0]
    
    # Sort by metrics to find improve / worsen
    # Campaign improvement: order increase or spend decrease with stable orders. Let's sort by orders_delta desc, spend_delta asc
    active_camps.sort(key=lambda item: (-item["orders_delta"], item["spend_delta"]))
    top_improved_camps = active_camps[:5]

    # Campaign worsening: order decrease or spend increase with declining orders.
    active_camps.sort(key=lambda item: (item["orders_delta"], -item["spend_delta"]))
    top_worsened_camps = active_camps[:5]

    # Count days active and anomalies (spend > 1.5 * median of active days)
    active_days_sql = text(
        """
        select date, sum(total_spend) as daily_spend
        from fact_ad_cost_day
        where date >= :start and date <= :end
        group by date
        """
    )
    _inc_queries("weekly_advertising_daily_spend")
    ad_days_rows = [r["daily_spend"] for r in session.execute(active_days_sql, {"start": current_from, "end": current_to}).mappings().all() if r["daily_spend"] is not None]
    
    active_days_count = len(ad_days_rows)
    anomalous_days = []
    if ad_days_rows:
        ad_days_rows_sorted = sorted(ad_days_rows)
        median_spend = ad_days_rows_sorted[len(ad_days_rows_sorted) // 2]
        # Load day names
        anomaly_days_sql = text(
            """
            select date, sum(total_spend) as daily_spend
            from fact_ad_cost_day
            where date >= :start and date <= :end
            group by date
            having sum(total_spend) > :threshold
            """
        )
        _inc_queries("weekly_advertising_anomalous_days")
        anomalous_days = [r["date"].isoformat() for r in session.execute(anomaly_days_sql, {"start": current_from, "end": current_to, "threshold": median_spend * Decimal("1.5")}).mappings().all()]

    advertising = {
        "status": "OK" if ads_days_current > 0 else "MISSING",
        "current_week_spend": current_aggs["ad_spend"],
        "previous_week_spend": previous_aggs["ad_spend"],
        "current_week_orders": current_aggs["ad_orders"],
        "previous_week_orders": previous_aggs["ad_orders"],
        "current_week_cpo": current_aggs["cpo"],
        "previous_week_cpo": previous_aggs["cpo"],
        "current_week_drr": current_aggs["drr"],
        "previous_week_drr": previous_aggs["drr"],
        "active_days": active_days_count,
        "anomalous_spend_days": anomalous_days,
        "top_improved_campaigns": top_improved_camps,
        "top_worsened_campaigns": top_worsened_camps,
    }

    # 9. Search Section (max 5 articles each)
    search_sql = text(
        """
        with current_week_search as (
            select
                nm_id,
                max(supplier_article) as supplier_article,
                max(title) as title,
                avg(avg_position) filter (where avg_position is not null) as avg_position,
                avg(visibility) filter (where visibility is not null) as visibility,
                sum(coalesce(search_clicks, 0)) as clicks,
                sum(coalesce(search_orders, 0)) as orders
            from fact_search_query_metric
            where date >= :current_from and date <= :current_to
            group by nm_id
        ),
        previous_week_search as (
            select
                nm_id,
                max(supplier_article) as supplier_article,
                max(title) as title,
                avg(avg_position) filter (where avg_position is not null) as avg_position,
                avg(visibility) filter (where visibility is not null) as visibility,
                sum(coalesce(search_clicks, 0)) as clicks,
                sum(coalesce(search_orders, 0)) as orders
            from fact_search_query_metric
            where date >= :previous_from and date <= :previous_to
            group by nm_id
        )
        select
            coalesce(c.nm_id, p.nm_id) as nm_id,
            coalesce(c.title, p.title) as title,
            coalesce(c.supplier_article, p.supplier_article) as supplier_article,
            c.avg_position as current_week_position,
            p.avg_position as previous_week_position,
            c.visibility as current_week_visibility,
            p.visibility as previous_week_visibility,
            coalesce(c.clicks, 0) as current_week_clicks,
            coalesce(p.clicks, 0) as previous_week_clicks,
            coalesce(c.orders, 0) as current_week_orders,
            coalesce(p.orders, 0) as previous_week_orders
        from current_week_search c
        full outer join previous_week_search p on p.nm_id = c.nm_id
        """
    )
    _inc_queries("weekly_search_mover_articles")
    search_rows = session.execute(search_sql, {
        "current_from": current_from,
        "current_to": current_to,
        "previous_from": previous_from,
        "previous_to": previous_to
    }).mappings().all()

    enriched_search = []
    for r in search_rows:
        curr_p = _to_decimal(r["current_week_position"])
        prev_p = _to_decimal(r["previous_week_position"])
        curr_v = _to_decimal(r["current_week_visibility"])
        prev_v = _to_decimal(r["previous_week_visibility"])
        
        pos_delta = curr_p - prev_p if (curr_p is not None and prev_p is not None) else None
        vis_delta = curr_v - prev_v if (curr_v is not None and prev_v is not None) else None
        
        enriched_search.append({
            "nm_id": int(r["nm_id"]),
            "supplier_article": r["supplier_article"],
            "title": r["title"] or r["supplier_article"] or "н/д",
            "current_week_position": curr_p,
            "previous_week_position": prev_p,
            "position_delta": pos_delta,
            "current_week_visibility": curr_v,
            "previous_week_visibility": prev_v,
            "visibility_delta": vis_delta,
            "current_week_clicks": int(r["current_week_clicks"]),
            "previous_week_clicks": int(r["previous_week_clicks"]),
            "clicks_delta": int(r["current_week_clicks"]) - int(r["previous_week_clicks"]),
        })

    # Sort search movers (visibility loss / growth)
    enriched_search.sort(key=lambda item: item["visibility_delta"] or Decimal("0"), reverse=True)
    search_growth = [item for item in enriched_search if (item["visibility_delta"] or Decimal("0")) > 0][:5]
    
    enriched_search.sort(key=lambda item: item["visibility_delta"] or Decimal("0"))
    search_loss = [item for item in enriched_search if (item["visibility_delta"] or Decimal("0")) < 0][:5]

    search = {
        "status": "OK" if search_days_by_week["current"] > 0 else "MISSING",
        "current_week_clicks": current_aggs["search_clicks"],
        "previous_week_clicks": previous_aggs["search_clicks"],
        "current_week_avg_position": current_aggs["search_avg_position"],
        "previous_week_avg_position": previous_aggs["search_avg_position"],
        "current_week_visibility": current_aggs["search_visibility"],
        "previous_week_visibility": previous_aggs["search_visibility"],
        "top_growth_articles": search_growth,
        "top_loss_articles": search_loss,
    }

    # 10. Operating Profit Context
    # Check completeness of profit
    profit_status = "OK"
    profit_dates_range = None
    if profit_days_by_week["current"] < 7 or profit_days_by_week["previous"] < 7:
        profit_status = "PARTIAL"
        all_profit_dates = sorted(list(set(profit_dates_current) | set(profit_dates_previous)))
        if all_profit_dates:
            profit_dates_range = {
                "from": all_profit_dates[0].isoformat(),
                "to": all_profit_dates[-1].isoformat(),
                "count": len(all_profit_dates)
            }
    if profit_days_by_week["current"] == 0 and profit_days_by_week["previous"] == 0:
        profit_status = "MISSING"

    # Identify most profitable and loss-making items
    prof_sorted = [item for item in enriched_arts if item["current_week_operating_profit"] is not None]
    
    prof_sorted.sort(key=lambda item: item["current_week_operating_profit"] or Decimal("0"), reverse=True)
    most_profitable = prof_sorted[:5]
    
    prof_sorted.sort(key=lambda item: item["current_week_operating_profit"] or Decimal("0"))
    most_loss_making = prof_sorted[:5]

    # Turnover up but profit down, or turnover down but profit up
    turnover_up_profit_down = []
    turnover_down_profit_up = []
    for item in enriched_arts:
        td = item["turnover_delta_rub"]
        pd = item["profit_delta_rub"]
        if td is not None and pd is not None:
            if td > 0 and pd < 0:
                turnover_up_profit_down.append(item)
            elif td < 0 and pd > 0:
                turnover_down_profit_up.append(item)

    operating_profit = {
        "status": profit_status,
        "profit_dates_range": profit_dates_range,
        "current_week_profit": current_aggs["operating_profit"],
        "previous_week_profit": previous_aggs["operating_profit"],
        "profit_delta": delta.get("operating_profit_abs"),
        "current_week_profit_per_unit": current_aggs["profit_per_unit"],
        "previous_week_profit_per_unit": previous_aggs["profit_per_unit"],
        "most_profitable_articles": most_profitable,
        "most_loss_making_articles": most_loss_making,
        "turnover_up_profit_down": turnover_up_profit_down[:5],
        "turnover_down_profit_up": turnover_down_profit_up[:5],
    }

    # 11. Prices & SPP (using existing pricing SPP context filtered for the week)
    price_changes = []
    existing_price_changes = pricing_spp_context.get("top_price_changes") or []
    for pc in existing_price_changes:
        # filter to current week
        chg_date = pc.get("change_date")
        if isinstance(chg_date, str):
            try:
                chg_date = date.fromisoformat(chg_date)
            except Exception:
                continue
        if chg_date and current_from <= chg_date <= current_to:
            price_changes.append(pc)

    prices = {
        "status": "OK" if price_changes else "NO_CHANGES",
        "top_price_changes": price_changes[:5]
    }

    # 12. Stocks snapshot analysis (first vs last date)
    stocks_sql = text(
        """
        select snapshot_date, nm_id, sum(stock_qty) as stock_qty
        from fact_stock_warehouse_snapshot
        where snapshot_date >= :start and snapshot_date <= :end
        group by snapshot_date, nm_id
        order by nm_id, snapshot_date
        """
    )
    _inc_queries("weekly_stock_snapshots")
    stock_rows = session.execute(stocks_sql, {"start": current_from, "end": current_to}).mappings().all()
    
    stock_by_nm = defaultdict(list)
    for r in stock_rows:
        stock_by_nm[int(r["nm_id"])].append(r)

    stock_coverage_dates = sorted(list({r["snapshot_date"] for r in stock_rows}))
    
    stock_analysis_rows = []
    if stock_coverage_dates:
        first_date = stock_coverage_dates[0]
        last_date = stock_coverage_dates[-1]
        for nm_id, pts in stock_by_nm.items():
            pts_by_date = {p["snapshot_date"]: p for p in pts}
            first_pt = pts_by_date.get(first_date)
            last_pt = pts_by_date.get(last_date)
            if first_pt and last_pt:
                qty_first = _to_decimal(first_pt["stock_qty"]) or Decimal("0")
                qty_last = _to_decimal(last_pt["stock_qty"]) or Decimal("0")
                stock_analysis_rows.append({
                    "nm_id": nm_id,
                    "first_snapshot_qty": qty_first,
                    "last_snapshot_qty": qty_last,
                    "delta": qty_last - qty_first,
                })
        stock_analysis_rows.sort(key=lambda item: abs(item["delta"]), reverse=True)

    stocks = {
        "status": "OK" if stock_coverage_dates else "MISSING",
        "first_snapshot_date": stock_coverage_dates[0].isoformat() if stock_coverage_dates else None,
        "last_snapshot_date": stock_coverage_dates[-1].isoformat() if stock_coverage_dates else None,
        "coverage": len(stock_coverage_dates),
        "top_stock_movers": stock_analysis_rows[:5],
    }

    # 13. Evidence Generation
    evidence = []
    missing_evidence = []

    # Check key signals
    turnover_chg_pct = delta.get("turnover_pct")
    if turnover_chg_pct is not None and abs(turnover_chg_pct) > 5:
        kind = "turnover_drop" if turnover_chg_pct < 0 else "turnover_growth"
        evidence.append({
            "kind": kind,
            "entity_type": "cabinet",
            "entity_id": None,
            "current_period_value": current_aggs["turnover"],
            "previous_period_value": previous_aggs["turnover"],
            "delta": delta["turnover_abs"],
            "days_affected": mart_days_current,
            "supporting_dates": [current_from.isoformat(), current_to.isoformat()],
            "supporting_metrics": ["turnover", "orders"],
            "confidence": "high" if mart_days_current == 7 else "medium",
        })

    # Ad efficiency signal
    cpo_chg_pct = delta.get("cpo_pct")
    if cpo_chg_pct is not None and cpo_chg_pct > 15:
        evidence.append({
            "kind": "ad_cpo_worsening",
            "entity_type": "cabinet",
            "entity_id": None,
            "current_period_value": current_aggs["cpo"],
            "previous_period_value": previous_aggs["cpo"],
            "delta": delta["cpo_abs"],
            "days_affected": ads_days_current,
            "supporting_dates": [current_from.isoformat(), ad_cutoff.isoformat()],
            "supporting_metrics": ["cpo", "ad_spend", "ad_orders"],
            "confidence": "medium" if ads_days_current >= 5 else "low",
        })

    # Missing evidence check: if ads data is lagged/missing
    if ads_days_current < 5:
        missing_evidence.append({
            "kind": "ad_attribution_lag",
            "entity_type": "cabinet",
            "message": "Рекламные данные за последние 2 дня недели находятся в стадии дозагрузки (AD_ATTRIBUTION_LAGGED).",
        })
    if profit_status == "PARTIAL":
        missing_evidence.append({
            "kind": "profit_partial_data",
            "entity_type": "cabinet",
            "message": "Данные о прибыли за неделю загружены не полностью (PARTIAL). Сравнение прибыли заблокировано.",
        })

    return {
        "current_period": {
            "from": current_from.isoformat(),
            "to": current_to.isoformat()
        },
        "previous_period": {
            "from": previous_from.isoformat(),
            "to": previous_to.isoformat()
        },
        "status": status,
        "completeness": completeness,
        "aggregate_metrics": {
            "current_week": current_aggs,
            "previous_week": previous_aggs,
            "delta": delta,
        },
        "daily_series": daily_series,
        "trend_quality": trend_quality,
        "article_contributions": article_contributions,
        "traffic_sources": traffic_sources,
        "advertising": advertising,
        "search": search,
        "operating_profit": operating_profit,
        "prices": prices,
        "stocks": stocks,
        "anomalies": [],
        "evidence": evidence,
        "missing_evidence": missing_evidence,
    }
