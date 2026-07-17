from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.db.models import (
    FactAdCampaignNmDay,
    FactAdCostDay,
    FactEntryPointDay,
    FactFunnelDay,
    FactLocalizationRegionDay,
    FactSearchQueryMetric,
    FactStockSnapshot,
    MartTotalReport,
    SettingsProducts,
)
from src.db.session import session_scope, upsert_rows


MART_TOTAL_REPORT_CONFLICT_COLUMNS = ("report_date", "nm_id")


def _to_decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _sum_decimal(values: Iterable[Any]) -> Decimal | None:
    total = Decimal("0")
    found = False
    for value in values:
        decimal_value = _to_decimal_or_none(value)
        if decimal_value is None:
            continue
        total += decimal_value
        found = True
    return total if found else None


def _mean_decimal(values: Iterable[Any]) -> Decimal | None:
    decimals = [value for value in (_to_decimal_or_none(item) for item in values) if value is not None]
    if not decimals:
        return None
    return sum(decimals, Decimal("0")) / Decimal(str(len(decimals)))


def _weighted_mean_decimal(pairs: Iterable[tuple[Any, Any]]) -> Decimal | None:
    numerator = Decimal("0")
    denominator = Decimal("0")
    for value, weight in pairs:
        decimal_value = _to_decimal_or_none(value)
        decimal_weight = _to_decimal_or_none(weight)
        if decimal_value is None or decimal_weight is None or decimal_weight == 0:
            continue
        numerator += decimal_value * decimal_weight
        denominator += decimal_weight
    if denominator == 0:
        return None
    return numerator / denominator


def _safe_divide(numerator: Any, denominator: Any, multiplier: Any | None = None) -> Decimal | None:
    decimal_numerator = _to_decimal_or_none(numerator)
    decimal_denominator = _to_decimal_or_none(denominator)
    if decimal_numerator is None or decimal_denominator is None or decimal_denominator == 0:
        return None
    result = decimal_numerator / decimal_denominator
    if multiplier is not None:
        decimal_multiplier = _to_decimal_or_none(multiplier)
        if decimal_multiplier is None:
            return None
        result *= decimal_multiplier
    return result


def build_calc_metrics(
    *,
    impressions: Any,
    card_clicks: Any,
    cart_count: Any,
    order_count: Any,
    order_sum: Any,
    ad_spend: Any,
    ad_views: Any,
    ad_clicks: Any,
    ad_orders: Any,
) -> dict[str, Decimal | None]:
    return {
        "ctr_calc": _safe_divide(card_clicks, impressions, Decimal("100")),
        "add_to_cart_conversion_calc": _safe_divide(cart_count, card_clicks, Decimal("100")),
        "cart_to_order_conversion_calc": _safe_divide(order_count, cart_count, Decimal("100")),
        "ad_cpc_calc": _safe_divide(ad_spend, ad_clicks),
        "ad_cpm_calc": _safe_divide(ad_spend, ad_views, Decimal("1000")),
        "ad_cpo_calc": _safe_divide(ad_spend, ad_orders),
        "ad_share_of_revenue_calc": _safe_divide(ad_spend, order_sum, Decimal("100")),
    }


def _has_meaningful_funnel_metrics(row: Mapping[str, Any]) -> bool:
    meaningful_fields = (
        "card_clicks",
        "cart_count",
        "order_count",
        "order_sum",
        "add_to_cart_conversion",
        "cart_to_order_conversion",
        "add_to_cart_conversion_calc",
        "cart_to_order_conversion_calc",
        "buyout_count",
        "buyout_sum",
    )
    return any(_to_decimal_or_none(row.get(field)) is not None for field in meaningful_fields)


def _has_positive_funnel_metrics(row: Mapping[str, Any]) -> bool:
    meaningful_fields = (
        "card_clicks",
        "cart_count",
        "order_count",
        "order_sum",
        "add_to_cart_conversion",
        "cart_to_order_conversion",
        "add_to_cart_conversion_calc",
        "cart_to_order_conversion_calc",
        "buyout_count",
        "buyout_sum",
    )
    return any(
        (decimal_value := _to_decimal_or_none(row.get(field))) is not None and decimal_value > 0
        for field in meaningful_fields
    )


def _resolve_funnel_status(funnel_row: FactFunnelDay | None, row: Mapping[str, Any]) -> tuple[str, str | None]:
    if funnel_row is None:
        return "SOURCE_MISSING", None
    source_status = getattr(funnel_row, "source_status", None)
    has_metrics = _has_meaningful_funnel_metrics(row)
    has_positive = _has_positive_funnel_metrics(row)
    if source_status == "DETAIL_HISTORY_REPORT":
        return ("REAL_API_DETAIL" if has_positive else "NO_ACTIVITY"), source_status
    if has_metrics:
        return ("LEGACY_FALLBACK" if has_positive else "NO_ACTIVITY"), source_status
    return "HOLLOW_LEGACY_IGNORED", source_status


def _date_range(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def build_active_product_date_grid(
    *,
    start: date,
    end: date,
    products: Sequence[SettingsProducts | Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for report_date in _date_range(start, end):
        for product in products:
            rows.append(
                {
                    "report_date": report_date,
                    "nm_id": product.nm_id,
                    "supplier_article": getattr(product, "supplier_article", None),
                    "title": getattr(product, "title", None),
                    "subject": getattr(product, "subject", None),
                    "brand": getattr(product, "brand", None),
                }
            )
    return rows


def aggregate_ad_campaign_stats(rows: Sequence[FactAdCampaignNmDay]) -> dict[tuple[date, int], dict[str, Any]]:
    grouped: dict[tuple[date, int], list[FactAdCampaignNmDay]] = defaultdict(list)
    for row in rows:
        if row.date is None or row.nm_id is None:
            continue
        grouped[(row.date, row.nm_id)].append(row)

    result: dict[tuple[date, int], dict[str, Any]] = {}
    for key, group in grouped.items():
        result[key] = {
            "ad_views": _sum_decimal(item.ad_views for item in group),
            "ad_clicks": _sum_decimal(item.ad_clicks for item in group),
            "ad_atbs": _sum_decimal(item.ad_atbs for item in group),
            "ad_orders": _sum_decimal(item.ad_orders for item in group),
            "ad_revenue": _sum_decimal(item.ad_revenue for item in group),
            "ad_spend": _sum_decimal(item.ad_spend for item in group),
            "ad_avg_position": _weighted_mean_decimal((item.avg_position, item.ad_views) for item in group)
            or _mean_decimal(item.avg_position for item in group),
            "direct_ad_atbs": _sum_decimal(item.ad_atbs for item in group if item.conversion_type == "DIRECT"),
            "associated_ad_atbs": _sum_decimal(item.ad_atbs for item in group if item.conversion_type == "ASSOCIATED"),
            "multicard_ad_atbs": _sum_decimal(item.ad_atbs for item in group if item.conversion_type == "MULTICARD"),
            "unknown_ad_atbs": _sum_decimal(
                item.ad_atbs
                for item in group
                if item.conversion_type not in {"DIRECT", "ASSOCIATED", "MULTICARD"}
            ),
        }
    return result


def build_mart_ad_metrics(
    *,
    ad_cost_stats: Mapping[str, Any] | None,
    ad_campaign_stats: Mapping[str, Any] | None,
    order_sum: Any,
    cart_count: Any,
) -> dict[str, Any]:
    ad_cost_stats = ad_cost_stats or {}
    ad_campaign_stats = ad_campaign_stats or {}
    ad_cost_writeoff_total = ad_cost_stats.get("ad_cost_spend")
    ad_campaign_spend_total = ad_campaign_stats.get("ad_spend")
    ad_spend_total = ad_cost_writeoff_total
    ad_views_total = ad_campaign_stats.get("ad_views")
    ad_clicks_total = ad_campaign_stats.get("ad_clicks")
    ad_atbs_total = ad_campaign_stats.get("ad_atbs")
    ad_orders_total = ad_campaign_stats.get("ad_orders")
    associated_ad_atbs = ad_campaign_stats.get("associated_ad_atbs")
    organic_cart_count = None
    organic_cart_share_calc = None
    organic_cart_share_status = "MISSING_SOURCE"
    decimal_cart_count = _to_decimal_or_none(cart_count)
    decimal_ad_atbs_total = _to_decimal_or_none(ad_atbs_total)
    decimal_associated_atbs = _to_decimal_or_none(associated_ad_atbs) or Decimal("0")

    if decimal_cart_count is not None and decimal_ad_atbs_total is not None:
        organic_cart_count = decimal_cart_count - decimal_ad_atbs_total
        organic_cart_share_status = "OK"
        organic_cart_share_calc = _safe_divide(organic_cart_count, decimal_ad_atbs_total, Decimal("100"))
    elif decimal_cart_count is not None or decimal_ad_atbs_total is not None:
        organic_cart_share_status = "MISSING_SOURCE"

    all_carts_denominator = None
    if decimal_cart_count is not None:
        all_carts_denominator = decimal_cart_count + decimal_associated_atbs

    return {
        "ad_spend_total": ad_spend_total,
        "ad_cost_writeoff_total": ad_cost_writeoff_total,
        "ad_campaign_spend_total": ad_campaign_spend_total,
        "ad_views_total": ad_views_total,
        "ad_clicks_total": ad_clicks_total,
        "ad_atbs_total": ad_atbs_total,
        "ad_orders_total": ad_orders_total,
        "direct_ad_atbs": ad_campaign_stats.get("direct_ad_atbs"),
        "associated_ad_atbs": associated_ad_atbs,
        "multicard_ad_atbs": ad_campaign_stats.get("multicard_ad_atbs"),
        "unknown_ad_atbs": ad_campaign_stats.get("unknown_ad_atbs"),
        "ad_cpm_calc": _safe_divide(ad_campaign_spend_total, ad_views_total, Decimal("1000")),
        "ad_cpc_calc": _safe_divide(ad_campaign_spend_total, ad_clicks_total),
        "ad_cost_per_cart_calc": _safe_divide(ad_campaign_spend_total, ad_atbs_total),
        "ad_cpo_calc": _safe_divide(ad_campaign_spend_total, ad_orders_total),
        "ad_share_of_revenue_calc": _safe_divide(ad_campaign_spend_total, order_sum, Decimal("100")),
        "associated_atbs_percent_calc": _safe_divide(associated_ad_atbs, ad_atbs_total, Decimal("100")),
        "organic_cart_count": organic_cart_count,
        "organic_cart_share_calc": organic_cart_share_calc,
        "ad_cost_per_all_carts_calc": _safe_divide(ad_campaign_spend_total, all_carts_denominator),
        "organic_cart_share_status": organic_cart_share_status,
    }


def aggregate_search_stats(rows: Sequence[FactSearchQueryMetric]) -> dict[tuple[date, int], dict[str, Any]]:
    grouped: dict[tuple[date, int], list[FactSearchQueryMetric]] = defaultdict(list)
    for row in rows:
        if row.date is None or row.nm_id is None:
            continue
        grouped[(row.date, row.nm_id)].append(row)

    result: dict[tuple[date, int], dict[str, Any]] = {}
    for key, group in grouped.items():
        result[key] = {
            "search_queries_count": len(group),
            "search_avg_position": _mean_decimal(item.avg_position for item in group),
            "search_visibility": _mean_decimal(item.visibility for item in group),
            "search_clicks": _sum_decimal(item.search_clicks for item in group),
            "search_cart": _sum_decimal(item.search_cart for item in group),
            "search_orders": _sum_decimal(item.search_orders for item in group),
        }
    return result


def aggregate_ad_cost_stats(rows: Sequence[FactAdCostDay]) -> dict[tuple[date, int], dict[str, Any]]:
    grouped: dict[tuple[date, int], list[FactAdCostDay]] = defaultdict(list)
    for row in rows:
        if row.date is None or row.nm_id is None:
            continue
        grouped[(row.date, row.nm_id)].append(row)

    result: dict[tuple[date, int], dict[str, Any]] = {}
    for key, group in grouped.items():
        result[key] = {
            "ad_cost_spend": _sum_decimal(item.total_spend for item in group),
        }
    return result


def aggregate_entry_point_stats(rows: Sequence[FactEntryPointDay]) -> dict[tuple[date, int], dict[str, Any]]:
    grouped: dict[tuple[date, int], list[FactEntryPointDay]] = defaultdict(list)
    for row in rows:
        if row.date is None or row.nm_id is None:
            continue
        grouped[(row.date, row.nm_id)].append(row)

    result: dict[tuple[date, int], dict[str, Any]] = {}
    for key, group in grouped.items():
        entry_impressions_total = _sum_decimal(item.impressions for item in group)
        entry_card_clicks_total = _sum_decimal(item.card_clicks for item in group)
        entry_cart_total = _sum_decimal(item.cart_count for item in group)
        entry_orders_total = _sum_decimal(item.order_count for item in group)
        result[key] = {
            "entry_impressions_total": entry_impressions_total,
            "entry_card_clicks_total": entry_card_clicks_total,
            "entry_cart_total": entry_cart_total,
            "entry_orders_total": entry_orders_total,
            "entry_ctr_calc": _safe_divide(entry_card_clicks_total, entry_impressions_total, Decimal("100")),
            "entry_cart_conversion_calc": _safe_divide(entry_cart_total, entry_card_clicks_total, Decimal("100")),
            "entry_order_conversion_calc": _safe_divide(entry_orders_total, entry_cart_total, Decimal("100")),
        }
    return result


def aggregate_localization_stats(rows: Sequence[FactLocalizationRegionDay]) -> dict[tuple[date, int], dict[str, Any]]:
    grouped: dict[tuple[date, int], list[FactLocalizationRegionDay]] = defaultdict(list)
    for row in rows:
        report_date = _localization_report_date(row)
        if report_date is None or row.nm_id is None:
            continue
        grouped[(report_date, row.nm_id)].append(row)

    result: dict[tuple[date, int], dict[str, Any]] = {}
    for key, group in grouped.items():
        result[key] = {
            "localization_regions_count": len({item.region for item in group if item.region}),
            "localization_orders_total_qty": _sum_decimal(item.orders_total_qty for item in group),
            "localization_sale_item_qty": _sum_decimal(item.sale_item_qty for item in group),
            "localization_sale_amount": _sum_decimal(item.sale_amount for item in group),
        }
    return result


def build_mart_total_report_row(
    funnel_row: FactFunnelDay,
    stock_row: FactStockSnapshot | None,
    ad_cost_stats: Mapping[str, Any] | None,
    ad_campaign_stats: Mapping[str, Any] | None,
    search_stats: Mapping[str, Any] | None,
    localization_stats: Mapping[str, Any] | None,
) -> dict[str, Any]:
    report_date = funnel_row.date
    nm_id = funnel_row.nm_id
    ad_cost_stats = ad_cost_stats or {}
    ad_campaign_stats = ad_campaign_stats or {}
    search_stats = search_stats or {}
    localization_stats = localization_stats or {}

    row = {
        "report_date": report_date,
        "nm_id": nm_id,
        "supplier_article": None,
        "title": None,
        "subject": None,
        "brand": None,
        "impressions": funnel_row.impressions,
        "card_clicks": funnel_row.card_clicks,
        "ctr": funnel_row.ctr,
        "cart_count": funnel_row.cart_count,
        "order_count": funnel_row.order_count,
        "order_sum": funnel_row.order_sum,
        "buyout_count": funnel_row.buyout_count,
        "buyout_sum": funnel_row.buyout_sum,
        "buyout_percent": funnel_row.buyout_percent,
        "add_to_cart_conversion": funnel_row.add_to_cart_conversion,
        "cart_to_order_conversion": funnel_row.cart_to_order_conversion,
        "add_to_wishlist_count": funnel_row.wishlist_count,
        "avg_delivery_time": funnel_row.avg_delivery_time,
        "local_orders_percent": funnel_row.local_orders_percent,
        "current_stock_qty": stock_row.stock_total_qty if stock_row else None,
        "current_stock_sum": stock_row.stock_total_sum if stock_row else None,
        "stock_snapshot_date": stock_row.snapshot_date if stock_row else None,
        "ad_cost_spend": ad_cost_stats.get("ad_cost_spend"),
        "ad_views": ad_campaign_stats.get("ad_views"),
        "ad_clicks": ad_campaign_stats.get("ad_clicks"),
        "ad_atbs": ad_campaign_stats.get("ad_atbs"),
        "ad_orders": ad_campaign_stats.get("ad_orders"),
        "ad_revenue": ad_campaign_stats.get("ad_revenue"),
        "ad_spend": ad_campaign_stats.get("ad_spend"),
        "ad_avg_position": ad_campaign_stats.get("ad_avg_position"),
        "direct_ad_atbs": ad_campaign_stats.get("direct_ad_atbs"),
        "associated_ad_atbs": ad_campaign_stats.get("associated_ad_atbs"),
        "multicard_ad_atbs": ad_campaign_stats.get("multicard_ad_atbs"),
        "search_queries_count": search_stats.get("search_queries_count"),
        "search_avg_position": search_stats.get("search_avg_position"),
        "search_visibility": search_stats.get("search_visibility"),
        "search_clicks": search_stats.get("search_clicks"),
        "search_cart": search_stats.get("search_cart"),
        "search_orders": search_stats.get("search_orders"),
        "localization_regions_count": localization_stats.get("localization_regions_count"),
        "localization_orders_total_qty": localization_stats.get("localization_orders_total_qty"),
        "localization_sale_item_qty": localization_stats.get("localization_sale_item_qty"),
        "localization_sale_amount": localization_stats.get("localization_sale_amount"),
        "current_mp_stock_qty": stock_row.mp_stock_qty if stock_row else None,
        "vbro_organic_sales_qty": None,
        "vbro_operating_profit": None,
        "has_funnel": False,
        "has_stock": stock_row is not None,
        "has_ad_cost": bool(ad_cost_stats),
        "has_ad_campaign": bool(ad_campaign_stats),
        "has_search": bool(search_stats),
        "has_localization": bool(localization_stats),
        "has_vbro": False,
        "has_entry_points": False,
        "has_card_comparison": False,
        "manual_vbro_status": "MANUAL_EXTERNAL_SERVICE / MANUAL_UPLOAD",
        "export_context_json": None,
        "data_status": "PARTIAL",
        "source_status": "PARTIAL",
        "loaded_at": funnel_row.loaded_at,
    }
    row["has_funnel"] = _has_meaningful_funnel_metrics(row)
    return row


def _build_mart_total_report_v2_row(
    *,
    base_row: Mapping[str, Any],
    stock_row: FactStockSnapshot | None,
    funnel_row: FactFunnelDay | None,
    entry_point_stats: Mapping[str, Any] | None,
    ad_cost_stats: Mapping[str, Any] | None,
    ad_campaign_stats: Mapping[str, Any] | None,
    search_stats: Mapping[str, Any] | None,
    localization_stats: Mapping[str, Any] | None,
) -> dict[str, Any]:
    entry_point_stats = entry_point_stats or {}
    ad_cost_stats = ad_cost_stats or {}
    ad_campaign_stats = ad_campaign_stats or {}
    search_stats = search_stats or {}
    localization_stats = localization_stats or {}
    loaded_candidates = [
        getattr(source, "loaded_at", None)
        for source in (funnel_row, stock_row)
        if source is not None and getattr(source, "loaded_at", None) is not None
    ]
    loaded_at = max(loaded_candidates) if loaded_candidates else datetime.now(timezone.utc)

    row = {
        "report_date": base_row["report_date"],
        "nm_id": base_row["nm_id"],
        "supplier_article": base_row.get("supplier_article") or (stock_row.supplier_article if stock_row else None),
        "title": base_row.get("title") or (stock_row.title if stock_row else None),
        "subject": base_row.get("subject") or (stock_row.subject if stock_row else None),
        "brand": base_row.get("brand") or (stock_row.brand if stock_row else None),
        "impressions": funnel_row.impressions if funnel_row else None,
        "card_clicks": funnel_row.card_clicks if funnel_row else None,
        "ctr": funnel_row.ctr if funnel_row else None,
        "cart_count": funnel_row.cart_count if funnel_row else None,
        "order_count": funnel_row.order_count if funnel_row else None,
        "order_sum": funnel_row.order_sum if funnel_row else None,
        "buyout_count": funnel_row.buyout_count if funnel_row else None,
        "buyout_sum": funnel_row.buyout_sum if funnel_row else None,
        "buyout_percent": funnel_row.buyout_percent if funnel_row else None,
        "add_to_cart_conversion": funnel_row.add_to_cart_conversion if funnel_row else None,
        "cart_to_order_conversion": funnel_row.cart_to_order_conversion if funnel_row else None,
        "add_to_wishlist_count": funnel_row.wishlist_count if funnel_row else None,
        "avg_delivery_time": funnel_row.avg_delivery_time if funnel_row else None,
        "local_orders_percent": funnel_row.local_orders_percent if funnel_row else None,
        "current_stock_qty": stock_row.stock_total_qty if stock_row else None,
        "current_stock_sum": stock_row.stock_total_sum if stock_row else None,
        "stock_snapshot_date": stock_row.snapshot_date if stock_row else None,
        "entry_impressions_total": entry_point_stats.get("entry_impressions_total"),
        "entry_card_clicks_total": entry_point_stats.get("entry_card_clicks_total"),
        "entry_cart_total": entry_point_stats.get("entry_cart_total"),
        "entry_orders_total": entry_point_stats.get("entry_orders_total"),
        "entry_ctr_calc": entry_point_stats.get("entry_ctr_calc"),
        "entry_cart_conversion_calc": entry_point_stats.get("entry_cart_conversion_calc"),
        "entry_order_conversion_calc": entry_point_stats.get("entry_order_conversion_calc"),
        "ad_cost_spend": ad_cost_stats.get("ad_cost_spend"),
        "ad_views": ad_campaign_stats.get("ad_views"),
        "ad_clicks": ad_campaign_stats.get("ad_clicks"),
        "ad_atbs": ad_campaign_stats.get("ad_atbs"),
        "ad_orders": ad_campaign_stats.get("ad_orders"),
        "ad_revenue": ad_campaign_stats.get("ad_revenue"),
        "ad_spend": ad_campaign_stats.get("ad_spend"),
        "ad_avg_position": ad_campaign_stats.get("ad_avg_position"),
        "direct_ad_atbs": ad_campaign_stats.get("direct_ad_atbs"),
        "associated_ad_atbs": ad_campaign_stats.get("associated_ad_atbs"),
        "multicard_ad_atbs": ad_campaign_stats.get("multicard_ad_atbs"),
        "search_queries_count": search_stats.get("search_queries_count"),
        "search_avg_position": search_stats.get("search_avg_position"),
        "search_visibility": search_stats.get("search_visibility"),
        "search_clicks": search_stats.get("search_clicks"),
        "search_cart": search_stats.get("search_cart"),
        "search_orders": search_stats.get("search_orders"),
        "localization_regions_count": localization_stats.get("localization_regions_count"),
        "localization_orders_total_qty": localization_stats.get("localization_orders_total_qty"),
        "localization_sale_item_qty": localization_stats.get("localization_sale_item_qty"),
        "localization_sale_amount": localization_stats.get("localization_sale_amount"),
        "current_mp_stock_qty": stock_row.mp_stock_qty if stock_row else None,
        "vbro_organic_sales_qty": None,
        "vbro_operating_profit": None,
        "has_funnel": False,
        "has_stock": stock_row is not None,
        "has_ad_cost": bool(ad_cost_stats),
        "has_ad_campaign": bool(ad_campaign_stats),
        "has_search": bool(search_stats),
        "has_localization": bool(localization_stats),
        "has_localization_partial": bool(localization_stats),
        "has_vbro": False,
        "has_entry_points": bool(entry_point_stats),
        "has_card_comparison": False,
        "manual_vbro_status": "MANUAL_EXTERNAL_SERVICE / MANUAL_UPLOAD",
        "entry_point_status": "FILE_IMPORT_PENDING",
        "orders_geography_status": "FILE_IMPORT_PENDING",
        "vbro_status": "MANUAL_PENDING",
        "card_comparison_status": "NOT_INCLUDED",
        "export_context_json": None,
        "data_status": "PARTIAL",
        "source_status": "PARTIAL",
        "loaded_at": loaded_at,
    }
    row.update(
        build_mart_ad_metrics(
            ad_cost_stats=ad_cost_stats,
            ad_campaign_stats=ad_campaign_stats,
            order_sum=row["order_sum"],
            cart_count=row["cart_count"],
        )
    )
    row.update(
        build_calc_metrics(
            impressions=row["impressions"],
            card_clicks=row["card_clicks"],
            cart_count=row["cart_count"],
            order_count=row["order_count"],
            order_sum=row["order_sum"],
            ad_spend=row["ad_spend_total"],
            ad_views=row["ad_views_total"],
            ad_clicks=row["ad_clicks_total"],
            ad_orders=row["ad_orders_total"],
        )
    )
    row["has_funnel"] = _has_meaningful_funnel_metrics(row)
    funnel_resolution_status, funnel_selected_source = _resolve_funnel_status(funnel_row, row)
    row["export_context_json"] = {
        "funnel_resolution_status": funnel_resolution_status,
        "funnel_selected_source": funnel_selected_source,
        "funnel_has_non_null_metrics": row["has_funnel"],
        "funnel_has_positive_metrics": _has_positive_funnel_metrics(row),
    }
    return row


def prepare_mart_total_report_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: dict[tuple[Any, Any], dict[str, Any]] = {}
    for row in rows:
        report_date = row.get("report_date")
        nm_id = row.get("nm_id")
        if report_date is None or nm_id in (None, ""):
            continue
        prepared[(report_date, nm_id)] = dict(row)
    return list(prepared.values())


def upsert_mart_total_report(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_mart_total_report_upsert_rows(rows)
    upsert_rows(
        session=session,
        model=MartTotalReport,
        rows=prepared_rows,
        conflict_columns=MART_TOTAL_REPORT_CONFLICT_COLUMNS,
        batch_size=100,
    )
    return len(prepared_rows)


def count_mart_total_report_rows(session: Session, start: date, end: date) -> int:
    stmt = (
        select(func.count())
        .select_from(MartTotalReport)
        .where(MartTotalReport.report_date >= start, MartTotalReport.report_date <= end)
    )
    return int(session.execute(stmt).scalar_one())


def count_mart_total_report_duplicates(session: Session, start: date, end: date) -> int:
    dup_stmt = (
        select(MartTotalReport.report_date, MartTotalReport.nm_id)
        .where(MartTotalReport.report_date >= start, MartTotalReport.report_date <= end)
        .group_by(MartTotalReport.report_date, MartTotalReport.nm_id)
        .having(func.count() > 1)
    )
    return len(session.execute(dup_stmt).all())


def delete_mart_total_report_rows_for_inactive_products(
    session: Session,
    *,
    start: date,
    end: date,
    active_nm_ids: Sequence[int],
) -> int:
    stmt = delete(MartTotalReport).where(
        MartTotalReport.report_date >= start,
        MartTotalReport.report_date <= end,
    )
    if active_nm_ids:
        stmt = stmt.where(MartTotalReport.nm_id.not_in(list(active_nm_ids)))
    result = session.execute(stmt)
    return result.rowcount or 0


def _stock_rows_by_date_nm(rows: Sequence[FactStockSnapshot]) -> dict[tuple[date, int], FactStockSnapshot]:
    indexed: dict[tuple[date, int], FactStockSnapshot] = {}
    for row in rows:
        key = (row.snapshot_date, row.nm_id)
        current = indexed.get(key)
        current_loaded_at = getattr(current, "loaded_at", None) if current is not None else None
        row_loaded_at = getattr(row, "loaded_at", None)
        if current is None or (row_loaded_at is not None and (current_loaded_at is None or row_loaded_at >= current_loaded_at)):
            indexed[key] = row
    return indexed


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _search_reference_index(rows: Sequence[FactSearchQueryMetric]) -> dict[tuple[date, int], FactSearchQueryMetric]:
    index: dict[tuple[date, int], FactSearchQueryMetric] = {}
    for row in rows:
        if row.date is None:
            continue
        key = (row.date, row.nm_id)
        current = index.get(key)
        if current is None:
            index[key] = row
            continue
        current_score = sum(1 for value in (current.supplier_article, current.title, current.subject, current.brand) if value)
        row_score = sum(1 for value in (row.supplier_article, row.title, row.subject, row.brand) if value)
        if row_score > current_score:
            index[key] = row
    return index


def _localization_reference_index(rows: Sequence[FactLocalizationRegionDay]) -> dict[tuple[date, int], FactLocalizationRegionDay]:
    index: dict[tuple[date, int], FactLocalizationRegionDay] = {}
    for row in rows:
        report_date = _localization_report_date(row)
        if report_date is None:
            continue
        key = (report_date, row.nm_id)
        current = index.get(key)
        if current is None or (getattr(current, "source_status", None) != "CSV_EXPORT" and getattr(row, "source_status", None) == "CSV_EXPORT"):
            index[key] = row
    return index


def _entry_point_reference_index(rows: Sequence[FactEntryPointDay]) -> dict[tuple[date, int], FactEntryPointDay]:
    index: dict[tuple[date, int], FactEntryPointDay] = {}
    for row in rows:
        key = (row.date, row.nm_id)
        current = index.get(key)
        if current is None:
            index[key] = row
            continue
        current_score = sum(1 for value in (current.supplier_article, current.title, current.subject, current.brand) if value)
        row_score = sum(1 for value in (row.supplier_article, row.title, row.subject, row.brand) if value)
        if row_score > current_score:
            index[key] = row
    return index


def _localization_report_date(row: FactLocalizationRegionDay) -> date | None:
    return getattr(row, "period_end", None) or getattr(row, "date", None)


def _source_status_key_set(
    rows: Sequence[Any],
    *,
    date_getter,
    source_status: str,
) -> set[tuple[date, int]]:
    keys: set[tuple[date, int]] = set()
    for row in rows:
        report_date = date_getter(row)
        nm_id = getattr(row, "nm_id", None)
        if report_date is None or nm_id is None:
            continue
        if getattr(row, "source_status", None) == source_status:
            keys.add((report_date, nm_id))
    return keys


def build_mart_total_report(start: date, end: date, version: str = "v2") -> dict[str, Any]:
    with session_scope() as session:
        if version not in {"v1", "v2"}:
            raise ValueError(f"Unsupported mart_total_report version: {version}")
        if version == "v1":
            return _build_mart_total_report_v1(session, start, end)
        return _build_mart_total_report_v2(session, start, end)


def _build_mart_total_report_v1(session: Session, start: date, end: date) -> dict[str, Any]:
    funnel_rows = session.execute(
        select(FactFunnelDay).where(FactFunnelDay.date >= start, FactFunnelDay.date <= end)
    ).scalars().all()
    if not funnel_rows:
        return {
            "version": "v1",
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "rows_built": 0,
            "rows_upserted": 0,
            "rows_in_db": 0,
            "duplicate_keys": 0,
            "funnel_rows": 0,
        }

    ad_cost_rows = session.execute(
        select(FactAdCostDay).where(FactAdCostDay.date >= start, FactAdCostDay.date <= end)
    ).scalars().all()
    ad_campaign_rows = session.execute(
        select(FactAdCampaignNmDay).where(FactAdCampaignNmDay.date >= start, FactAdCampaignNmDay.date <= end)
    ).scalars().all()
    search_rows = session.execute(
        select(FactSearchQueryMetric).where(FactSearchQueryMetric.date >= start, FactSearchQueryMetric.date <= end)
    ).scalars().all()
    localization_rows = session.execute(
        select(FactLocalizationRegionDay).where(FactLocalizationRegionDay.period_end >= start, FactLocalizationRegionDay.period_end <= end)
    ).scalars().all()
    stock_rows = session.execute(select(FactStockSnapshot).where(FactStockSnapshot.snapshot_date >= start, FactStockSnapshot.snapshot_date <= end)).scalars().all()

    stock_rows_by_date_nm = _stock_rows_by_date_nm(stock_rows)
    ad_cost_index = aggregate_ad_cost_stats(ad_cost_rows)
    ad_campaign_index = aggregate_ad_campaign_stats(ad_campaign_rows)
    search_index = aggregate_search_stats(search_rows)
    localization_index = aggregate_localization_stats(localization_rows)

    mart_rows: list[dict[str, Any]] = []
    for funnel_row in funnel_rows:
        stock_row = stock_rows_by_date_nm.get((funnel_row.date, funnel_row.nm_id))
        row = build_mart_total_report_row(
            funnel_row=funnel_row,
            stock_row=stock_row,
            ad_cost_stats=ad_cost_index.get((funnel_row.date, funnel_row.nm_id)),
            ad_campaign_stats=ad_campaign_index.get((funnel_row.date, funnel_row.nm_id)),
            search_stats=search_index.get((funnel_row.date, funnel_row.nm_id)),
            localization_stats=localization_index.get((funnel_row.date, funnel_row.nm_id)),
        )
        mart_rows.append(row)

    rows_upserted = upsert_mart_total_report(session, mart_rows)
    rows_in_db = count_mart_total_report_rows(session, start, end)
    duplicate_keys = count_mart_total_report_duplicates(session, start, end)
    return {
        "version": "v1",
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "rows_built": len(mart_rows),
        "rows_upserted": rows_upserted,
        "rows_in_db": rows_in_db,
        "duplicate_keys": duplicate_keys,
        "funnel_rows": len(funnel_rows),
    }


def _build_mart_total_report_v2(session: Session, start: date, end: date) -> dict[str, Any]:
    active_products = session.execute(
        select(SettingsProducts).where(SettingsProducts.active.is_(True)).order_by(SettingsProducts.nm_id.asc())
    ).scalars().all()
    active_nm_ids = [product.nm_id for product in active_products]
    date_series = _date_range(start, end)
    base_rows = build_active_product_date_grid(start=start, end=end, products=active_products)

    funnel_rows = session.execute(
        select(FactFunnelDay).where(FactFunnelDay.date >= start, FactFunnelDay.date <= end)
    ).scalars().all()
    ad_cost_rows = session.execute(
        select(FactAdCostDay).where(FactAdCostDay.date >= start, FactAdCostDay.date <= end)
    ).scalars().all()
    ad_campaign_rows = session.execute(
        select(FactAdCampaignNmDay).where(FactAdCampaignNmDay.date >= start, FactAdCampaignNmDay.date <= end)
    ).scalars().all()
    search_rows = session.execute(
        select(FactSearchQueryMetric).where(FactSearchQueryMetric.date >= start, FactSearchQueryMetric.date <= end)
    ).scalars().all()
    localization_rows = session.execute(
        select(FactLocalizationRegionDay).where(FactLocalizationRegionDay.period_end >= start, FactLocalizationRegionDay.period_end <= end)
    ).scalars().all()
    entry_point_rows = session.execute(
        select(FactEntryPointDay).where(FactEntryPointDay.date >= start, FactEntryPointDay.date <= end)
    ).scalars().all()
    stock_rows = session.execute(select(FactStockSnapshot).where(FactStockSnapshot.snapshot_date >= start, FactStockSnapshot.snapshot_date <= end)).scalars().all()

    funnel_index = {(row.date, row.nm_id): row for row in funnel_rows}
    stock_rows_by_date_nm = _stock_rows_by_date_nm(stock_rows)
    entry_point_index = aggregate_entry_point_stats(entry_point_rows)
    ad_cost_index = aggregate_ad_cost_stats(ad_cost_rows)
    ad_campaign_index = aggregate_ad_campaign_stats(ad_campaign_rows)
    search_index = aggregate_search_stats(search_rows)
    localization_index = aggregate_localization_stats(localization_rows)
    search_reference_index = _search_reference_index(search_rows)
    localization_reference_index = _localization_reference_index(localization_rows)
    entry_point_reference_index = _entry_point_reference_index(entry_point_rows)
    orders_geography_csv_keys = _source_status_key_set(
        localization_rows,
        date_getter=_localization_report_date,
        source_status="CSV_EXPORT",
    )
    entry_point_csv_keys = _source_status_key_set(
        entry_point_rows,
        date_getter=lambda row: getattr(row, "date", None),
        source_status="CSV_EXPORT",
    )

    mart_rows: list[dict[str, Any]] = []
    for base_row in base_rows:
        report_date = base_row["report_date"]
        nm_id = base_row["nm_id"]
        stock_row = stock_rows_by_date_nm.get((report_date, nm_id))
        row = _build_mart_total_report_v2_row(
            base_row=base_row,
            stock_row=stock_row,
            funnel_row=funnel_index.get((report_date, nm_id)),
            entry_point_stats=entry_point_index.get((report_date, nm_id)),
            ad_cost_stats=ad_cost_index.get((report_date, nm_id)),
            ad_campaign_stats=ad_campaign_index.get((report_date, nm_id)),
            search_stats=search_index.get((report_date, nm_id)),
            localization_stats=localization_index.get((report_date, nm_id)),
        )
        search_ref = search_reference_index.get((report_date, nm_id))
        localization_ref = localization_reference_index.get((report_date, nm_id))
        entry_point_ref = entry_point_reference_index.get((report_date, nm_id))
        row["supplier_article"] = _first_nonempty(
            row.get("supplier_article"),
            getattr(entry_point_ref, "supplier_article", None),
            getattr(search_ref, "supplier_article", None),
            getattr(localization_ref, "supplier_article", None),
        )
        row["title"] = _first_nonempty(
            row.get("title"),
            getattr(entry_point_ref, "title", None),
            getattr(search_ref, "title", None),
            getattr(localization_ref, "title", None),
        )
        row["subject"] = _first_nonempty(
            row.get("subject"),
            getattr(entry_point_ref, "subject", None),
            getattr(search_ref, "subject", None),
            getattr(localization_ref, "subject", None),
        )
        row["brand"] = _first_nonempty(
            row.get("brand"),
            getattr(entry_point_ref, "brand", None),
            getattr(search_ref, "brand", None),
            getattr(localization_ref, "brand", None),
        )
        if (report_date, nm_id) in orders_geography_csv_keys:
            row["orders_geography_status"] = "CSV_EXPORT"
        if (report_date, nm_id) in entry_point_csv_keys:
            row["entry_point_status"] = "CSV_EXPORT"
        mart_rows.append(row)

    rows_deleted_for_inactive = delete_mart_total_report_rows_for_inactive_products(
        session,
        start=start,
        end=end,
        active_nm_ids=active_nm_ids,
    )
    rows_upserted = upsert_mart_total_report(session, mart_rows)
    rows_in_db = count_mart_total_report_rows(session, start, end)
    duplicate_keys = count_mart_total_report_duplicates(session, start, end)
    rows_without_any_data = sum(
        1
        for row in mart_rows
        if not any(
            row.get(flag)
            for flag in (
                "has_funnel",
                "has_stock",
                "has_ad_cost",
                "has_ad_campaign",
                "has_search",
                "has_localization_partial",
            )
        )
    )
    formula_samples = [
        {
            "report_date": row["report_date"].isoformat(),
            "nm_id": row["nm_id"],
            "impressions": str(row["impressions"]) if row["impressions"] is not None else None,
            "card_clicks": str(row["card_clicks"]) if row["card_clicks"] is not None else None,
            "ctr_calc": str(row["ctr_calc"]) if row["ctr_calc"] is not None else None,
            "cart_count": str(row["cart_count"]) if row["cart_count"] is not None else None,
            "add_to_cart_conversion_calc": str(row["add_to_cart_conversion_calc"]) if row["add_to_cart_conversion_calc"] is not None else None,
            "order_count": str(row["order_count"]) if row["order_count"] is not None else None,
            "cart_to_order_conversion_calc": str(row["cart_to_order_conversion_calc"]) if row["cart_to_order_conversion_calc"] is not None else None,
            "ad_spend_total": str(row["ad_spend_total"]) if row["ad_spend_total"] is not None else None,
            "ad_atbs_total": str(row["ad_atbs_total"]) if row["ad_atbs_total"] is not None else None,
            "ad_clicks_total": str(row["ad_clicks_total"]) if row["ad_clicks_total"] is not None else None,
            "ad_cpc_calc": str(row["ad_cpc_calc"]) if row["ad_cpc_calc"] is not None else None,
            "ad_cost_per_cart_calc": str(row["ad_cost_per_cart_calc"]) if row["ad_cost_per_cart_calc"] is not None else None,
            "ad_orders_total": str(row["ad_orders_total"]) if row["ad_orders_total"] is not None else None,
            "ad_cpo_calc": str(row["ad_cpo_calc"]) if row["ad_cpo_calc"] is not None else None,
            "associated_ad_atbs": str(row["associated_ad_atbs"]) if row["associated_ad_atbs"] is not None else None,
            "associated_atbs_percent_calc": str(row["associated_atbs_percent_calc"]) if row["associated_atbs_percent_calc"] is not None else None,
        }
        for row in mart_rows
        if any(
            row.get(field) is not None
            for field in (
                "ctr_calc",
                "add_to_cart_conversion_calc",
                "cart_to_order_conversion_calc",
                "ad_cpc_calc",
                "ad_cpo_calc",
            )
        )
    ][:5]

    return {
        "version": "v2",
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "active_products_count": len(active_products),
        "date_count": len(date_series),
        "expected_rows": len(active_products) * len(date_series),
        "rows_built": len(mart_rows),
        "rows_deleted_for_inactive": rows_deleted_for_inactive,
        "rows_upserted": rows_upserted,
        "actual_mart_rows": rows_in_db,
        "rows_in_db": rows_in_db,
        "duplicate_keys": duplicate_keys,
        "rows_with_funnel": sum(1 for row in mart_rows if row.get("has_funnel")),
        "rows_with_stock": sum(1 for row in mart_rows if row.get("has_stock")),
        "rows_with_ad_cost": sum(1 for row in mart_rows if row.get("has_ad_cost")),
        "rows_with_ad_campaign": sum(1 for row in mart_rows if row.get("has_ad_campaign")),
        "rows_with_search": sum(1 for row in mart_rows if row.get("has_search")),
        "rows_with_localization_partial": sum(1 for row in mart_rows if row.get("has_localization_partial")),
        "rows_with_entry_points": sum(1 for row in mart_rows if row.get("has_entry_points")),
        "rows_without_any_data": rows_without_any_data,
        "sum_ad_spend_total": str(_sum_decimal(row.get("ad_spend_total") for row in mart_rows)) if _sum_decimal(row.get("ad_spend_total") for row in mart_rows) is not None else None,
        "sum_ad_cost_writeoff_total": str(_sum_decimal(row.get("ad_cost_writeoff_total") for row in mart_rows)) if _sum_decimal(row.get("ad_cost_writeoff_total") for row in mart_rows) is not None else None,
        "sum_ad_campaign_spend_total": str(_sum_decimal(row.get("ad_campaign_spend_total") for row in mart_rows)) if _sum_decimal(row.get("ad_campaign_spend_total") for row in mart_rows) is not None else None,
        "sum_ad_atbs_total": str(_sum_decimal(row.get("ad_atbs_total") for row in mart_rows)) if _sum_decimal(row.get("ad_atbs_total") for row in mart_rows) is not None else None,
        "sum_direct_ad_atbs": str(_sum_decimal(row.get("direct_ad_atbs") for row in mart_rows)) if _sum_decimal(row.get("direct_ad_atbs") for row in mart_rows) is not None else None,
        "sum_associated_ad_atbs": str(_sum_decimal(row.get("associated_ad_atbs") for row in mart_rows)) if _sum_decimal(row.get("associated_ad_atbs") for row in mart_rows) is not None else None,
        "sum_multicard_ad_atbs": str(_sum_decimal(row.get("multicard_ad_atbs") for row in mart_rows)) if _sum_decimal(row.get("multicard_ad_atbs") for row in mart_rows) is not None else None,
        "sum_unknown_ad_atbs": str(_sum_decimal(row.get("unknown_ad_atbs") for row in mart_rows)) if _sum_decimal(row.get("unknown_ad_atbs") for row in mart_rows) is not None else None,
        "rows_with_ad_cost_per_cart": sum(1 for row in mart_rows if row.get("ad_cost_per_cart_calc") is not None),
        "rows_with_ad_cpo": sum(1 for row in mart_rows if row.get("ad_cpo_calc") is not None),
        "rows_with_associated_percent": sum(1 for row in mart_rows if row.get("associated_atbs_percent_calc") is not None),
        "count_unallocated_ad_cost_excluded": sum(1 for row in ad_cost_rows if row.nm_id is None),
        "rows_with_associated_ad_atbs": sum(1 for row in mart_rows if row.get("associated_ad_atbs") not in (None, Decimal("0"), 0)),
        "formula_samples": formula_samples,
    }


