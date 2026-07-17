from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Sequence

from src.mcp_server.schemas import WbDailyOperationalHighlightsResponse
from src.mcp_server.wb_daily_operational_summary_rules import WbDailyOperationalSummaryRules

PRICE_CHANGE_THRESHOLD_PCT = Decimal("10")
LOW_TRAFFIC_QUERY_CLICKS = Decimal("5")
POSITION_JUMP_ANOMALY = Decimal("50")
CONVERSION_STABLE_PP = Decimal("1.5")
LARGE_TURNOVER_LOSS_RUB = Decimal("25000")
LARGE_TURNOVER_GROWTH_RUB = Decimal("20000")
LARGE_TURNOVER_SHARE_PCT = Decimal("30")


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _median(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    values = sorted(values)
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / Decimal("2")


def _safe_diff(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None:
        return None
    return current - previous


def _safe_pct_delta(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous in (None, Decimal("0")):
        return None
    return (current - previous) / previous * Decimal("100")


def _safe_ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator in (None, Decimal("0")):
        return None
    return numerator / denominator * Decimal("100")


def _format_decimal(value: Any, decimals: int = 0) -> str:
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return "н/д"
    quant = Decimal("1") if decimals == 0 else Decimal("1." + ("0" * decimals))
    return f"{decimal_value.quantize(quant):,.{decimals}f}".replace(",", " ")


def _format_currency(value: Any) -> str:
    return f"{_format_decimal(value, 0)} ₽"


def _format_percent(value: Any, decimals: int = 1) -> str:
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return "н/д"
    prefix = "+" if decimal_value > 0 else ""
    return f"{prefix}{_format_decimal(decimal_value, decimals)}%"


def _format_pp(value: Any, decimals: int = 1) -> str:
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return "н/д"
    prefix = "+" if decimal_value > 0 else ""
    return f"{prefix}{_format_decimal(decimal_value, decimals)} п.п."


def _series(rows: Iterable[dict[str, Any]], *, report_date: date, date_key: str, metric_key: str) -> list[tuple[date, Decimal]]:
    points: list[tuple[date, Decimal]] = []
    for row in rows:
        point_date = row.get(date_key)
        point_value = _to_decimal(row.get(metric_key))
        if point_date is None or point_value is None or point_date > report_date:
            continue
        points.append((point_date, point_value))
    points.sort(key=lambda item: item[0])
    return points


def build_metric_history(rows: Iterable[dict[str, Any]], *, report_date: date, date_key: str, metric_key: str, threshold_pct: Decimal = Decimal("5")) -> dict[str, Any]:
    series = _series(rows, report_date=report_date, date_key=date_key, metric_key=metric_key)
    current = next((value for point_date, value in reversed(series) if point_date == report_date), None)
    previous_points = [(point_date, value) for point_date, value in series if point_date < report_date]
    previous_day = previous_points[-1][1] if previous_points else None
    prev7 = [value for _, value in previous_points[-7:]]
    prev14 = [value for _, value in previous_points[-14:]]
    prev7_before_previous = [value for _, value in previous_points[-8:-1]] if len(previous_points) >= 8 else []
    avg_prev_7 = _mean(prev7) if len(prev7) >= 7 else None
    median_prev_7 = _median(prev7) if len(prev7) >= 7 else None
    avg_prev_14 = _mean(prev14) if len(prev14) >= 14 else None
    previous_day_avg_prev_7 = _mean(prev7_before_previous) if len(prev7_before_previous) == 7 else None

    series_values = [value for _, value in series]
    direction: str | None = None
    consecutive_days = 0
    for index in range(len(series_values) - 1, 0, -1):
        delta_pct = _safe_pct_delta(series_values[index], series_values[index - 1])
        if delta_pct is None:
            break
        if delta_pct >= threshold_pct:
            step_direction = "growth"
        elif delta_pct <= -threshold_pct:
            step_direction = "decline"
        else:
            break
        if direction is None:
            direction = step_direction
            consecutive_days = 1
        elif step_direction == direction:
            consecutive_days += 1
        else:
            break

    current_pct_vs_avg_prev_7 = _safe_pct_delta(current, avg_prev_7)
    current_pct_vs_median_prev_7 = _safe_pct_delta(current, median_prev_7)
    current_pct_vs_previous_day_avg_prev_7 = _safe_pct_delta(current, previous_day_avg_prev_7)
    previous_day_pct_vs_avg_prev_7 = _safe_pct_delta(previous_day, previous_day_avg_prev_7)
    near_baseline = (
        (current_pct_vs_avg_prev_7 is not None and abs(current_pct_vs_avg_prev_7) < threshold_pct)
        or (current_pct_vs_median_prev_7 is not None and abs(current_pct_vs_median_prev_7) < threshold_pct)
        or (current_pct_vs_previous_day_avg_prev_7 is not None and abs(current_pct_vs_previous_day_avg_prev_7) < threshold_pct)
    )
    previous_day_spike = previous_day_pct_vs_avg_prev_7 is not None and previous_day_pct_vs_avg_prev_7 >= threshold_pct
    previous_day_drop = previous_day_pct_vs_avg_prev_7 is not None and previous_day_pct_vs_avg_prev_7 <= -threshold_pct

    if avg_prev_7 is None or previous_day is None:
        trend_status = "insufficient_history"
    elif (previous_day_spike or previous_day_drop) and near_baseline:
        trend_status = "return_to_baseline"
    elif previous_day_spike and current is not None and current < previous_day:
        trend_status = "previous_day_spike"
    elif previous_day_drop and current is not None and current > previous_day:
        trend_status = "previous_day_drop"
    elif direction == "decline":
        trend_status = "decline_3_plus_days" if consecutive_days >= 3 else ("decline_2_days" if consecutive_days == 2 else "first_decline")
    elif direction == "growth":
        trend_status = "growth_3_plus_days" if consecutive_days >= 3 else ("growth_2_days" if consecutive_days == 2 else "first_growth")
    else:
        trend_status = "stable"

    return {
        "metric": metric_key,
        "current": current,
        "previous_day": previous_day,
        "avg_prev_7": avg_prev_7,
        "median_prev_7": median_prev_7,
        "avg_prev_14": avg_prev_14,
        "delta_vs_previous_day": _safe_diff(current, previous_day),
        "pct_vs_previous_day": _safe_pct_delta(current, previous_day),
        "delta_vs_avg_prev_7": _safe_diff(current, avg_prev_7),
        "pct_vs_avg_prev_7": current_pct_vs_avg_prev_7,
        "delta_vs_median_prev_7": _safe_diff(current, median_prev_7),
        "pct_vs_median_prev_7": _safe_pct_delta(current, median_prev_7),
        "previous_day_pct_vs_avg_prev_7": previous_day_pct_vs_avg_prev_7,
        "consecutive_days": consecutive_days,
        "trend_status": trend_status,
        "history_days_available": len(previous_points),
        "points": [{"date": point_date, metric_key: value} for point_date, value in series],
    }


def _history_gap(metric_name: str, scope: str, nm_id: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "historical_baseline",
        "status": "PARTIAL",
        "scope": scope,
        "metric": metric_name,
        "message": "Недостаточно предыдущих полных дней для устойчивого baseline 7/14.",
    }
    if nm_id is not None:
        payload["nm_id"] = nm_id
    return payload


def _trend_weight(trend_status: str) -> Decimal:
    return {
        "decline_3_plus_days": Decimal("24"),
        "growth_3_plus_days": Decimal("24"),
        "decline_2_days": Decimal("14"),
        "growth_2_days": Decimal("14"),
        "first_decline": Decimal("4"),
        "first_growth": Decimal("4"),
        "return_to_baseline": Decimal("-6"),
        "previous_day_spike": Decimal("-4"),
        "previous_day_drop": Decimal("-4"),
        "stable": Decimal("0"),
        "insufficient_history": Decimal("-8"),
    }.get(trend_status, Decimal("0"))


def _quality_penalty(partial_primary: bool) -> Decimal:
    return Decimal("-25") if partial_primary else Decimal("0")


def _search_query_is_significant(query_row: dict[str, Any], report_date: date, rules: WbDailyOperationalSummaryRules) -> bool:
    history = build_metric_history(query_row.get("trend_7d") or [], report_date=report_date, date_key="date", metric_key="search_clicks")
    baseline_clicks = _to_decimal(history.get("avg_prev_7")) or Decimal("0")
    current_carts = _to_decimal(query_row.get("search_cart")) or Decimal("0")
    current_orders = _to_decimal(query_row.get("search_orders")) or Decimal("0")
    clicks_delta = abs(_to_decimal(query_row.get("clicks_delta_day")) or Decimal("0"))
    orders_delta = abs(_to_decimal(query_row.get("orders_delta_day")) or Decimal("0"))
    ever_orders = any((_to_decimal(row.get("search_orders")) or Decimal("0")) > 0 for row in (query_row.get("trend_7d") or []))
    persistent_change = abs(_to_decimal(history.get("pct_vs_previous_day")) or Decimal("0")) >= rules.significant_pct_change
    return any((baseline_clicks >= LOW_TRAFFIC_QUERY_CLICKS, current_carts > 0, current_orders > 0, ever_orders, clicks_delta >= Decimal("5"), orders_delta > 0, persistent_change))


def build_article_analysis(*, report_date: date, article_context: Sequence[dict[str, Any]], warehouse_context: Sequence[dict[str, Any]], campaign_context: Sequence[dict[str, Any]], search_query_context: Sequence[dict[str, Any]], entry_point_context: Sequence[dict[str, Any]], price_context: Sequence[dict[str, Any]], logistics_context: Sequence[dict[str, Any]], data_gaps: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    warehouse_by_nm: dict[int, list[dict[str, Any]]] = defaultdict(list)
    campaign_by_nm: dict[int, list[dict[str, Any]]] = defaultdict(list)
    search_by_nm: dict[int, list[dict[str, Any]]] = defaultdict(list)
    entry_by_nm: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in warehouse_context:
        try:
            warehouse_by_nm[int(row.get("nm_id"))].append(row)
        except (TypeError, ValueError):
            continue
    for row in campaign_context:
        try:
            campaign_by_nm[int(row.get("nm_id"))].append(row)
        except (TypeError, ValueError):
            continue
    for row in search_query_context:
        try:
            search_by_nm[int(row.get("nm_id"))].append(row)
        except (TypeError, ValueError):
            continue
    for row in entry_point_context:
        try:
            entry_by_nm[int(row.get("nm_id"))].append(row)
        except (TypeError, ValueError):
            continue
    price_by_nm = {int(row.get("nm_id")): row for row in price_context if row.get("nm_id") is not None}
    logistics_by_nm = {int(row.get("nm_id")): row for row in logistics_context if row.get("nm_id") is not None}

    rows: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for article in article_context:
        nm_id = int(article.get("nm_id"))
        trend_rows = article.get("trend_14d") or []
        sales_history = build_metric_history(trend_rows, report_date=report_date, date_key="report_date", metric_key="order_sum")
        clicks_history = build_metric_history(trend_rows, report_date=report_date, date_key="report_date", metric_key="card_clicks")
        carts_history = build_metric_history(trend_rows, report_date=report_date, date_key="report_date", metric_key="cart_count")
        orders_history = build_metric_history(trend_rows, report_date=report_date, date_key="report_date", metric_key="order_count")
        impressions_history = build_metric_history(trend_rows, report_date=report_date, date_key="report_date", metric_key="impressions")
        if sales_history.get("avg_prev_7") is None:
            gaps.append(_history_gap("order_sum", "article_analysis", nm_id))
        previous_point = next((row for row in reversed(trend_rows) if row.get("report_date") and row.get("report_date") < report_date), None)
        current_clicks = _to_decimal(article.get("card_clicks"))
        current_carts = _to_decimal(article.get("cart_count"))
        current_orders = _to_decimal(article.get("order_count"))
        current_order_sum = _to_decimal(article.get("order_sum"))
        previous_clicks = _to_decimal(previous_point.get("card_clicks")) if previous_point else None
        previous_carts = _to_decimal(previous_point.get("cart_count")) if previous_point else None
        previous_orders = _to_decimal(previous_point.get("order_count")) if previous_point else None
        previous_order_sum = _to_decimal(previous_point.get("order_sum")) if previous_point else None
        current_atc = _safe_ratio(current_carts, current_clicks)
        previous_atc = _safe_ratio(previous_carts, previous_clicks)
        current_c2o = _safe_ratio(current_orders, current_carts)
        previous_c2o = _safe_ratio(previous_orders, previous_carts)
        current_avg_check = None if current_orders in (None, Decimal("0")) or current_order_sum is None else current_order_sum / current_orders
        previous_avg_check = None if previous_orders in (None, Decimal("0")) or previous_order_sum is None else previous_order_sum / previous_orders
        rows.append({
            "nm_id": nm_id,
            "supplier_article": article.get("supplier_article"),
            "title": article.get("title"),
            "sales": {"order_sum": current_order_sum, "order_count": current_orders, "avg_check": current_avg_check, "avg_check_previous": previous_avg_check, "baseline": sales_history},
            "traffic": {"impressions": _to_decimal(article.get("impressions")), "card_clicks": current_clicks, "cart_count": current_carts, "baseline_clicks": clicks_history, "baseline_impressions": impressions_history, "baseline_carts": carts_history, "add_to_cart_conversion": current_atc, "add_to_cart_conversion_previous": previous_atc},
            "funnel": {"cart_to_order_conversion": current_c2o, "cart_to_order_conversion_previous": previous_c2o, "order_count_baseline": orders_history},
            "ads": {"campaigns": campaign_by_nm.get(nm_id, [])},
            "search": {"queries": search_by_nm.get(nm_id, [])},
            "price": price_by_nm.get(nm_id),
            "stock": {"stock_qty_same_day": _to_decimal(article.get("stock_qty_same_day")), "warehouses_with_stock": int(article.get("warehouses_with_stock") or 0), "warehouses_zero_stock": int(article.get("warehouses_zero_stock") or 0), "warehouse_rows": warehouse_by_nm.get(nm_id, []), "stock_status": article.get("stock_status")},
            "entry_points": {"rows": entry_by_nm.get(nm_id, [])},
            "logistics": logistics_by_nm.get(nm_id),
            "history": {"trend_14d": trend_rows},
            "data_quality": {"price_partial": (price_by_nm.get(nm_id) or {}).get("source_status") != "OK", "stock_partial": article.get("stock_status") != "OK", "entry_partial": any(str((row or {}).get("source_status")) != "OK" for row in entry_by_nm.get(nm_id, [])), "logistics_partial": (logistics_by_nm.get(nm_id) or {}).get("source_status") == "PARTIAL"},
        })
    return rows, gaps


def _build_signal(*, kind: str, direction: str, title: str, summary: str, check_text: str, metric: str, trend_status: str, confirmations: int, confidence: str, partial_primary: bool, order_sum_delta: Decimal | None = None, share_of_total_delta: Decimal | None = None, nm_id: int | None = None, advert_id: int | None = None, search_query: str | None = None, warehouse_name: str | None = None, evidence: list[str] | None = None, operational_weight: Decimal = Decimal("10"), cause_status: str = "confirmed", supported_factors: list[str] | None = None, missing_evidence: list[str] | None = None, recommended_check: str | None = None) -> dict[str, Any]:
    delta_component = min(abs(order_sum_delta or Decimal("0")) / Decimal("1000"), Decimal("35"))
    share_component = min(abs(share_of_total_delta or Decimal("0")), Decimal("100")) / Decimal("4")
    score = delta_component + share_component + _trend_weight(trend_status) + Decimal(confirmations * 4) + operational_weight + _quality_penalty(partial_primary)
    return {
        "kind": kind,
        "signal_key": kind,
        "direction": direction,
        "nm_id": nm_id,
        "entity_type": "product" if nm_id is not None else ("campaign" if advert_id is not None else "query" if search_query else "aggregate"),
        "entity_id": nm_id if nm_id is not None else advert_id,
        "advert_id": advert_id,
        "search_query": search_query,
        "warehouse_name": warehouse_name,
        "metric": metric,
        "title": title,
        "summary": summary,
        "check": {"text": check_text, "nm_id": nm_id, "advert_id": advert_id, "search_query": search_query, "warehouse": warehouse_name, "metric": metric},
        "order_sum_delta": order_sum_delta,
        "impact_rub": order_sum_delta,
        "share_of_total_delta": share_of_total_delta,
        "trend_status": trend_status,
        "confirmations": confirmations,
        "confidence": confidence,
        "score": score,
        "partial_primary": partial_primary,
        "cause_status": cause_status,
        "supported_factors": supported_factors if supported_factors is not None else list(evidence or []),
        "missing_evidence": missing_evidence or [],
        "recommended_check": recommended_check or check_text,
        "evidence": evidence or [],
        "user_visible": not partial_primary,
    }



def _build_data_anomalies(*, report_date: date, article_analysis: Sequence[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for article in article_analysis:
        nm_id = int(article["nm_id"])
        for query_row in article["search"]["queries"]:
            position_delta = _to_decimal(query_row.get("position_delta_day"))
            current_clicks = _to_decimal(query_row.get("search_clicks")) or Decimal("0")
            current_visibility = _to_decimal(query_row.get("visibility"))
            trend_rows = query_row.get("trend_7d") or []
            baseline_clicks = build_metric_history(trend_rows, report_date=report_date, date_key="date", metric_key="search_clicks").get("avg_prev_7")
            if position_delta is not None and position_delta >= POSITION_JUMP_ANOMALY and (baseline_clicks or Decimal("0")) < LOW_TRAFFIC_QUERY_CLICKS:
                anomalies.append({"kind": "search_low_traffic_position_jump", "nm_id": nm_id, "search_query": query_row.get("search_query"), "severity": "medium", "summary": f"Резкий скачок позиции по запросу «{query_row.get('search_query')}» при малом базовом трафике. Нужна проверка данных."})
            if position_delta is not None and position_delta >= POSITION_JUMP_ANOMALY and (_to_decimal(query_row.get("clicks_delta_day")) or Decimal("0")) >= 0 and (_to_decimal(query_row.get("orders_delta_day")) or Decimal("0")) >= 0:
                anomalies.append({"kind": "search_position_without_traffic_drop", "nm_id": nm_id, "search_query": query_row.get("search_query"), "severity": "medium", "summary": f"Позиция по запросу «{query_row.get('search_query')}» резко ухудшилась, но трафик не подтвердил падение."})
            if current_visibility == Decimal("0") and current_clicks > 0:
                anomalies.append({"kind": "search_zero_visibility_with_clicks", "nm_id": nm_id, "search_query": query_row.get("search_query"), "severity": "high", "summary": f"Нулевая видимость по запросу «{query_row.get('search_query')}» не совпадает с положительными кликами."})
        if (article["traffic"].get("cart_count") or Decimal("0")) == 0 and (article["sales"].get("order_count") or Decimal("0")) > 0:
            anomalies.append({"kind": "orders_without_carts", "nm_id": nm_id, "severity": "high", "summary": f"У артикула {nm_id} есть заказы при нулевых корзинах."})
        for campaign in article["ads"]["campaigns"]:
            if (_to_decimal(campaign.get("ad_spend")) or Decimal("0")) > 0 and (_to_decimal(campaign.get("ad_views")) or Decimal("0")) == 0 and (_to_decimal(campaign.get("ad_clicks")) or Decimal("0")) == 0:
                anomalies.append({"kind": "ad_spend_without_reach", "nm_id": nm_id, "advert_id": campaign.get("advert_id"), "severity": "high", "summary": f"По кампании {campaign.get('advert_id')} есть расход без показов и кликов."})
        if (article["stock"].get("stock_qty_same_day") or Decimal("0")) == 0 and (article["sales"].get("order_count") or Decimal("0")) > 0:
            anomalies.append({"kind": "zero_stock_with_orders", "nm_id": nm_id, "severity": "high", "summary": f"У артикула {nm_id} нулевой остаток при продолжающихся заказах."})
        price = article.get("price") or {}
        previous_price = _to_decimal(price.get("previous_buyer_visible_price"))
        current_price = _to_decimal(price.get("buyer_visible_price"))
        price_delta_pct = _safe_pct_delta(current_price, previous_price)
        if price_delta_pct is not None and abs(price_delta_pct) >= PRICE_CHANGE_THRESHOLD_PCT:
            anomalies.append({"kind": "sharp_price_change", "nm_id": nm_id, "severity": "medium", "summary": f"У артикула {nm_id} цена изменилась на {_format_percent(price_delta_pct)} за день."})
    anomalies.sort(key=lambda item: {"high": 0, "medium": 1, "low": 2}.get(str(item.get("severity")), 3))
    return anomalies[: max(top_n * 2, top_n)]


def _build_ranked_signals(*, report_date: date, daily_rows: Sequence[dict[str, Any]], article_analysis: Sequence[dict[str, Any]], anomalies: Sequence[dict[str, Any]], rules: WbDailyOperationalSummaryRules, top_n: int) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    total_negative_delta = sum(abs((_to_decimal(row["sales"]["baseline"].get("delta_vs_previous_day")) or Decimal("0"))) for row in article_analysis if (_to_decimal(row["sales"]["baseline"].get("delta_vs_previous_day")) or Decimal("0")) < 0)
    total_positive_delta = sum(abs((_to_decimal(row["sales"]["baseline"].get("delta_vs_previous_day")) or Decimal("0"))) for row in article_analysis if (_to_decimal(row["sales"]["baseline"].get("delta_vs_previous_day")) or Decimal("0")) > 0)
    aggregate_sales = build_metric_history(daily_rows, report_date=report_date, date_key="report_date", metric_key="order_sum")
    delta = _to_decimal(aggregate_sales.get("delta_vs_previous_day")) or Decimal("0")
    if delta < 0 and aggregate_sales.get("trend_status") not in {"return_to_baseline", "previous_day_spike"}:
        signals.append(_build_signal(kind="aggregate_sales", direction="negative", title="Общий спад оборота", summary=f"Оборот заказов снижается устойчивее обычного: {_format_currency(aggregate_sales.get('current'))} против {_format_currency(aggregate_sales.get('previous_day'))}.", check_text="Проверить совокупный вклад трафика, поиска и рекламы в спад оборота.", metric="order_sum", trend_status=str(aggregate_sales.get("trend_status")), confirmations=2, confidence="high", partial_primary=False, order_sum_delta=delta, share_of_total_delta=Decimal("100"), operational_weight=Decimal("8")))
    elif delta > 0 and aggregate_sales.get("trend_status") in {"growth_2_days", "growth_3_plus_days", "first_growth"}:
        signals.append(_build_signal(kind="aggregate_sales", direction="positive", title="Общий рост оборота", summary=f"Оборот заказов вырос до {_format_currency(aggregate_sales.get('current'))}.", check_text="Проверить, какие артикулы дали основной вклад в рост оборота.", metric="order_sum", trend_status=str(aggregate_sales.get("trend_status")), confirmations=2, confidence="high", partial_primary=False, order_sum_delta=delta, share_of_total_delta=Decimal("100"), operational_weight=Decimal("8")))

    for article in article_analysis:
        nm_id = int(article["nm_id"])
        sales_baseline = article["sales"]["baseline"]
        order_sum_delta = _to_decimal(sales_baseline.get("delta_vs_previous_day")) or Decimal("0")
        share_negative = (abs(order_sum_delta) / total_negative_delta * Decimal("100")) if total_negative_delta > 0 and order_sum_delta < 0 else None
        share_positive = (abs(order_sum_delta) / total_positive_delta * Decimal("100")) if total_positive_delta > 0 and order_sum_delta > 0 else None
        trend_status = str(sales_baseline.get("trend_status"))
        traffic = article["traffic"]
        current_atc = _to_decimal(traffic.get("add_to_cart_conversion"))
        previous_atc = _to_decimal(traffic.get("add_to_cart_conversion_previous"))
        atc_delta_pp = _safe_diff(current_atc, previous_atc)
        current_avg_check = _to_decimal(article["sales"].get("avg_check"))
        previous_avg_check = _to_decimal(article["sales"].get("avg_check_previous"))
        avg_check_delta_pct = _safe_pct_delta(current_avg_check, previous_avg_check)
        clicks_drop = (_to_decimal(traffic["baseline_clicks"].get("pct_vs_previous_day")) or Decimal("0")) <= -rules.significant_pct_change
        impressions_drop = (_to_decimal(traffic["baseline_impressions"].get("pct_vs_previous_day")) or Decimal("0")) <= -rules.significant_pct_change
        carts_drop = (_to_decimal(traffic["baseline_carts"].get("pct_vs_previous_day")) or Decimal("0")) <= -rules.significant_pct_change
        stock_qty = _to_decimal(article["stock"].get("stock_qty_same_day")) or Decimal("0")
        conversion_stable = atc_delta_pp is None or abs(atc_delta_pp) <= CONVERSION_STABLE_PP
        avg_check_stable = avg_check_delta_pct is None or abs(avg_check_delta_pct) <= rules.significant_pct_change
        has_negative_cause_signal = False
        has_positive_cause_signal = False
        if order_sum_delta < 0 and (clicks_drop or impressions_drop) and carts_drop and conversion_stable and avg_check_stable and stock_qty > 0:
            confidence = "high" if impressions_drop else "medium"
            signals.append(_build_signal(kind="traffic", direction="negative", title=f"Трафик просел по артикулу {nm_id}", summary=f"Основное снижение по артикулу {nm_id} похоже на просадку трафика: клики и корзины снизились, а конверсии и средний чек заметно не ухудшились.", check_text=f"Проверить трафик артикула {nm_id}: остаток {_format_decimal(stock_qty)}, клики {_format_decimal(traffic['baseline_clicks'].get('delta_vs_previous_day'))}, корзины {_format_decimal(traffic['baseline_carts'].get('delta_vs_previous_day'))}.", metric="traffic", trend_status=trend_status, confirmations=4 if impressions_drop else 3, confidence=confidence, partial_primary=confidence != "high", order_sum_delta=order_sum_delta, share_of_total_delta=share_negative, nm_id=nm_id, evidence=["clicks_down", "carts_down"], operational_weight=Decimal("16")))
            has_negative_cause_signal = True
        for query_row in article["search"]["queries"]:
            position_delta = _to_decimal(query_row.get("position_delta_day"))
            clicks_delta = _to_decimal(query_row.get("clicks_delta_day")) or Decimal("0")
            orders_delta = _to_decimal(query_row.get("orders_delta_day")) or Decimal("0")
            baseline_clicks = build_metric_history(query_row.get("trend_7d") or [], report_date=report_date, date_key="date", metric_key="search_clicks").get("avg_prev_7")
            if _search_query_is_significant(query_row, report_date, rules) and position_delta is not None and position_delta >= rules.search_position_change_threshold and clicks_delta < 0 and (orders_delta < 0 or (_to_decimal(query_row.get("search_orders")) or Decimal("0")) > 0):
                signals.append(_build_signal(kind="search", direction="negative", title=f"Поиск ухудшился по артикулу {nm_id}", summary=f"Поиск мог внести вклад в спад артикула {nm_id}: по запросу «{query_row.get('search_query')}» ухудшились позиция и поисковые клики.", check_text=f"Проверить индексацию артикула {nm_id} по запросу «{query_row.get('search_query')}»: позиция изменилась с {_format_decimal(query_row.get('previous_avg_position'), 1)} до {_format_decimal(query_row.get('avg_position'), 1)}, поисковые клики снизились на {_format_decimal(clicks_delta)}.", metric="search", trend_status=trend_status, confirmations=4, confidence="medium", partial_primary=False, order_sum_delta=order_sum_delta, share_of_total_delta=share_negative, nm_id=nm_id, search_query=str(query_row.get("search_query")), evidence=["position_down", "search_clicks_down"], operational_weight=Decimal("14")))
                has_negative_cause_signal = True
                break
        best_campaign = None
        for campaign in sorted(article["ads"]["campaigns"], key=lambda row: _to_decimal(row.get("ad_spend")) or Decimal("0"), reverse=True):
            spend = _to_decimal(campaign.get("ad_spend")) or Decimal("0")
            orders = _to_decimal(campaign.get("ad_orders")) or Decimal("0")
            if spend >= rules.zero_order_spend_threshold and orders == 0:
                best_campaign = campaign
                break
        if best_campaign is not None:
            signals.append(_build_signal(kind="ads", direction="negative", title=f"Реклама по артикулу {nm_id} требует проверки", summary=f"По кампании {best_campaign.get('advert_id')} есть расход без достаточного результата по артикулу {nm_id}.", check_text=f"Проверить кампанию {best_campaign.get('advert_id')} по артикулу {nm_id}: расход {_format_currency(best_campaign.get('ad_spend'))}, заказы {_format_decimal(best_campaign.get('ad_orders'))}, ДРР {_format_percent(best_campaign.get('drr'))}.", metric="ad_spend", trend_status=trend_status, confirmations=3, confidence="high", partial_primary=False, order_sum_delta=order_sum_delta, share_of_total_delta=share_negative, nm_id=nm_id, advert_id=int(best_campaign.get("advert_id")), evidence=["ad_spend", "ad_orders"], operational_weight=Decimal("13")))
            has_negative_cause_signal = True
        warehouse_rows = article["stock"]["warehouse_rows"]
        avg_orders = max((_to_decimal(row.get("avg_orders_7d_article")) or Decimal("0")) for row in warehouse_rows) if warehouse_rows else (_to_decimal(article["funnel"]["order_count_baseline"].get("avg_prev_7")) or Decimal("0"))
        warehouses_with_stock = int(article["stock"].get("warehouses_with_stock") or 0)
        warehouses_zero_stock = int(article["stock"].get("warehouses_zero_stock") or 0)
        days_of_supply = (stock_qty / avg_orders) if avg_orders > 0 else None
        if avg_orders > 0 and (stock_qty <= 0 or (days_of_supply is not None and days_of_supply <= rules.low_stock_days)) and (order_sum_delta < 0 or trend_status in {"growth_2_days", "growth_3_plus_days", "first_growth"}):
            signals.append(_build_signal(kind="stock", direction="negative", title=f"Остаток ограничивает артикул {nm_id}", summary=f"По артикулу {nm_id} есть риск дефицита: остаток {_format_decimal(stock_qty)}, средний спрос {_format_decimal(avg_orders, 1)} заказа в день.", check_text=f"Проверить остатки артикула {nm_id}: общий остаток {_format_decimal(stock_qty)}, средний спрос {_format_decimal(avg_orders, 1)}, складов с наличием {warehouses_with_stock}, складов с нулём {warehouses_zero_stock}. Оценка запаса по общей скорости артикула: {_format_decimal(days_of_supply, 0) if days_of_supply is not None else "н/д"} дней.", metric="stock_qty", trend_status=trend_status, confirmations=4, confidence="high", partial_primary=article["data_quality"].get("stock_partial") is True, order_sum_delta=order_sum_delta, share_of_total_delta=(share_negative if order_sum_delta < 0 else share_positive), nm_id=nm_id, evidence=[_format_decimal(stock_qty), _format_decimal(avg_orders, 1)], operational_weight=Decimal("18")))
            has_negative_cause_signal = True
        price = article.get("price") or {}
        current_price = _to_decimal(price.get("buyer_visible_price"))
        previous_price = _to_decimal(price.get("previous_buyer_visible_price"))
        price_delta_pct = _safe_pct_delta(current_price, previous_price)
        if price.get("source_status") == "OK" and price_delta_pct is not None and abs(price_delta_pct) >= PRICE_CHANGE_THRESHOLD_PCT and not clicks_drop and stock_qty > 0:
            order_delta_pct = _to_decimal(article["funnel"]["order_count_baseline"].get("pct_vs_previous_day"))
            if order_delta_pct is not None and order_delta_pct < 0:
                signals.append(_build_signal(kind="price", direction="negative", title=f"Цена могла повлиять на артикул {nm_id}", summary=f"После заметного изменения клиентской цены по артикулу {nm_id} просели заказы, при этом трафик и остатки не объясняют всё изменение.", check_text=f"Проверить цену артикула {nm_id}: клиентская цена изменилась с {_format_currency(previous_price)} до {_format_currency(current_price)}, заказы изменились на {_format_percent(order_delta_pct)}.", metric="buyer_visible_price", trend_status=trend_status, confirmations=3, confidence="medium", partial_primary=False, order_sum_delta=order_sum_delta, share_of_total_delta=share_negative, nm_id=nm_id, evidence=[_format_percent(price_delta_pct)], operational_weight=Decimal("11")))
                has_negative_cause_signal = True
        if order_sum_delta > 0 and trend_status in {"growth_2_days", "growth_3_plus_days", "first_growth"}:
            confirmations = 1 + (1 if (_to_decimal(traffic["baseline_clicks"].get("pct_vs_previous_day")) or Decimal("0")) > 0 else 0)
            signals.append(_build_signal(kind="article_growth", direction="positive", title=f"Артикул {nm_id} растёт", summary=f"Артикул {nm_id} дал заметный вклад в рост оборота за день.", check_text=f"Проверить, за счёт чего артикул {nm_id} растёт быстрее базы: оборот изменился на {_format_currency(order_sum_delta)}.", metric="order_sum", trend_status=trend_status, confirmations=confirmations, confidence="high", partial_primary=False, order_sum_delta=order_sum_delta, share_of_total_delta=share_positive, nm_id=nm_id, evidence=[trend_status], operational_weight=Decimal("10")))
            has_positive_cause_signal = True
        if order_sum_delta < 0 and (
            abs(order_sum_delta) >= LARGE_TURNOVER_LOSS_RUB
            or (share_negative is not None and share_negative >= LARGE_TURNOVER_SHARE_PCT)
        ):
            signals.append(_build_signal(
                kind="large_turnover_loss",
                direction="negative",
                title=f"Артикул {nm_id} дал крупную потерю оборота",
                summary=f"Артикул {nm_id} дал крупную потерю оборота на {_format_currency(order_sum_delta)}. Основная причина пока не подтверждена и требует отдельного разбора.",
                check_text=f"Разобрать артикул {nm_id}: падение оборота {_format_currency(order_sum_delta)}, вклад в общее снижение {(_format_percent(share_negative) if share_negative is not None else 'н/д')}.",
                metric="order_sum",
                trend_status=trend_status,
                confirmations=1,
                confidence="medium",
                partial_primary=False,
                order_sum_delta=order_sum_delta,
                share_of_total_delta=share_negative,
                nm_id=nm_id,
                evidence=[],
                operational_weight=Decimal("12"),
                cause_status="unconfirmed",
                supported_factors=[],
                missing_evidence=["confirmed_primary_cause"],
                recommended_check="Проверить трафик, рекламу, цену и остатки по артикулу отдельно.",
            ))
        if order_sum_delta > 0 and (
            abs(order_sum_delta) >= LARGE_TURNOVER_GROWTH_RUB
            or (share_positive is not None and share_positive >= LARGE_TURNOVER_SHARE_PCT)
        ):
            signals.append(_build_signal(
                kind="large_turnover_growth",
                direction="positive",
                title=f"Артикул {nm_id} дал заметный рост оборота",
                summary=f"Артикул {nm_id} дал заметный рост оборота на {_format_currency(order_sum_delta)}. Фактор роста требует проверки для оценки возможности масштабирования.",
                check_text=f"Разобрать артикул {nm_id}: рост оборота {_format_currency(order_sum_delta)}, вклад в общий рост {(_format_percent(share_positive) if share_positive is not None else 'н/д')}.",
                metric="order_sum",
                trend_status=trend_status,
                confirmations=1,
                confidence="medium",
                partial_primary=False,
                order_sum_delta=order_sum_delta,
                share_of_total_delta=share_positive,
                nm_id=nm_id,
                evidence=[],
                operational_weight=Decimal("9"),
                cause_status="unconfirmed",
                supported_factors=[],
                missing_evidence=["confirmed_growth_driver"],
                recommended_check="Проверить, какой фактор дал рост: трафик, цена, поиск или доступность товара.",
            ))
    signals.sort(key=lambda item: (0 if item.get("direction") == "negative" else 1, -(item.get("score") or Decimal("0")), -(abs(item.get("order_sum_delta") or Decimal("0"))), str(item.get("kind"))))
    return signals[: max(top_n * 4, 12)]



def _signal_entity_key(signal: dict[str, Any]) -> tuple[str, Any]:
    entity_type = str(signal.get("entity_type") or "unknown")
    entity_id = signal.get("entity_id")
    if entity_id is None:
        entity_id = signal.get("nm_id")
    if entity_id is None:
        entity_id = signal.get("advert_id")
    if entity_id is None:
        entity_id = signal.get("search_query")
    return entity_type, entity_id


def _support_phrase(signal: dict[str, Any]) -> str | None:
    kind = str(signal.get("kind") or "")
    return {
        "traffic": "Снижение сопровождается падением трафика.",
        "search": "Есть подтверждённое ухудшение поиска.",
        "ads": "Есть признаки ухудшения рекламного результата.",
        "stock": "Есть подтверждённый риск дефицита.",
        "price": "Есть изменение клиентской цены, требующее проверки.",
        "article_growth": "Рост сопровождается устойчивой положительной динамикой.",
    }.get(kind)

def _ensure_sentence(text: str | None) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if value[-1] in ".!?":
        return value
    return f"{value}."


def _join_sentences(*parts: str | None) -> str:
    sentences = [_ensure_sentence(part) for part in parts if str(part or "").strip()]
    return " ".join(sentence for sentence in sentences if sentence)


def _dedupe_texts(texts: Iterable[str], *, limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for text in texts:
        normalized = " ".join(str(text or "").split()).strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(str(text).strip())
        if limit is not None and len(result) >= limit:
            break
    return result


def _signal_anchor(signal: dict[str, Any]) -> str:
    if signal.get("nm_id") is not None:
        return f"\u0430\u0440\u0442\u0438\u043a\u0443\u043b {signal.get('nm_id')}"
    if signal.get("advert_id") is not None:
        return f"\u043a\u0430\u043c\u043f\u0430\u043d\u0438\u044f {signal.get('advert_id')}"
    if signal.get("search_query"):
        return f"\u0437\u0430\u043f\u0440\u043e\u0441 \xab{signal.get('search_query')}\xbb"
    if signal.get("warehouse_name"):
        return f"\u0441\u043a\u043b\u0430\u0434 {signal.get('warehouse_name')}"
    return "\u043e\u0431\u044a\u0435\u043a\u0442"


def _signal_observation(signal: dict[str, Any]) -> str | None:
    kind = str(signal.get("kind") or "")
    if kind == "traffic":
        return "\u0441\u043d\u0438\u0436\u0435\u043d\u0438\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0435\u0442\u0441\u044f \u043f\u0440\u043e\u0441\u0430\u0434\u043a\u043e\u0439 \u0442\u0440\u0430\u0444\u0438\u043a\u0430 \u0438 \u043a\u043b\u0438\u043a\u043e\u0432"
    if kind == "search":
        query = signal.get("search_query")
        if query:
            return f"\u0443\u0445\u0443\u0434\u0448\u0435\u043d\u0438\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0435\u0442\u0441\u044f \u043f\u043e\u0438\u0441\u043a\u043e\u043c \u043f\u043e \u0437\u0430\u043f\u0440\u043e\u0441\u0443 \xab{query}\xbb"
        return "\u0443\u0445\u0443\u0434\u0448\u0435\u043d\u0438\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0435\u0442\u0441\u044f \u043f\u043e\u0438\u0441\u043a\u043e\u0432\u044b\u043c\u0438 \u043c\u0435\u0442\u0440\u0438\u043a\u0430\u043c\u0438"
    if kind == "ads":
        advert_id = signal.get("advert_id")
        if advert_id is not None:
            return f"\u043a\u0430\u043c\u043f\u0430\u043d\u0438\u044f {advert_id} \u0434\u0430\u0451\u0442 \u043c\u0435\u043d\u044c\u0448\u0435 \u0437\u0430\u043a\u0430\u0437\u043e\u0432 \u043f\u0440\u0438 \u0441\u043e\u043f\u043e\u0441\u0442\u0430\u0432\u0438\u043c\u044b\u0445 \u0440\u0430\u0441\u0445\u043e\u0434\u0430\u0445"
        return "\u0440\u0435\u043a\u043b\u0430\u043c\u043d\u044b\u0439 \u043a\u0430\u043d\u0430\u043b \u0434\u0430\u0451\u0442 \u043c\u0435\u043d\u044c\u0448\u0435 \u0437\u0430\u043a\u0430\u0437\u043e\u0432"
    if kind == "stock":
        return "\u0440\u0438\u0441\u043a \u043f\u043e \u043e\u0441\u0442\u0430\u0442\u043a\u0443 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0435\u0442\u0441\u044f \u0434\u0435\u0444\u0438\u0446\u0438\u0442\u043e\u043c \u0438 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u0438\u044f\u043c\u0438 \u043f\u043e \u0441\u043a\u043b\u0430\u0434\u0430\u043c"
    if kind == "price":
        return "\u0438\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435 \u0432\u0438\u0434\u0438\u043c\u043e\u0439 \u0446\u0435\u043d\u044b \u0442\u0440\u0435\u0431\u0443\u0435\u0442 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438"
    if kind == "article_growth":
        return "\u0440\u043e\u0441\u0442 \u0434\u0435\u0440\u0436\u0438\u0442\u0441\u044f \u043d\u0435\u0441\u043a\u043e\u043b\u044c\u043a\u043e \u0434\u043d\u0435\u0439 \u0438 \u0447\u0430\u0441\u0442\u0438\u0447\u043d\u043e \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0435\u0442\u0441\u044f \u0441\u043f\u0440\u043e\u0441\u043e\u043c"
    if kind == "large_turnover_loss":
        return "\u044d\u0442\u043e \u043e\u0434\u0438\u043d \u0438\u0437 \u043a\u0440\u0443\u043f\u043d\u0435\u0439\u0448\u0438\u0445 \u0432\u043a\u043b\u0430\u0434\u043e\u0432 \u0432 \u043e\u0431\u0449\u0435\u0435 \u0441\u043d\u0438\u0436\u0435\u043d\u0438\u0435 \u043e\u0431\u043e\u0440\u043e\u0442\u0430"
    if kind == "large_turnover_growth":
        return "\u044d\u0442\u043e \u043e\u0434\u0438\u043d \u0438\u0437 \u043a\u0440\u0443\u043f\u043d\u0435\u0439\u0448\u0438\u0445 \u0432\u043a\u043b\u0430\u0434\u043e\u0432 \u0432 \u043e\u0431\u0449\u0438\u0439 \u0440\u043e\u0441\u0442 \u043e\u0431\u043e\u0440\u043e\u0442\u0430"
    return None


def _signal_effect(signal: dict[str, Any]) -> str:
    impact = _to_decimal(signal.get("impact_rub"))
    direction = str(signal.get("direction") or "")
    anchor = _signal_anchor(signal)
    if impact is None or impact == 0:
        return str(signal.get("summary") or signal.get("title") or anchor)
    if direction == "negative":
        return f"{anchor} \u0434\u0430\u043b \u043f\u043e\u0442\u0435\u0440\u044e \u043e\u0431\u043e\u0440\u043e\u0442\u0430 {_format_currency(impact)}"
    if direction == "positive":
        return f"{anchor} \u0434\u0430\u043b \u043f\u0440\u0438\u0440\u043e\u0441\u0442 \u043e\u0431\u043e\u0440\u043e\u0442\u0430 {_format_currency(impact)}"
    return str(signal.get("summary") or signal.get("title") or anchor)


def _signal_recommended_action(signal: dict[str, Any]) -> str | None:
    check = signal.get("check") if isinstance(signal.get("check"), dict) else {}
    text = check.get("text") if isinstance(check, dict) else None
    return str(text or signal.get("recommended_check") or "").strip() or None


def _supporting_observations(signal: dict[str, Any]) -> list[str]:
    observations: list[str] = []
    primary = _signal_observation(signal)
    if primary:
        observations.append(primary)
    for item in signal.get("supporting_signals") or []:
        if not isinstance(item, dict):
            continue
        observation = _signal_observation(item)
        if observation:
            observations.append(observation)
    return _dedupe_texts(observations, limit=3)


def _build_priority_narrative(signal: dict[str, Any]) -> dict[str, Any]:
    observations = _supporting_observations(signal)
    sentences = [_signal_effect(signal)]
    if observations:
        sentences.append(", ".join(observations[:2]).capitalize())
    elif signal.get("cause_status") != "confirmed":
        sentences.append("\u041f\u0440\u0438\u0447\u0438\u043d\u0430 \u0442\u0440\u0435\u0431\u0443\u0435\u0442 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438 \u043f\u043e \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0451\u043d\u043d\u044b\u043c \u0441\u043b\u043e\u044f\u043c")
    action = _signal_recommended_action(signal)
    if action:
        sentences.append(action)
    return {
        "entity_type": signal.get("entity_type"),
        "entity_id": signal.get("entity_id"),
        "nm_id": signal.get("nm_id"),
        "advert_id": signal.get("advert_id"),
        "search_query": signal.get("search_query"),
        "warehouse_name": signal.get("warehouse_name"),
        "kind": signal.get("kind"),
        "impact_rub": signal.get("impact_rub"),
        "text": _join_sentences(*sentences),
        "action": action,
        "supporting_signals": list(signal.get("supporting_signals") or []),
        "supported_factors": list(signal.get("supported_factors") or []),
        "evidence": list(signal.get("evidence") or []),
    }


def _pick_first_signal(
    signals: Sequence[dict[str, Any]],
    *,
    kinds: set[str] | None = None,
    supported_factors: set[str] | None = None,
    direction: str | None = None,
) -> dict[str, Any] | None:
    for signal in signals:
        if direction and signal.get("direction") != direction:
            continue
        if kinds and str(signal.get("kind") or "") in kinds:
            return signal
        if supported_factors and any(str(item) in supported_factors for item in (signal.get("supported_factors") or [])):
            return signal
        if supported_factors:
            for item in signal.get("supporting_signals") or []:
                if isinstance(item, dict) and str(item.get("kind") or "") in supported_factors:
                    return signal
    return None


def _build_section_narratives(
    business_priorities: Sequence[dict[str, Any]],
    article_analysis: Sequence[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    narratives: dict[str, dict[str, str]] = {}
    article_by_nm = {int(item.get("nm_id")): item for item in article_analysis if item.get("nm_id") is not None}
    visible_signals = [signal for signal in business_priorities if signal.get("user_visible")]
    main_negative = next((signal for signal in visible_signals if signal.get("direction") == "negative"), None)
    main_positive = next((signal for signal in visible_signals if signal.get("direction") == "positive"), None)

    traffic_signal = _pick_first_signal(visible_signals, kinds={"traffic"}, direction="negative")
    if traffic_signal:
        narratives["traffic"] = {
            "comment": _join_sentences(
                _signal_effect(traffic_signal),
                "\u041f\u0430\u0434\u0435\u043d\u0438\u0435 \u0432\u0438\u0434\u043d\u043e \u043f\u0440\u0435\u0436\u0434\u0435 \u0432\u0441\u0435\u0433\u043e \u0432 \u0441\u043e\u043a\u0440\u0430\u0449\u0435\u043d\u0438\u0438 \u043a\u0430\u0440\u0442\u043e\u0447\u043d\u044b\u0445 \u043a\u043b\u0438\u043a\u043e\u0432 \u0438 \u043f\u043e\u043a\u0430\u0437\u043e\u0432",
            ),
            "action": _signal_recommended_action(traffic_signal) or "",
        }
        narratives["funnel"] = {
            "comment": _join_sentences(
                f"\u041f\u043e {_signal_anchor(traffic_signal)} \u0441\u043d\u0438\u0436\u0430\u0435\u0442\u0441\u044f \u0432\u0445\u043e\u0434\u044f\u0449\u0438\u0439 \u043f\u043e\u0442\u043e\u043a \u0432 \u0432\u043e\u0440\u043e\u043d\u043a\u0443",
                "\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043f\u0430\u0434\u0430\u0435\u0442 \u0442\u0440\u0430\u0444\u0438\u043a \u0432 \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0443, \u0430 \u043a\u043e\u043d\u0432\u0435\u0440\u0441\u0438\u044f \u0432 \u043a\u043e\u0440\u0437\u0438\u043d\u0443 \u0443\u0436\u0435 \u043d\u0435 \u043a\u043e\u043c\u043f\u0435\u043d\u0441\u0438\u0440\u0443\u0435\u0442 \u0441\u043d\u0438\u0436\u0435\u043d\u0438\u0435",
            ),
            "action": _signal_recommended_action(traffic_signal) or "",
        }

    ads_signal = _pick_first_signal(visible_signals, kinds={"ads"}, direction="negative")
    if ads_signal:
        advert_id = ads_signal.get("advert_id")
        narratives["ads"] = {
            "comment": _join_sentences(
                _signal_effect(ads_signal),
                f"\u0421\u043b\u0430\u0431\u043e\u0435 \u043c\u0435\u0441\u0442\u043e \u0444\u0438\u043a\u0441\u0438\u0440\u0443\u0435\u0442\u0441\u044f \u0432 \u043a\u0430\u043c\u043f\u0430\u043d\u0438\u0438 {advert_id}" if advert_id is not None else "\u0421\u043d\u0438\u0436\u0435\u043d\u0438\u0435 \u0441\u0432\u044f\u0437\u0430\u043d\u043e \u0441 \u0443\u0445\u0443\u0434\u0448\u0435\u043d\u0438\u0435\u043c \u0440\u0435\u043a\u043b\u0430\u043c\u043d\u043e\u0439 \u044d\u0444\u0444\u0435\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u0438",
            ),
            "action": _signal_recommended_action(ads_signal) or "",
        }

    stock_signal = _pick_first_signal(visible_signals, kinds={"stock"})
    if stock_signal and stock_signal.get("nm_id") is not None:
        article = article_by_nm.get(int(stock_signal.get("nm_id")))
        stock = (article or {}).get("stock") or {}
        stock_qty = stock.get("stock_qty_same_day")
        with_stock = stock.get("warehouses_with_stock")
        zero_stock = stock.get("warehouses_zero_stock")
        narratives["stock"] = {
            "comment": _join_sentences(
                f"\u041f\u043e \u0430\u0440\u0442\u0438\u043a\u0443\u043b\u0443 {stock_signal.get('nm_id')} \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0435\u0442\u0441\u044f \u0440\u0438\u0441\u043a \u043f\u043e \u043e\u0441\u0442\u0430\u0442\u043a\u0443: \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e {_format_decimal(stock_qty)}",
                f"\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e\u0441\u0442\u044c \u043f\u043e \u0441\u043a\u043b\u0430\u0434\u0430\u043c \u0442\u043e\u0436\u0435 \u0432\u0438\u0434\u043d\u0430: \u0432 \u043d\u0430\u043b\u0438\u0447\u0438\u0438 {with_stock}, \u0431\u0435\u0437 \u043e\u0441\u0442\u0430\u0442\u043a\u043e\u0432 {zero_stock}",
            ),
            "action": _signal_recommended_action(stock_signal) or "",
        }

    search_signal = _pick_first_signal(visible_signals, kinds={"search"}, direction="negative")
    if search_signal:
        query = search_signal.get("search_query")
        narratives["search"] = {
            "comment": _join_sentences(
                _signal_effect(search_signal),
                f"\u0412 \u043f\u043e\u0438\u0441\u043a\u0435 \u0442\u043e\u0432\u0430\u0440 \u0447\u0430\u0449\u0435 \u0442\u0435\u0440\u044f\u0435\u0442 \u0432\u0438\u0434\u0438\u043c\u043e\u0441\u0442\u044c \u043f\u043e \u0437\u0430\u043f\u0440\u043e\u0441\u0443 \xab{query}\xbb" if query else None,
            ),
            "action": _signal_recommended_action(search_signal) or "",
        }

    price_signal = _pick_first_signal(visible_signals, kinds={"price"}, direction="negative")
    if price_signal:
        narratives["sales"] = {
            "comment": _join_sentences(
                _signal_effect(price_signal),
                "\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u0435 \u043a\u043b\u0438\u0435\u043d\u0442\u0441\u043a\u043e\u0439 \u0446\u0435\u043d\u044b \u0441\u0442\u043e\u0438\u0442 \u0441\u043e\u043f\u043e\u0441\u0442\u0430\u0432\u0438\u0442\u044c \u0441 \u044d\u043b\u0430\u0441\u0442\u0438\u0447\u043d\u043e\u0441\u0442\u044c\u044e \u0441\u043f\u0440\u043e\u0441\u0430 \u0438 \u0442\u0435\u043a\u0443\u0449\u0435\u0439 \u0433\u043b\u0443\u0431\u0438\u043d\u043e\u0439 \u0441\u043a\u0438\u0434\u043a\u0438",
            ),
            "action": _signal_recommended_action(price_signal) or "",
        }
    elif main_negative or main_positive:
        comments: list[str] = []
        if main_negative:
            comments.append(_signal_effect(main_negative))
        if main_positive and main_positive is not main_negative:
            comments.append(f"\u041f\u043e\u043b\u043e\u0436\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0439 \u0432\u043a\u043b\u0430\u0434 \u0434\u0430\u043b {_signal_anchor(main_positive)} \u0441 \u043f\u0440\u0438\u0440\u043e\u0441\u0442\u043e\u043c {_format_currency(main_positive.get('impact_rub'))}")
        narratives["sales"] = {
            "comment": _join_sentences(*comments),
            "action": _signal_recommended_action(main_negative or main_positive or {}) or "",
        }

    assortment_negative = next(
        (
            signal
            for signal in visible_signals
            if signal.get("direction") == "negative" and signal.get("nm_id") is not None
        ),
        None,
    )
    assortment_positive = next(
        (
            signal
            for signal in visible_signals
            if signal.get("direction") == "positive" and signal.get("nm_id") is not None
        ),
        None,
    )
    if assortment_negative or assortment_positive:
        comment_parts: list[str] = []
        if assortment_negative:
            comment_parts.append(_signal_effect(assortment_negative))
        if assortment_positive and assortment_positive is not assortment_negative:
            comment_parts.append(
                f"\u041f\u0440\u0438 \u044d\u0442\u043e\u043c \u0430\u0440\u0442\u0438\u043a\u0443\u043b {assortment_positive.get('nm_id')} \u043d\u0430 {_format_currency(assortment_positive.get('impact_rub'))} \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u0442 \u043e\u0431\u0449\u0438\u0439 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442"
            )
        narratives["assortment"] = {
            "comment": _join_sentences(*comment_parts),
            "action": _signal_recommended_action(assortment_negative or assortment_positive or {}) or "",
        }

    if main_negative and "sales" not in narratives:
        narratives["sales"] = {
            "comment": _ensure_sentence(str(main_negative.get("summary") or main_negative.get("title") or "")),
            "action": _signal_recommended_action(main_negative) or "",
        }

    return {key: value for key, value in narratives.items() if value.get("comment")}


def _build_scenario_narrative(
    business_priorities: Sequence[dict[str, Any]],
    priority_narratives: Sequence[dict[str, Any]],
) -> str:
    visible_signals = [signal for signal in business_priorities if signal.get("user_visible")]
    negative = [signal for signal in visible_signals if signal.get("direction") == "negative"]
    positive = [signal for signal in visible_signals if signal.get("direction") == "positive"]
    losses = [str(signal.get("nm_id")) for signal in negative if signal.get("nm_id") is not None][:3]
    parts: list[str] = []
    if losses:
        parts.append(f"\u041f\u043e\u0434 \u043e\u0441\u043d\u043e\u0432\u043d\u044b\u043c \u0440\u0438\u0441\u043a\u043e\u043c \u0434\u043d\u044f \u043d\u0430\u0445\u043e\u0434\u044f\u0442\u0441\u044f \u0442\u043e\u0432\u0430\u0440\u044b, \u043a\u043e\u0442\u043e\u0440\u044b\u0435 \u0441\u0438\u043b\u044c\u043d\u0435\u0435 \u0432\u0441\u0435\u0433\u043e \u0442\u044f\u043d\u0443\u0442 \u043e\u0431\u043e\u0440\u043e\u0442 \u0432\u043d\u0438\u0437: {', '.join(losses)}")
    elif negative:
        parts.append(f"\u0413\u043b\u0430\u0432\u043d\u044b\u0439 \u0440\u0438\u0441\u043a \u0434\u043d\u044f \u0441\u0435\u0439\u0447\u0430\u0441 \u0441\u0432\u044f\u0437\u0430\u043d \u0441 {_signal_anchor(negative[0])}")
    if positive:
        parts.append(f"\u041f\u043e\u043b\u043e\u0436\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0439 \u0438\u043c\u043f\u0443\u043b\u044c\u0441 \u0434\u0430\u0451\u0442 {_signal_anchor(positive[0])}, \u043d\u043e \u043e\u043d \u043f\u043e\u043a\u0430 \u043d\u0435 \u043a\u043e\u043c\u043f\u0435\u043d\u0441\u0438\u0440\u0443\u0435\u0442 \u0432\u0441\u0435 \u0442\u043e\u0447\u043a\u0438 \u0441\u043d\u0438\u0436\u0435\u043d\u0438\u044f")
    first_action = next((item.get("action") for item in priority_narratives if item.get("action")), None)
    if first_action:
        parts.append(f"\u041f\u0435\u0440\u0432\u044b\u043c \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435\u043c \u0441\u0442\u043e\u0438\u0442 {str(first_action).rstrip('.')}")
    return _join_sentences(*parts)


def _build_action_items(priority_narratives: Sequence[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in priority_narratives:
        action = str(item.get("action") or "").strip()
        if not action:
            continue
        normalized = " ".join(action.split()).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        items.append(
            {
                "text": action,
                "entity_type": item.get("entity_type"),
                "entity_id": item.get("entity_id"),
                "nm_id": item.get("nm_id"),
                "advert_id": item.get("advert_id"),
                "search_query": item.get("search_query"),
                "warehouse_name": item.get("warehouse_name"),
            }
        )
        if len(items) >= limit:
            break
    return items


def _merge_business_priorities(ranked_signals: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, Any], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, signal in enumerate(ranked_signals):
        grouped[_signal_entity_key(signal)].append((index, signal))

    merged_rows: list[tuple[int, dict[str, Any]]] = []
    for group_rows in grouped.values():
        signals = [signal for _, signal in group_rows]
        if not any(signal.get("user_visible") for signal in signals):
            continue
        confirmed_causal = [
            signal
            for signal in signals
            if signal.get("cause_status") == "confirmed" and not signal.get("partial_primary") and signal.get("kind") not in {"large_turnover_loss", "large_turnover_growth"}
        ]
        if confirmed_causal:
            main_signal = max(
                confirmed_causal,
                key=lambda item: (item.get("score") or Decimal("0"), abs(item.get("impact_rub") or Decimal("0"))),
            )
        else:
            main_signal = max(
                signals,
                key=lambda item: (abs(item.get("impact_rub") or Decimal("0")), item.get("score") or Decimal("0")),
            )
        impact_signal = max(
            signals,
            key=lambda item: (abs(item.get("impact_rub") or Decimal("0")), item.get("score") or Decimal("0")),
        )
        merged_signal = dict(main_signal)
        merged_signal["user_visible"] = any(signal.get("user_visible") for signal in signals)
        supporting = [signal for signal in signals if signal is not main_signal]
        merged_signal["impact_rub"] = impact_signal.get("impact_rub")
        merged_signal["order_sum_delta"] = impact_signal.get("impact_rub")
        merged_signal["supporting_signals"] = [
            {
                "kind": signal.get("kind"),
                "title": signal.get("title"),
                "summary": signal.get("summary"),
                "cause_status": signal.get("cause_status"),
                "impact_rub": signal.get("impact_rub"),
                "confidence": signal.get("confidence"),
            }
            for signal in supporting
        ]
        supported_factors: list[str] = []
        evidence: list[str] = []
        for signal in [main_signal, *supporting]:
            for value in signal.get("supported_factors") or []:
                if value and value not in supported_factors:
                    supported_factors.append(str(value))
            if signal is not main_signal and signal.get("cause_status") == "confirmed":
                kind = str(signal.get("kind") or "")
                if kind and kind not in supported_factors:
                    supported_factors.append(kind)
            for value in signal.get("evidence") or []:
                if value and value not in evidence:
                    evidence.append(str(value))
        merged_signal["supported_factors"] = supported_factors
        merged_signal["evidence"] = evidence
        summary_parts: list[str] = []
        impact_summary = impact_signal.get("summary")
        if impact_summary:
            summary_parts.append(str(impact_summary))
        if main_signal is not impact_signal and main_signal.get("cause_status") == "confirmed":
            phrase = _support_phrase(main_signal)
            if phrase and phrase not in summary_parts:
                summary_parts.append(phrase)
        for signal in supporting:
            if signal.get("cause_status") != "confirmed":
                continue
            phrase = _support_phrase(signal)
            if phrase and phrase not in summary_parts:
                summary_parts.append(phrase)
        if summary_parts:
            merged_signal["summary"] = " ".join(summary_parts)
        check_texts: list[str] = []
        for signal in [main_signal, *supporting]:
            text = ((signal.get("check") or {}).get("text") if isinstance(signal.get("check"), dict) else None) or signal.get("recommended_check")
            if text and text not in check_texts:
                check_texts.append(str(text))
        if check_texts:
            merged_signal["check"] = dict(merged_signal.get("check") or {})
            merged_signal["check"]["text"] = check_texts[0]
            merged_signal["recommended_check"] = check_texts[0]
        merged_signal["recommended_checks"] = list(check_texts)
        missing_evidence: list[str] = []
        for signal in [main_signal, *supporting]:
            for value in signal.get("missing_evidence") or []:
                if value and value not in missing_evidence:
                    missing_evidence.append(str(value))
        merged_signal["missing_evidence"] = missing_evidence
        merged_signal["primary_signal"] = {
            "kind": main_signal.get("kind"),
            "title": main_signal.get("title"),
            "summary": main_signal.get("summary"),
            "cause_status": main_signal.get("cause_status"),
            "impact_rub": main_signal.get("impact_rub"),
            "recommended_check": _signal_recommended_action(main_signal),
        }
        merged_rows.append((min(index for index, _ in group_rows), merged_signal))

    merged_rows.sort(key=lambda item: item[0])
    return [row for _, row in merged_rows]


def _build_analysis_summary(
    business_priorities: Sequence[dict[str, Any]],
    anomalies: Sequence[dict[str, Any]],
    article_analysis: Sequence[dict[str, Any]],
    top_n: int,
) -> dict[str, Any]:
    negative_signals = [signal for signal in business_priorities if signal.get("direction") == "negative" and signal.get("user_visible")]
    positive_signals = [signal for signal in business_priorities if signal.get("direction") == "positive" and signal.get("user_visible")]
    main_problem = next((signal for signal in negative_signals if signal.get("kind") != "anomaly"), negative_signals[0] if negative_signals else None)
    main_growth = positive_signals[0] if positive_signals else None
    priority_checks = [signal.get("check") for signal in negative_signals[:top_n] if signal.get("check")]
    preferred_priority_signals = [
        signal
        for signal in business_priorities
        if signal.get("user_visible") and signal.get("entity_type") in {"product", "campaign", "query"}
    ]
    if len(preferred_priority_signals) < min(top_n, 3):
        preferred_priority_signals = [signal for signal in business_priorities if signal.get("user_visible")]
    priority_narratives = [_build_priority_narrative(signal) for signal in preferred_priority_signals[:top_n]]
    section_narratives = _build_section_narratives(business_priorities, article_analysis)
    scenario_narrative = _build_scenario_narrative(business_priorities, priority_narratives)
    user_worse = _dedupe_texts([str(main_problem.get("summary"))] if main_problem else [], limit=top_n)
    user_better = _dedupe_texts([str(main_growth.get("summary"))] if main_growth else [], limit=top_n)
    return {
        "main_problem": main_problem,
        "main_growth": main_growth,
        "priority_checks": priority_checks,
        "user_worse": user_worse,
        "user_better": user_better,
        "section_narratives": section_narratives,
        "priority_narratives": priority_narratives,
        "scenario_narrative": scenario_narrative,
        "action_items": _build_action_items(priority_narratives, limit=top_n),
        "top_anomalies": list(anomalies[:top_n]),
        "data_quality_checks": [str(item.get("summary")) for item in anomalies[:top_n]],
    }


def build_highlights_from_analysis(analysis_payload: dict[str, Any], *, top_n: int) -> WbDailyOperationalHighlightsResponse:
    summary = analysis_payload.get("analysis_summary") or {}
    action_items = summary.get("action_items") or []
    legacy_checks = summary.get("priority_checks") or []
    priority_checks = _dedupe_texts(
        [str(item.get("text")) for item in action_items if item and item.get("text")]
        or [str(item.get("text")) for item in legacy_checks if item and item.get("text")],
        limit=top_n,
    )
    return WbDailyOperationalHighlightsResponse(
        worse=_dedupe_texts(summary.get("user_worse") or [], limit=top_n),
        better=_dedupe_texts(summary.get("user_better") or [], limit=top_n),
        priority_checks=priority_checks,
    )


def build_internal_analysis(*, report_date: date, daily_rows: Sequence[dict[str, Any]], article_context: Sequence[dict[str, Any]], warehouse_context: Sequence[dict[str, Any]], campaign_context: Sequence[dict[str, Any]], search_query_context: Sequence[dict[str, Any]], entry_point_context: Sequence[dict[str, Any]], price_context: Sequence[dict[str, Any]], logistics_context: Sequence[dict[str, Any]], database_audit: dict[str, Any] | None = None, operating_profit_context: dict[str, Any] | None = None, logistics_summary: dict[str, Any] | None = None, pricing_spp_context: dict[str, Any] | None = None, competitor_context: dict[str, Any] | None = None, additional_data_candidates: Sequence[dict[str, Any]] | None = None, data_gaps: Sequence[dict[str, Any]] = (), rules: WbDailyOperationalSummaryRules, top_n: int = 5) -> dict[str, Any]:
    article_analysis, analysis_gaps = build_article_analysis(
        report_date=report_date,
        article_context=article_context,
        warehouse_context=warehouse_context,
        campaign_context=campaign_context,
        search_query_context=search_query_context,
        entry_point_context=entry_point_context,
        price_context=price_context,
        logistics_context=logistics_context,
        data_gaps=data_gaps,
    )
    aggregate_gaps: list[dict[str, Any]] = []
    for metric_name in ("order_sum", "order_count", "card_clicks", "impressions"):
        history = build_metric_history(daily_rows, report_date=report_date, date_key="report_date", metric_key=metric_name)
        if history.get("avg_prev_7") is None:
            aggregate_gaps.append(_history_gap(metric_name, "aggregate"))
    anomalies = _build_data_anomalies(report_date=report_date, article_analysis=article_analysis, top_n=top_n)
    ranked_signals = _build_ranked_signals(report_date=report_date, daily_rows=daily_rows, article_analysis=article_analysis, anomalies=anomalies, rules=rules, top_n=top_n)
    business_priorities = _merge_business_priorities(ranked_signals)
    analysis_summary = _build_analysis_summary(business_priorities, anomalies, article_analysis, top_n)
    return {
        "article_analysis": article_analysis,
        "business_priorities": business_priorities,
        "ranked_signals": ranked_signals,
        "data_anomalies": list(anomalies),
        "analysis_summary": analysis_summary,
        "data_gaps": analysis_gaps + aggregate_gaps,
    }


