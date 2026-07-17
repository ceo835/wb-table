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
        return "РЅ/Рґ"
    quant = Decimal("1") if decimals == 0 else Decimal("1." + ("0" * decimals))
    return f"{decimal_value.quantize(quant):,.{decimals}f}".replace(",", " ")


def _format_currency(value: Any) -> str:
    return f"{_format_decimal(value, 0)} в‚Ѕ"


def _format_percent(value: Any, decimals: int = 1) -> str:
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return "РЅ/Рґ"
    prefix = "+" if decimal_value > 0 else ""
    return f"{prefix}{_format_decimal(decimal_value, decimals)}%"


def _format_pp(value: Any, decimals: int = 1) -> str:
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return "РЅ/Рґ"
    prefix = "+" if decimal_value > 0 else ""
    return f"{prefix}{_format_decimal(decimal_value, decimals)} Рї.Рї."


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
        "message": "РќРµРґРѕСЃС‚Р°С‚РѕС‡РЅРѕ РїСЂРµРґС‹РґСѓС‰РёС… РїРѕР»РЅС‹С… РґРЅРµР№ РґР»СЏ СѓСЃС‚РѕР№С‡РёРІРѕРіРѕ baseline 7/14.",
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


def _build_signal(*, kind: str, direction: str, title: str, summary: str, check_text: str, metric: str, trend_status: str, confirmations: int, confidence: str, partial_primary: bool, order_sum_delta: Decimal | None = None, share_of_total_delta: Decimal | None = None, nm_id: int | None = None, advert_id: int | None = None, search_query: str | None = None, warehouse_name: str | None = None, evidence: list[str] | None = None, operational_weight: Decimal = Decimal("10")) -> dict[str, Any]:
    delta_component = min(abs(order_sum_delta or Decimal("0")) / Decimal("1000"), Decimal("35"))
    share_component = min(abs(share_of_total_delta or Decimal("0")), Decimal("100")) / Decimal("4")
    score = delta_component + share_component + _trend_weight(trend_status) + Decimal(confirmations * 4) + operational_weight + _quality_penalty(partial_primary)
    return {
        "kind": kind,
        "direction": direction,
        "nm_id": nm_id,
        "advert_id": advert_id,
        "search_query": search_query,
        "warehouse_name": warehouse_name,
        "metric": metric,
        "title": title,
        "summary": summary,
        "check": {"text": check_text, "nm_id": nm_id, "advert_id": advert_id, "search_query": search_query, "warehouse": warehouse_name, "metric": metric},
        "order_sum_delta": order_sum_delta,
        "share_of_total_delta": share_of_total_delta,
        "trend_status": trend_status,
        "confirmations": confirmations,
        "confidence": confidence,
        "score": score,
        "partial_primary": partial_primary,
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
                anomalies.append({"kind": "search_low_traffic_position_jump", "nm_id": nm_id, "search_query": query_row.get("search_query"), "severity": "medium", "summary": f"Р РµР·РєРёР№ СЃРєР°С‡РѕРє РїРѕР·РёС†РёРё РїРѕ Р·Р°РїСЂРѕСЃСѓ В«{query_row.get('search_query')}В» РїСЂРё РјР°Р»РѕРј Р±Р°Р·РѕРІРѕРј С‚СЂР°С„РёРєРµ. РќСѓР¶РЅР° РїСЂРѕРІРµСЂРєР° РґР°РЅРЅС‹С…."})
            if position_delta is not None and position_delta >= POSITION_JUMP_ANOMALY and (_to_decimal(query_row.get("clicks_delta_day")) or Decimal("0")) >= 0 and (_to_decimal(query_row.get("orders_delta_day")) or Decimal("0")) >= 0:
                anomalies.append({"kind": "search_position_without_traffic_drop", "nm_id": nm_id, "search_query": query_row.get("search_query"), "severity": "medium", "summary": f"РџРѕР·РёС†РёСЏ РїРѕ Р·Р°РїСЂРѕСЃСѓ В«{query_row.get('search_query')}В» СЂРµР·РєРѕ СѓС…СѓРґС€РёР»Р°СЃСЊ, РЅРѕ С‚СЂР°С„РёРє РЅРµ РїРѕРґС‚РІРµСЂРґРёР» РїР°РґРµРЅРёРµ."})
            if current_visibility == Decimal("0") and current_clicks > 0:
                anomalies.append({"kind": "search_zero_visibility_with_clicks", "nm_id": nm_id, "search_query": query_row.get("search_query"), "severity": "high", "summary": f"РќСѓР»РµРІР°СЏ РІРёРґРёРјРѕСЃС‚СЊ РїРѕ Р·Р°РїСЂРѕСЃСѓ В«{query_row.get('search_query')}В» РЅРµ СЃРѕРІРїР°РґР°РµС‚ СЃ РїРѕР»РѕР¶РёС‚РµР»СЊРЅС‹РјРё РєР»РёРєР°РјРё."})
        if (article["traffic"].get("cart_count") or Decimal("0")) == 0 and (article["sales"].get("order_count") or Decimal("0")) > 0:
            anomalies.append({"kind": "orders_without_carts", "nm_id": nm_id, "severity": "high", "summary": f"РЈ Р°СЂС‚РёРєСѓР»Р° {nm_id} РµСЃС‚СЊ Р·Р°РєР°Р·С‹ РїСЂРё РЅСѓР»РµРІС‹С… РєРѕСЂР·РёРЅР°С…."})
        for campaign in article["ads"]["campaigns"]:
            if (_to_decimal(campaign.get("ad_spend")) or Decimal("0")) > 0 and (_to_decimal(campaign.get("ad_views")) or Decimal("0")) == 0 and (_to_decimal(campaign.get("ad_clicks")) or Decimal("0")) == 0:
                anomalies.append({"kind": "ad_spend_without_reach", "nm_id": nm_id, "advert_id": campaign.get("advert_id"), "severity": "high", "summary": f"РџРѕ РєР°РјРїР°РЅРёРё {campaign.get('advert_id')} РµСЃС‚СЊ СЂР°СЃС…РѕРґ Р±РµР· РїРѕРєР°Р·РѕРІ Рё РєР»РёРєРѕРІ."})
        if (article["stock"].get("stock_qty_same_day") or Decimal("0")) == 0 and (article["sales"].get("order_count") or Decimal("0")) > 0:
            anomalies.append({"kind": "zero_stock_with_orders", "nm_id": nm_id, "severity": "high", "summary": f"РЈ Р°СЂС‚РёРєСѓР»Р° {nm_id} РЅСѓР»РµРІРѕР№ РѕСЃС‚Р°С‚РѕРє РїСЂРё РїСЂРѕРґРѕР»Р¶Р°СЋС‰РёС…СЃСЏ Р·Р°РєР°Р·Р°С…."})
        price = article.get("price") or {}
        previous_price = _to_decimal(price.get("previous_buyer_visible_price"))
        current_price = _to_decimal(price.get("buyer_visible_price"))
        price_delta_pct = _safe_pct_delta(current_price, previous_price)
        if price_delta_pct is not None and abs(price_delta_pct) >= PRICE_CHANGE_THRESHOLD_PCT:
            anomalies.append({"kind": "sharp_price_change", "nm_id": nm_id, "severity": "medium", "summary": f"РЈ Р°СЂС‚РёРєСѓР»Р° {nm_id} С†РµРЅР° РёР·РјРµРЅРёР»Р°СЃСЊ РЅР° {_format_percent(price_delta_pct)} Р·Р° РґРµРЅСЊ."})
    anomalies.sort(key=lambda item: {"high": 0, "medium": 1, "low": 2}.get(str(item.get("severity")), 3))
    return anomalies[: max(top_n * 2, top_n)]


def _build_ranked_signals(*, report_date: date, daily_rows: Sequence[dict[str, Any]], article_analysis: Sequence[dict[str, Any]], anomalies: Sequence[dict[str, Any]], rules: WbDailyOperationalSummaryRules, top_n: int) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    total_negative_delta = sum(abs((_to_decimal(row["sales"]["baseline"].get("delta_vs_previous_day")) or Decimal("0"))) for row in article_analysis if (_to_decimal(row["sales"]["baseline"].get("delta_vs_previous_day")) or Decimal("0")) < 0)
    total_positive_delta = sum(abs((_to_decimal(row["sales"]["baseline"].get("delta_vs_previous_day")) or Decimal("0"))) for row in article_analysis if (_to_decimal(row["sales"]["baseline"].get("delta_vs_previous_day")) or Decimal("0")) > 0)
    aggregate_sales = build_metric_history(daily_rows, report_date=report_date, date_key="report_date", metric_key="order_sum")
    delta = _to_decimal(aggregate_sales.get("delta_vs_previous_day")) or Decimal("0")
    if delta < 0 and aggregate_sales.get("trend_status") not in {"return_to_baseline", "previous_day_spike"}:
        signals.append(_build_signal(kind="aggregate_sales", direction="negative", title="РћР±С‰РёР№ СЃРїР°Рґ РѕР±РѕСЂРѕС‚Р°", summary=f"РћР±РѕСЂРѕС‚ Р·Р°РєР°Р·РѕРІ СЃРЅРёР¶Р°РµС‚СЃСЏ СѓСЃС‚РѕР№С‡РёРІРµРµ РѕР±С‹С‡РЅРѕРіРѕ: {_format_currency(aggregate_sales.get('current'))} РїСЂРѕС‚РёРІ {_format_currency(aggregate_sales.get('previous_day'))}.", check_text="РџСЂРѕРІРµСЂРёС‚СЊ СЃРѕРІРѕРєСѓРїРЅС‹Р№ РІРєР»Р°Рґ С‚СЂР°С„РёРєР°, РїРѕРёСЃРєР° Рё СЂРµРєР»Р°РјС‹ РІ СЃРїР°Рґ РѕР±РѕСЂРѕС‚Р°.", metric="order_sum", trend_status=str(aggregate_sales.get("trend_status")), confirmations=2, confidence="high", partial_primary=False, order_sum_delta=delta, share_of_total_delta=Decimal("100"), operational_weight=Decimal("8")))
    elif delta > 0 and aggregate_sales.get("trend_status") in {"growth_2_days", "growth_3_plus_days", "first_growth"}:
        signals.append(_build_signal(kind="aggregate_sales", direction="positive", title="РћР±С‰РёР№ СЂРѕСЃС‚ РѕР±РѕСЂРѕС‚Р°", summary=f"РћР±РѕСЂРѕС‚ Р·Р°РєР°Р·РѕРІ РІС‹СЂРѕСЃ РґРѕ {_format_currency(aggregate_sales.get('current'))}.", check_text="РџСЂРѕРІРµСЂРёС‚СЊ, РєР°РєРёРµ Р°СЂС‚РёРєСѓР»С‹ РґР°Р»Рё РѕСЃРЅРѕРІРЅРѕР№ РІРєР»Р°Рґ РІ СЂРѕСЃС‚ РѕР±РѕСЂРѕС‚Р°.", metric="order_sum", trend_status=str(aggregate_sales.get("trend_status")), confirmations=2, confidence="high", partial_primary=False, order_sum_delta=delta, share_of_total_delta=Decimal("100"), operational_weight=Decimal("8")))

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
        if order_sum_delta < 0 and (clicks_drop or impressions_drop) and carts_drop and conversion_stable and avg_check_stable and stock_qty > 0:
            confidence = "high" if impressions_drop else "medium"
            signals.append(_build_signal(kind="traffic", direction="negative", title=f"РўСЂР°С„РёРє РїСЂРѕСЃРµР» РїРѕ Р°СЂС‚РёРєСѓР»Сѓ {nm_id}", summary=f"РћСЃРЅРѕРІРЅРѕРµ СЃРЅРёР¶РµРЅРёРµ РїРѕ Р°СЂС‚РёРєСѓР»Сѓ {nm_id} РїРѕС…РѕР¶Рµ РЅР° РїСЂРѕСЃР°РґРєСѓ С‚СЂР°С„РёРєР°: РєР»РёРєРё Рё РєРѕСЂР·РёРЅС‹ СЃРЅРёР·РёР»РёСЃСЊ, Р° РєРѕРЅРІРµСЂСЃРёРё Рё СЃСЂРµРґРЅРёР№ С‡РµРє Р·Р°РјРµС‚РЅРѕ РЅРµ СѓС…СѓРґС€РёР»РёСЃСЊ.", check_text=f"РџСЂРѕРІРµСЂРёС‚СЊ С‚СЂР°С„РёРє Р°СЂС‚РёРєСѓР»Р° {nm_id}: РѕСЃС‚Р°С‚РѕРє {_format_decimal(stock_qty)}, РєР»РёРєРё {_format_decimal(traffic['baseline_clicks'].get('delta_vs_previous_day'))}, РєРѕСЂР·РёРЅС‹ {_format_decimal(traffic['baseline_carts'].get('delta_vs_previous_day'))}.", metric="traffic", trend_status=trend_status, confirmations=4 if impressions_drop else 3, confidence=confidence, partial_primary=confidence != "high", order_sum_delta=order_sum_delta, share_of_total_delta=share_negative, nm_id=nm_id, evidence=["clicks_down", "carts_down"], operational_weight=Decimal("16")))
        for query_row in article["search"]["queries"]:
            position_delta = _to_decimal(query_row.get("position_delta_day"))
            clicks_delta = _to_decimal(query_row.get("clicks_delta_day")) or Decimal("0")
            orders_delta = _to_decimal(query_row.get("orders_delta_day")) or Decimal("0")
            baseline_clicks = build_metric_history(query_row.get("trend_7d") or [], report_date=report_date, date_key="date", metric_key="search_clicks").get("avg_prev_7")
            if position_delta is not None and position_delta >= rules.search_position_change_threshold and clicks_delta < 0 and orders_delta < 0 and (baseline_clicks or Decimal("0")) >= LOW_TRAFFIC_QUERY_CLICKS:
                signals.append(_build_signal(kind="search", direction="negative", title=f"РџРѕРёСЃРє СѓС…СѓРґС€РёР»СЃСЏ РїРѕ Р°СЂС‚РёРєСѓР»Сѓ {nm_id}", summary=f"РџРѕРёСЃРє РјРѕРі РІРЅРµСЃС‚Рё РІРєР»Р°Рґ РІ СЃРїР°Рґ Р°СЂС‚РёРєСѓР»Р° {nm_id}: РїРѕ Р·Р°РїСЂРѕСЃСѓ В«{query_row.get('search_query')}В» СѓС…СѓРґС€РёР»РёСЃСЊ РїРѕР·РёС†РёСЏ Рё РїРѕРёСЃРєРѕРІС‹Рµ РєР»РёРєРё.", check_text=f"РџСЂРѕРІРµСЂРёС‚СЊ РёРЅРґРµРєСЃР°С†РёСЋ Р°СЂС‚РёРєСѓР»Р° {nm_id} РїРѕ Р·Р°РїСЂРѕСЃСѓ В«{query_row.get('search_query')}В»: РїРѕР·РёС†РёСЏ РёР·РјРµРЅРёР»Р°СЃСЊ СЃ {_format_decimal(query_row.get('previous_avg_position'), 1)} РґРѕ {_format_decimal(query_row.get('avg_position'), 1)}, РїРѕРёСЃРєРѕРІС‹Рµ РєР»РёРєРё СЃРЅРёР·РёР»РёСЃСЊ РЅР° {_format_decimal(clicks_delta)}.", metric="search", trend_status=trend_status, confirmations=4, confidence="medium", partial_primary=False, order_sum_delta=order_sum_delta, share_of_total_delta=share_negative, nm_id=nm_id, search_query=str(query_row.get("search_query")), evidence=["position_down", "search_clicks_down"], operational_weight=Decimal("14")))
                break
        best_campaign = None
        for campaign in sorted(article["ads"]["campaigns"], key=lambda row: _to_decimal(row.get("ad_spend")) or Decimal("0"), reverse=True):
            spend = _to_decimal(campaign.get("ad_spend")) or Decimal("0")
            orders = _to_decimal(campaign.get("ad_orders")) or Decimal("0")
            if spend >= rules.zero_order_spend_threshold and orders == 0:
                best_campaign = campaign
                break
        if best_campaign is not None:
            signals.append(_build_signal(kind="ads", direction="negative", title=f"Р РµРєР»Р°РјР° РїРѕ Р°СЂС‚РёРєСѓР»Сѓ {nm_id} С‚СЂРµР±СѓРµС‚ РїСЂРѕРІРµСЂРєРё", summary=f"РџРѕ РєР°РјРїР°РЅРёРё {best_campaign.get('advert_id')} РµСЃС‚СЊ СЂР°СЃС…РѕРґ Р±РµР· РґРѕСЃС‚Р°С‚РѕС‡РЅРѕРіРѕ СЂРµР·СѓР»СЊС‚Р°С‚Р° РїРѕ Р°СЂС‚РёРєСѓР»Сѓ {nm_id}.", check_text=f"РџСЂРѕРІРµСЂРёС‚СЊ РєР°РјРїР°РЅРёСЋ {best_campaign.get('advert_id')} РїРѕ Р°СЂС‚РёРєСѓР»Сѓ {nm_id}: СЂР°СЃС…РѕРґ {_format_currency(best_campaign.get('ad_spend'))}, Р·Р°РєР°Р·С‹ {_format_decimal(best_campaign.get('ad_orders'))}, Р”Р Р  {_format_percent(best_campaign.get('drr'))}.", metric="ad_spend", trend_status=trend_status, confirmations=3, confidence="high", partial_primary=False, order_sum_delta=order_sum_delta, share_of_total_delta=share_negative, nm_id=nm_id, advert_id=int(best_campaign.get("advert_id")), evidence=["ad_spend", "ad_orders"], operational_weight=Decimal("13")))
        warehouse_rows = article["stock"]["warehouse_rows"]
        avg_orders = max((_to_decimal(row.get("avg_orders_7d_article")) or Decimal("0")) for row in warehouse_rows) if warehouse_rows else (_to_decimal(article["funnel"]["order_count_baseline"].get("avg_prev_7")) or Decimal("0"))
        warehouses_with_stock = int(article["stock"].get("warehouses_with_stock") or 0)
        warehouses_zero_stock = int(article["stock"].get("warehouses_zero_stock") or 0)
        days_of_supply = (stock_qty / avg_orders) if avg_orders > 0 else None
        if order_sum_delta < 0 and avg_orders > 0 and (stock_qty <= 0 or (days_of_supply is not None and days_of_supply <= rules.low_stock_days)):
            signals.append(_build_signal(kind="stock", direction="negative", title=f"РћСЃС‚Р°С‚РѕРє РѕРіСЂР°РЅРёС‡РёРІР°РµС‚ Р°СЂС‚РёРєСѓР» {nm_id}", summary=f"РџРѕ Р°СЂС‚РёРєСѓР»Сѓ {nm_id} РµСЃС‚СЊ СЂРёСЃРє РґРµС„РёС†РёС‚Р°: РѕСЃС‚Р°С‚РѕРє {_format_decimal(stock_qty)}, СЃСЂРµРґРЅРёР№ СЃРїСЂРѕСЃ {_format_decimal(avg_orders, 1)} Р·Р°РєР°Р·Р° РІ РґРµРЅСЊ.", check_text=f"РџСЂРѕРІРµСЂРёС‚СЊ РѕСЃС‚Р°С‚РєРё Р°СЂС‚РёРєСѓР»Р° {nm_id}: РѕР±С‰РёР№ РѕСЃС‚Р°С‚РѕРє {_format_decimal(stock_qty)}, СЃСЂРµРґРЅРёР№ СЃРїСЂРѕСЃ {_format_decimal(avg_orders, 1)}, СЃРєР»Р°РґРѕРІ СЃ РЅР°Р»РёС‡РёРµРј {warehouses_with_stock}, СЃРєР»Р°РґРѕРІ СЃ РЅСѓР»С‘Рј {warehouses_zero_stock}.", metric="stock_qty", trend_status=trend_status, confirmations=4, confidence="high", partial_primary=article["data_quality"].get("stock_partial") is True, order_sum_delta=order_sum_delta, share_of_total_delta=share_negative, nm_id=nm_id, evidence=[_format_decimal(stock_qty), _format_decimal(avg_orders, 1)], operational_weight=Decimal("18")))
        price = article.get("price") or {}
        current_price = _to_decimal(price.get("buyer_visible_price"))
        previous_price = _to_decimal(price.get("previous_buyer_visible_price"))
        price_delta_pct = _safe_pct_delta(current_price, previous_price)
        if price.get("source_status") == "OK" and price_delta_pct is not None and abs(price_delta_pct) >= PRICE_CHANGE_THRESHOLD_PCT and not clicks_drop and stock_qty > 0:
            order_delta_pct = _to_decimal(article["funnel"]["order_count_baseline"].get("pct_vs_previous_day"))
            if order_delta_pct is not None and order_delta_pct < 0:
                signals.append(_build_signal(kind="price", direction="negative", title=f"Р¦РµРЅР° РјРѕРіР»Р° РїРѕРІР»РёСЏС‚СЊ РЅР° Р°СЂС‚РёРєСѓР» {nm_id}", summary=f"РџРѕСЃР»Рµ Р·Р°РјРµС‚РЅРѕРіРѕ РёР·РјРµРЅРµРЅРёСЏ РєР»РёРµРЅС‚СЃРєРѕР№ С†РµРЅС‹ РїРѕ Р°СЂС‚РёРєСѓР»Сѓ {nm_id} РїСЂРѕСЃРµР»Рё Р·Р°РєР°Р·С‹, РїСЂРё СЌС‚РѕРј С‚СЂР°С„РёРє Рё РѕСЃС‚Р°С‚РєРё РЅРµ РѕР±СЉСЏСЃРЅСЏСЋС‚ РІСЃС‘ РёР·РјРµРЅРµРЅРёРµ.", check_text=f"РџСЂРѕРІРµСЂРёС‚СЊ С†РµРЅСѓ Р°СЂС‚РёРєСѓР»Р° {nm_id}: РєР»РёРµРЅС‚СЃРєР°СЏ С†РµРЅР° РёР·РјРµРЅРёР»Р°СЃСЊ СЃ {_format_currency(previous_price)} РґРѕ {_format_currency(current_price)}, Р·Р°РєР°Р·С‹ РёР·РјРµРЅРёР»РёСЃСЊ РЅР° {_format_percent(order_delta_pct)}.", metric="buyer_visible_price", trend_status=trend_status, confirmations=3, confidence="medium", partial_primary=False, order_sum_delta=order_sum_delta, share_of_total_delta=share_negative, nm_id=nm_id, evidence=[_format_percent(price_delta_pct)], operational_weight=Decimal("11")))
        if order_sum_delta > 0 and trend_status in {"growth_2_days", "growth_3_plus_days", "first_growth"}:
            confirmations = 1 + (1 if (_to_decimal(traffic["baseline_clicks"].get("pct_vs_previous_day")) or Decimal("0")) > 0 else 0)
            signals.append(_build_signal(kind="article_growth", direction="positive", title=f"РђСЂС‚РёРєСѓР» {nm_id} СЂР°СЃС‚С‘С‚", summary=f"РђСЂС‚РёРєСѓР» {nm_id} РґР°Р» Р·Р°РјРµС‚РЅС‹Р№ РІРєР»Р°Рґ РІ СЂРѕСЃС‚ РѕР±РѕСЂРѕС‚Р° Р·Р° РґРµРЅСЊ.", check_text=f"РџСЂРѕРІРµСЂРёС‚СЊ, Р·Р° СЃС‡С‘С‚ С‡РµРіРѕ Р°СЂС‚РёРєСѓР» {nm_id} СЂР°СЃС‚С‘С‚ Р±С‹СЃС‚СЂРµРµ Р±Р°Р·С‹: РѕР±РѕСЂРѕС‚ РёР·РјРµРЅРёР»СЃСЏ РЅР° {_format_currency(order_sum_delta)}.", metric="order_sum", trend_status=trend_status, confirmations=confirmations, confidence="high", partial_primary=False, order_sum_delta=order_sum_delta, share_of_total_delta=share_positive, nm_id=nm_id, evidence=[trend_status], operational_weight=Decimal("10")))
    for anomaly in anomalies:
        signals.append(_build_signal(kind="anomaly", direction="negative", title="РўСЂРµР±СѓРµС‚СЃСЏ РїСЂРѕРІРµСЂРєР° РґР°РЅРЅС‹С…", summary=str(anomaly.get("summary")), check_text=str(anomaly.get("summary")), metric=str(anomaly.get("kind")), trend_status="stable", confirmations=1, confidence="medium", partial_primary=False, order_sum_delta=Decimal("0"), share_of_total_delta=Decimal("0"), nm_id=anomaly.get("nm_id"), advert_id=anomaly.get("advert_id"), search_query=anomaly.get("search_query"), evidence=[str(anomaly.get("kind"))], operational_weight=Decimal("7")))
    signals.sort(key=lambda item: (0 if item.get("direction") == "negative" else 1, -(item.get("score") or Decimal("0")), -(abs(item.get("order_sum_delta") or Decimal("0"))), str(item.get("kind"))))
    return signals[: max(top_n * 4, 12)]



def _build_analysis_summary(ranked_signals: Sequence[dict[str, Any]], anomalies: Sequence[dict[str, Any]], top_n: int) -> dict[str, Any]:
    negative_signals = [signal for signal in ranked_signals if signal.get("direction") == "negative" and signal.get("user_visible")]
    positive_signals = [signal for signal in ranked_signals if signal.get("direction") == "positive" and signal.get("user_visible")]
    main_problem = next((signal for signal in negative_signals if signal.get("kind") != "anomaly"), negative_signals[0] if negative_signals else None)
    main_growth = positive_signals[0] if positive_signals else None
    priority_checks = [signal.get("check") for signal in negative_signals[:top_n] if signal.get("check")]
    user_worse = [str(main_problem.get("summary"))] if main_problem else ([str(anomalies[0].get("summary"))] if anomalies else [])
    user_better = [str(main_growth.get("summary"))] if main_growth else []
    return {
        "main_problem": main_problem,
        "main_growth": main_growth,
        "priority_checks": priority_checks,
        "user_worse": user_worse,
        "user_better": user_better,
        "top_anomalies": list(anomalies[:top_n]),
    }


def build_highlights_from_analysis(analysis_payload: dict[str, Any], *, top_n: int) -> WbDailyOperationalHighlightsResponse:
    summary = analysis_payload.get("analysis_summary") or {}
    priority_checks = [str(item.get("text")) for item in (summary.get("priority_checks") or []) if item and item.get("text")]
    return WbDailyOperationalHighlightsResponse(
        worse=list((summary.get("user_worse") or [])[:top_n]),
        better=list((summary.get("user_better") or [])[:top_n]),
        priority_checks=priority_checks[:top_n],
    )


def build_internal_analysis(*, report_date: date, daily_rows: Sequence[dict[str, Any]], article_context: Sequence[dict[str, Any]], warehouse_context: Sequence[dict[str, Any]], campaign_context: Sequence[dict[str, Any]], search_query_context: Sequence[dict[str, Any]], entry_point_context: Sequence[dict[str, Any]], price_context: Sequence[dict[str, Any]], logistics_context: Sequence[dict[str, Any]], data_gaps: Sequence[dict[str, Any]], rules: WbDailyOperationalSummaryRules, top_n: int) -> dict[str, Any]:
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
    analysis_summary = _build_analysis_summary(ranked_signals, anomalies, top_n)
    return {
        "article_analysis": article_analysis,
        "ranked_signals": ranked_signals,
        "data_anomalies": list(anomalies),
        "analysis_summary": analysis_summary,
        "data_gaps": analysis_gaps + aggregate_gaps,
    }


