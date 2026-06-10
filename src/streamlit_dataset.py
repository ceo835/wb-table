from __future__ import annotations

from typing import Any, Mapping


STREAMLIT_V1_COLUMNS = [
    "report_date",
    "nm_id",
    "supplier_article",
    "title",
    "brand",
    "subject",
    "display_impressions",
    "display_ctr_calc",
    "impressions_source_note",
    "impressions",
    "card_clicks",
    "ctr_calc",
    "entry_impressions_total",
    "entry_card_clicks_total",
    "entry_ctr_calc",
    "cart_count",
    "add_to_cart_conversion_calc",
    "entry_cart_total",
    "entry_cart_conversion_calc",
    "order_count",
    "cart_to_order_conversion_calc",
    "entry_orders_total",
    "entry_order_conversion_calc",
    "order_sum",
    "buyout_count",
    "buyout_sum",
    "buyout_percent",
    "current_stock_qty",
    "current_mp_stock_qty",
    "local_orders_percent",
    "ad_cost_writeoff_total",
    "ad_campaign_spend_total",
    "ad_views_total",
    "ad_clicks_total",
    "ad_atbs_total",
    "ad_orders_total",
    "ad_cpc_calc",
    "ad_cpm_calc",
    "ad_cost_per_cart_calc",
    "ad_cpo_calc",
    "ad_share_of_revenue_calc",
    "direct_ad_atbs",
    "associated_ad_atbs",
    "multicard_ad_atbs",
    "unknown_ad_atbs",
    "associated_atbs_percent_calc",
    "organic_cart_count",
    "organic_cart_share_calc",
    "ad_cost_per_all_carts_calc",
    "organic_cart_share_status",
    "search_queries_count",
    "search_avg_position",
    "search_visibility",
    "search_clicks",
    "search_cart",
    "search_orders",
    "localization_orders_total_qty",
    "localization_regions_count",
    "has_funnel",
    "has_stock",
    "has_ad_cost",
    "has_ad_campaign",
    "has_search",
    "has_localization_partial",
    "entry_point_status",
    "orders_geography_status",
    "vbro_status",
    "card_comparison_status",
    "data_quality_status",
    "data_quality_label",
    "funnel_data_note",
    "card_clicks_note",
    "search_data_note",
    "stock_data_note",
    "localization_data_note",
    "entry_point_data_note",
    "vbro_data_note",
]

SOURCE_FLAG_FIELDS = [
    "has_funnel",
    "has_stock",
    "has_ad_cost",
    "has_ad_campaign",
    "has_search",
    "has_localization_partial",
]

DATA_QUALITY_LABELS = {
    "OK_PARTIAL_SOURCES": "Данные есть, внешние источники ожидаются",
    "NO_DATA": "Нет данных",
    "PARTIAL": "Частично",
}

NOTE_COLUMNS = [
    "funnel_data_note",
    "card_clicks_note",
    "impressions_source_note",
    "search_data_note",
    "stock_data_note",
    "localization_data_note",
    "entry_point_data_note",
    "vbro_data_note",
]


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value != value


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if _is_missing(value):
        return False
    return str(value).strip().lower() == "true"


def has_any_source(row: Mapping[str, Any]) -> bool:
    return any(_to_bool(row.get(field)) for field in SOURCE_FLAG_FIELDS)


def has_core_coverage(row: Mapping[str, Any]) -> bool:
    return _to_bool(row.get("has_funnel")) or _to_bool(row.get("has_ad_cost")) or _to_bool(row.get("has_ad_campaign"))


def compute_data_quality_status(row: Mapping[str, Any]) -> str:
    if not has_any_source(row):
        return "NO_DATA"
    if has_core_coverage(row):
        return "OK_PARTIAL_SOURCES"
    return "PARTIAL"


def build_data_quality_label(status: Any) -> str:
    if _is_missing(status):
        return "—"
    return DATA_QUALITY_LABELS.get(str(status), str(status))


def _has_sparse_funnel_payload(row: Mapping[str, Any]) -> bool:
    core_fields = ("impressions", "card_clicks", "cart_count", "order_count", "order_sum")
    filled_count = sum(0 if _is_missing(row.get(field)) else 1 for field in core_fields)
    return filled_count <= 1


def build_note_columns(row: Mapping[str, Any]) -> dict[str, str]:
    has_funnel = _to_bool(row.get("has_funnel"))
    has_search = _to_bool(row.get("has_search"))
    has_stock = _to_bool(row.get("has_stock"))
    has_localization_partial = _to_bool(row.get("has_localization_partial"))
    orders_geography_status = row.get("orders_geography_status")
    entry_point_status = row.get("entry_point_status")
    vbro_status = row.get("vbro_status")

    if _is_missing(row.get("card_clicks")):
        card_clicks_note = "API не передал переходы в карточку"
    else:
        card_clicks_note = "OK"

    if _is_missing(row.get("impressions")) and not _is_missing(row.get("entry_impressions_total")):
        impressions_source_note = "Показы взяты из файла Точка входа"
    elif _is_missing(row.get("impressions")):
        impressions_source_note = "Нет подтверждённого источника показов"
    else:
        impressions_source_note = "OK"

    if not has_funnel:
        funnel_data_note = "Нет строки воронки за дату"
    elif _has_sparse_funnel_payload(row):
        funnel_data_note = "Воронка есть, но WB отдал неполные данные"
    else:
        funnel_data_note = "OK"

    search_data_note = "OK" if has_search else "Нет данных поиска за дату или источник не отдал"
    stock_data_note = "OK" if has_stock else "Нет snapshot остатков за дату"

    if has_localization_partial:
        localization_data_note = "Есть partial/API localization"
    elif orders_geography_status == "FILE_IMPORT_PENDING":
        localization_data_note = "Ожидается файл География"
    else:
        localization_data_note = "Нет данных географии"

    if entry_point_status == "FILE_IMPORT_PENDING":
        entry_point_data_note = "Ожидается файл Точка входа"
    else:
        entry_point_data_note = "OK"

    if vbro_status == "MANUAL_PENDING":
        vbro_data_note = "Ожидается ручной ввод/файл ВБро"
    else:
        vbro_data_note = "OK"

    return {
        "funnel_data_note": funnel_data_note,
        "card_clicks_note": card_clicks_note,
        "impressions_source_note": impressions_source_note,
        "search_data_note": search_data_note,
        "stock_data_note": stock_data_note,
        "localization_data_note": localization_data_note,
        "entry_point_data_note": entry_point_data_note,
        "vbro_data_note": vbro_data_note,
    }


def enrich_streamlit_row(row: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    if _is_missing(enriched.get("display_impressions")):
        enriched["display_impressions"] = (
            enriched.get("impressions")
            if not _is_missing(enriched.get("impressions"))
            else enriched.get("entry_impressions_total")
        )
    if _is_missing(enriched.get("display_ctr_calc")):
        enriched["display_ctr_calc"] = (
            enriched.get("ctr_calc")
            if not _is_missing(enriched.get("ctr_calc"))
            else enriched.get("entry_ctr_calc")
        )
    if _is_missing(enriched.get("data_quality_status")):
        enriched["data_quality_status"] = compute_data_quality_status(enriched)
    enriched["data_quality_label"] = build_data_quality_label(enriched["data_quality_status"])
    enriched.update(build_note_columns(enriched))
    return enriched
