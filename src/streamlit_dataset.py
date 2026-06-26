from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence


STREAMLIT_V1_COLUMNS = [
    "report_date",
    "nm_id",
    "supplier_article",
    "title",
    "brand",
    "subject",
    "wb_buyer_price",
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
    "current_stock_sum",
    "local_orders_percent",
    "avg_delivery_time",
    "ad_cost_writeoff_total",
    "ad_campaign_spend_total",
    "legacy_cpm_common_calc",
    "legacy_cost_per_card_click_calc",
    "legacy_cost_per_all_carts_calc",
    "legacy_cost_per_order_calc",
    "legacy_ad_share_of_order_sum_pct",
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
    "ad_data_note",
    "card_clicks_note",
    "search_data_note",
    "stock_data_note",
    "localization_data_note",
    "entry_point_data_note",
    "vbro_data_note",
    "vvbromo_organic_sales",
    "vvbromo_operating_profit",
    "vvbromo_operating_profit_per_unit",
    "crm_common_calc",
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
    "ad_data_note",
    "card_clicks_note",
    "impressions_source_note",
    "search_data_note",
    "stock_data_note",
    "localization_data_note",
    "entry_point_data_note",
    "vbro_data_note",
]

FUNNEL_ZERO_FILL_FIELDS = [
    "card_clicks",
    "cart_count",
    "add_to_cart_conversion_calc",
    "order_count",
    "cart_to_order_conversion_calc",
    "order_sum",
    "buyout_count",
    "buyout_sum",
    "buyout_percent",
]

AD_ZERO_FILL_FIELDS = [
    "ad_cost_writeoff_total",
    "ad_campaign_spend_total",
    "ad_views_total",
    "ad_clicks_total",
    "ad_atbs_total",
    "ad_orders_total",
    "direct_ad_atbs",
    "associated_ad_atbs",
    "multicard_ad_atbs",
    "unknown_ad_atbs",
]

AD_CAMPAIGN_ZERO_FILL_FIELDS = [
    "ad_campaign_spend_total",
    "ad_views_total",
    "ad_clicks_total",
    "ad_atbs_total",
    "ad_orders_total",
    "direct_ad_atbs",
    "associated_ad_atbs",
    "multicard_ad_atbs",
    "unknown_ad_atbs",
]

AD_COST_ZERO_FILL_FIELDS = ["ad_cost_writeoff_total"]


def _normalize_date(value: Any) -> date | None:
    if _is_missing(value):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.fromisoformat(str(value)).date()
    except Exception:
        return None


def _normalize_datetime(value: Any) -> datetime | None:
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        return value
    try:
        normalized_text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(normalized_text)
    except Exception:
        return None


def build_wb_price_snapshot_lookup(
    snapshot_rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[date, int], dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    for row in snapshot_rows:
        snapshot_date = _normalize_date(row.get("snapshot_date"))
        if snapshot_date is None or _is_missing(row.get("nm_id")):
            continue
        try:
            nm_id = int(row.get("nm_id"))
        except (TypeError, ValueError):
            continue
        normalized_rows.append(
            {
                "snapshot_date": snapshot_date,
                "snapshot_at": _normalize_datetime(row.get("snapshot_at")),
                "nm_id": nm_id,
                "buyer_visible_price": _to_decimal_or_none(row.get("buyer_visible_price")),
                "fetch_status": None if _is_missing(row.get("fetch_status")) else str(row.get("fetch_status")),
            }
        )

    normalized_rows.sort(
        key=lambda item: (
            item["nm_id"],
            item["snapshot_date"],
            item["snapshot_at"] or datetime.min,
        )
    )

    lookup: dict[tuple[date, int], dict[str, Any]] = {}
    previous_success_price_by_nm: dict[int, Decimal] = {}

    for row in normalized_rows:
        previous_success_price = previous_success_price_by_nm.get(row["nm_id"])
        current_price = row["buyer_visible_price"]
        price_delta = None
        price_alert = False
        if current_price is not None and previous_success_price is not None:
            price_delta = current_price - previous_success_price
            price_alert = abs(price_delta) >= Decimal("50")

        lookup[(row["snapshot_date"], row["nm_id"])] = {
            "wb_buyer_price": current_price,
            "previous_wb_buyer_price": previous_success_price,
            "wb_price_delta": price_delta,
            "wb_price_alert": price_alert,
            "wb_price_fetch_status": row["fetch_status"],
        }

        if row["fetch_status"] == "success" and current_price is not None:
            previous_success_price_by_nm[row["nm_id"]] = current_price

    return lookup


def attach_wb_price_snapshot_fields(
    rows: Sequence[Mapping[str, Any]],
    snapshot_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    price_lookup = build_wb_price_snapshot_lookup(snapshot_rows)
    attached_rows: list[dict[str, Any]] = []
    for row in rows:
        attached_row = dict(row)
        report_date = _normalize_date(row.get("report_date"))
        lookup_key: tuple[date, int] | None = None
        if report_date is not None and not _is_missing(row.get("nm_id")):
            try:
                lookup_key = (report_date, int(row.get("nm_id")))
            except (TypeError, ValueError):
                lookup_key = None
        price_payload = price_lookup.get(lookup_key, {}) if lookup_key is not None else {}
        attached_row["wb_buyer_price"] = price_payload.get("wb_buyer_price")
        attached_row["previous_wb_buyer_price"] = price_payload.get("previous_wb_buyer_price")
        attached_row["wb_price_delta"] = price_payload.get("wb_price_delta")
        attached_row["wb_price_alert"] = bool(price_payload.get("wb_price_alert", False))
        attached_rows.append(attached_row)
    return attached_rows


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value != value


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if _is_missing(value):
        return False
    return str(value).strip().lower() == "true"


def _to_bool_extended(value: Any) -> bool:
    if _is_missing(value):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    return s in ("true", "1", "yes", "y", "t", "on")


def _to_decimal_or_none(value: Any) -> Decimal | None:
    if _is_missing(value):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


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

    has_ad_cost = _to_bool(row.get("has_ad_cost"))
    has_ad_campaign = _to_bool(row.get("has_ad_campaign"))
    if has_ad_cost and has_ad_campaign:
        ad_data_note = "OK"
    elif has_ad_cost or has_ad_campaign:
        ad_data_note = "Частичные рекламные данные"
    else:
        ad_data_note = "Нет рекламы"

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
        "ad_data_note": ad_data_note,
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

    if _to_bool(enriched.get("has_funnel")):
        for field in FUNNEL_ZERO_FILL_FIELDS:
            if _is_missing(enriched.get(field)):
                enriched[field] = 0

    if _to_bool(enriched.get("has_ad_cost")):
        for field in AD_COST_ZERO_FILL_FIELDS:
            if _is_missing(enriched.get(field)):
                enriched[field] = 0

    if _to_bool(enriched.get("has_ad_campaign")):
        for field in AD_CAMPAIGN_ZERO_FILL_FIELDS:
            if _is_missing(enriched.get(field)):
                enriched[field] = 0

    if not (_to_bool(enriched.get("has_ad_cost")) or _to_bool(enriched.get("has_ad_campaign"))):
        for field in AD_ZERO_FILL_FIELDS:
            if _is_missing(enriched.get(field)):
                enriched[field] = 0

    if _is_missing(enriched.get("ad_cpc_calc")):
        enriched["ad_cpc_calc"] = _safe_divide(
            enriched.get("ad_campaign_spend_total"),
            enriched.get("ad_clicks_total"),
        )
    if _is_missing(enriched.get("legacy_cpm_common_calc")):
        enriched["legacy_cpm_common_calc"] = _safe_divide(
            enriched.get("ad_campaign_spend_total"),
            enriched.get("impressions"),
            Decimal("1000"),
        )
    if _is_missing(enriched.get("legacy_cost_per_card_click_calc")):
        enriched["legacy_cost_per_card_click_calc"] = _safe_divide(
            enriched.get("ad_campaign_spend_total"),
            enriched.get("card_clicks"),
        )
    if _is_missing(enriched.get("legacy_cost_per_all_carts_calc")):
        enriched["legacy_cost_per_all_carts_calc"] = _safe_divide(
            enriched.get("ad_campaign_spend_total"),
            enriched.get("cart_count"),
        )
    if _is_missing(enriched.get("legacy_cost_per_order_calc")):
        enriched["legacy_cost_per_order_calc"] = _safe_divide(
            enriched.get("ad_campaign_spend_total"),
            enriched.get("order_count"),
        )
    if _is_missing(enriched.get("legacy_ad_share_of_order_sum_pct")):
        enriched["legacy_ad_share_of_order_sum_pct"] = _safe_divide(
            enriched.get("ad_campaign_spend_total"),
            enriched.get("order_sum"),
            Decimal("100"),
        )
    if _is_missing(enriched.get("ad_cpm_calc")):
        enriched["ad_cpm_calc"] = _safe_divide(
            enriched.get("ad_campaign_spend_total"),
            enriched.get("ad_views_total"),
            Decimal("1000"),
        )
    if _is_missing(enriched.get("ad_cost_per_cart_calc")):
        enriched["ad_cost_per_cart_calc"] = _safe_divide(
            enriched.get("ad_campaign_spend_total"),
            enriched.get("ad_atbs_total"),
        )
    if _is_missing(enriched.get("ad_cpo_calc")):
        enriched["ad_cpo_calc"] = _safe_divide(
            enriched.get("ad_campaign_spend_total"),
            enriched.get("ad_orders_total"),
        )
    if _is_missing(enriched.get("ad_share_of_revenue_calc")):
        enriched["ad_share_of_revenue_calc"] = _safe_divide(
            enriched.get("ad_campaign_spend_total"),
            enriched.get("order_sum"),
            Decimal("100"),
        )
    if _is_missing(enriched.get("associated_atbs_percent_calc")):
        enriched["associated_atbs_percent_calc"] = _safe_divide(
            enriched.get("associated_ad_atbs"),
            enriched.get("ad_atbs_total"),
            Decimal("100"),
        )

    if _is_missing(enriched.get("organic_cart_count")):
        cart_count = _to_decimal_or_none(enriched.get("cart_count"))
        ad_atbs_total = _to_decimal_or_none(enriched.get("ad_atbs_total"))
        if cart_count is not None and ad_atbs_total is not None:
            enriched["organic_cart_count"] = cart_count - ad_atbs_total

    if _is_missing(enriched.get("organic_cart_share_calc")):
        enriched["organic_cart_share_calc"] = _safe_divide(
            enriched.get("organic_cart_count"),
            enriched.get("ad_atbs_total"),
            Decimal("100"),
        )

    if _is_missing(enriched.get("ad_cost_per_all_carts_calc")):
        cart_count = _to_decimal_or_none(enriched.get("cart_count"))
        associated_ad_atbs = _to_decimal_or_none(enriched.get("associated_ad_atbs")) or Decimal("0")
        denominator = None if cart_count is None else cart_count + associated_ad_atbs
        enriched["ad_cost_per_all_carts_calc"] = _safe_divide(
            enriched.get("ad_campaign_spend_total"),
            denominator,
        )

    profit = enriched.get("vvbromo_operating_profit")
    orders = enriched.get("order_count")
    if (
        profit is not None and not _is_missing(profit)
        and orders is not None and not _is_missing(orders)
        and float(orders) > 0
    ):
        enriched["crm_common_calc"] = float(profit) / float(orders)
    else:
        enriched["crm_common_calc"] = None

    return enriched


def attach_vvbromo_fields(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    import pandas as pd
    nm_ids = {int(r["nm_id"]) for r in rows if not _is_missing(r.get("nm_id"))}
    dates = {_normalize_date(r.get("report_date")) for r in rows if r.get("report_date") is not None}
    dates = {d for d in dates if d is not None}

    vvbromo_lookup = {}
    if nm_ids and dates:
        try:
            from src.db.session import session_scope
            from src.db.models import FactVvbromoProductDay
            from sqlalchemy import select
            with session_scope() as session:
                db_rows = session.execute(
                    select(FactVvbromoProductDay).where(
                        FactVvbromoProductDay.nm_id.in_(list(nm_ids)),
                        FactVvbromoProductDay.day.in_(list(dates))
                    )
                ).scalars().all()
                for r in db_rows:
                    r_date = _normalize_date(r.day)
                    if r_date is not None:
                        vvbromo_lookup[(r_date, int(r.nm_id))] = {
                            "vvbromo_organic_sales": r.organic_sales,
                            "vvbromo_operating_profit": float(r.operating_profit) if r.operating_profit is not None else None,
                            "vvbromo_operating_profit_per_unit": float(r.operating_profit_per_unit) if r.operating_profit_per_unit is not None else None,
                        }
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to load VVBromo data from DB: {e}")

    attached_rows: list[dict[str, Any]] = []
    for row in rows:
        attached_row = dict(row)
        report_date = _normalize_date(row.get("report_date"))
        lookup_key = None
        if report_date is not None and not _is_missing(row.get("nm_id")):
            try:
                lookup_key = (report_date, int(row.get("nm_id")))
            except (TypeError, ValueError):
                lookup_key = None

        attached_row["vvbromo_organic_sales"] = None
        attached_row["vvbromo_operating_profit"] = None
        attached_row["vvbromo_operating_profit_per_unit"] = None

        if lookup_key is not None and lookup_key in vvbromo_lookup:
            payload = vvbromo_lookup[lookup_key]
            attached_row["vvbromo_organic_sales"] = payload["vvbromo_organic_sales"]
            attached_row["vvbromo_operating_profit"] = payload["vvbromo_operating_profit"]
            attached_row["vvbromo_operating_profit_per_unit"] = payload["vvbromo_operating_profit_per_unit"]

        attached_rows.append(attached_row)
    return attached_rows


def aggregate_vvbromo_for_period(df: pd.DataFrame, groupby_cols: list[str]) -> pd.DataFrame:
    import pandas as pd
    if df.empty:
        return df.copy()

    # Agg dict with dynamic types
    agg_dict = {}
    for col in df.columns:
        if col in groupby_cols:
            continue
        if col in ("vvbromo_organic_sales", "vvbromo_operating_profit"):
            agg_dict[col] = lambda s: s.sum(min_count=1)
        elif col in ("vvbromo_operating_profit_per_unit", "crm_common_calc"):
            continue
        else:
            if df[col].dtype in ("int64", "float64"):
                agg_dict[col] = lambda s: s.sum(min_count=1)
            else:
                agg_dict[col] = "first"

    grouped = df.groupby(groupby_cols, as_index=False).agg(agg_dict)

    if "vvbromo_organic_sales" in grouped.columns and "vvbromo_operating_profit" in grouped.columns:
        def calc_per_unit(row):
            sales = row.get("vvbromo_organic_sales")
            profit = row.get("vvbromo_operating_profit")
            if pd.isna(sales) or sales == 0:
                return None
            if pd.isna(profit):
                return None
            return float(profit) / float(sales)

        grouped["vvbromo_operating_profit_per_unit"] = grouped.apply(calc_per_unit, axis=1)

    if "vvbromo_operating_profit" in grouped.columns and "order_count" in grouped.columns:
        def calc_crm(row):
            profit = row.get("vvbromo_operating_profit")
            orders = row.get("order_count")
            if pd.isna(profit) or pd.isna(orders) or orders == 0:
                return None
            return float(profit) / float(orders)

        grouped["crm_common_calc"] = grouped.apply(calc_crm, axis=1)

    return grouped
