from __future__ import annotations

from src.streamlit_dataset import attach_wb_price_snapshot_fields, enrich_streamlit_row


def test_enrich_streamlit_row_uses_entry_point_impressions_for_display_fields():
    row = enrich_streamlit_row(
        {
            "report_date": "2026-06-07",
            "nm_id": 197330807,
            "impressions": None,
            "ctr_calc": None,
            "entry_impressions_total": 138486,
            "entry_card_clicks_total": 6118,
            "entry_ctr_calc": 4.42,
            "entry_point_status": "CSV_EXPORT",
            "orders_geography_status": "FILE_IMPORT_PENDING",
            "vbro_status": "MANUAL_PENDING",
            "has_funnel": True,
            "has_stock": False,
            "has_ad_cost": False,
            "has_ad_campaign": False,
            "has_search": False,
            "has_localization_partial": False,
        }
    )

    assert row["display_impressions"] == 138486
    assert row["display_ctr_calc"] == 4.42
    assert row["impressions_source_note"] == "Показы взяты из файла Точка входа"


def test_enrich_streamlit_row_zero_fills_funnel_fields_only_when_has_funnel_true():
    row = enrich_streamlit_row(
        {
            "has_funnel": True,
            "has_stock": False,
            "has_ad_cost": False,
            "has_ad_campaign": False,
            "has_search": False,
            "has_localization_partial": False,
            "entry_point_status": "FILE_IMPORT_PENDING",
            "orders_geography_status": "FILE_IMPORT_PENDING",
            "vbro_status": "MANUAL_PENDING",
            "impressions": None,
            "card_clicks": None,
            "cart_count": None,
            "add_to_cart_conversion_calc": None,
            "order_count": None,
            "cart_to_order_conversion_calc": None,
            "order_sum": None,
            "buyout_count": None,
            "buyout_sum": None,
        }
    )

    assert row["impressions"] is None
    assert row["card_clicks"] == 0
    assert row["cart_count"] == 0
    assert row["add_to_cart_conversion_calc"] == 0
    assert row["order_count"] == 0
    assert row["cart_to_order_conversion_calc"] == 0
    assert row["order_sum"] == 0
    assert row["buyout_count"] == 0
    assert row["buyout_sum"] == 0
    assert row["funnel_data_note"] == "Воронка есть, но WB отдал неполные данные"


def test_enrich_streamlit_row_zero_fills_ad_fields_and_sets_no_ads_note():
    row = enrich_streamlit_row(
        {
            "has_funnel": False,
            "has_stock": False,
            "has_ad_cost": False,
            "has_ad_campaign": False,
            "has_search": False,
            "has_localization_partial": False,
            "entry_point_status": "FILE_IMPORT_PENDING",
            "orders_geography_status": "FILE_IMPORT_PENDING",
            "vbro_status": "MANUAL_PENDING",
            "ad_cost_writeoff_total": None,
            "ad_campaign_spend_total": None,
            "ad_views_total": None,
            "ad_clicks_total": None,
            "ad_atbs_total": None,
            "ad_orders_total": None,
        }
    )

    assert row["ad_cost_writeoff_total"] == 0
    assert row["ad_campaign_spend_total"] == 0
    assert row["ad_views_total"] == 0
    assert row["ad_clicks_total"] == 0
    assert row["ad_atbs_total"] == 0
    assert row["ad_orders_total"] == 0
    assert row["ad_data_note"] == "Нет рекламы"


def test_enrich_streamlit_row_zero_fills_campaign_metrics_but_keeps_missing_cost_as_partial() -> None:
    row = enrich_streamlit_row(
        {
            "has_funnel": True,
            "has_stock": False,
            "has_ad_cost": False,
            "has_ad_campaign": True,
            "has_search": False,
            "has_localization_partial": False,
            "entry_point_status": "FILE_IMPORT_PENDING",
            "orders_geography_status": "FILE_IMPORT_PENDING",
            "vbro_status": "MANUAL_PENDING",
            "cart_count": 5,
            "order_sum": 100,
            "ad_cost_writeoff_total": None,
            "ad_campaign_spend_total": None,
            "ad_views_total": None,
            "ad_clicks_total": None,
            "ad_atbs_total": None,
            "ad_orders_total": None,
            "ad_cpc_calc": None,
            "ad_cpm_calc": None,
            "ad_cost_per_cart_calc": None,
            "ad_cpo_calc": None,
            "organic_cart_count": None,
            "organic_cart_share_calc": None,
        }
    )

    assert row["ad_cost_writeoff_total"] is None
    assert row["ad_campaign_spend_total"] == 0
    assert row["ad_views_total"] == 0
    assert row["ad_clicks_total"] == 0
    assert row["ad_atbs_total"] == 0
    assert row["ad_orders_total"] == 0
    assert row["ad_cpc_calc"] is None
    assert row["ad_cpm_calc"] is None
    assert row["ad_cost_per_cart_calc"] is None
    assert row["ad_cpo_calc"] is None
    assert row["organic_cart_count"] == 5
    assert row["organic_cart_share_calc"] is None
    assert row["ad_data_note"] == "Частичные рекламные данные"


def test_enrich_streamlit_row_recalculates_ad_formulas_when_operands_present() -> None:
    row = enrich_streamlit_row(
        {
            "has_funnel": True,
            "has_stock": False,
            "has_ad_cost": True,
            "has_ad_campaign": True,
            "has_search": False,
            "has_localization_partial": False,
            "entry_point_status": "FILE_IMPORT_PENDING",
            "orders_geography_status": "FILE_IMPORT_PENDING",
            "vbro_status": "MANUAL_PENDING",
            "cart_count": 10,
            "order_sum": 200,
            "ad_cost_writeoff_total": 30,
            "ad_campaign_spend_total": 30,
            "ad_views_total": 150,
            "ad_clicks_total": 15,
            "ad_atbs_total": 5,
            "ad_orders_total": 2,
            "associated_ad_atbs": 1,
            "ad_cpc_calc": None,
            "ad_cpm_calc": None,
            "ad_cost_per_cart_calc": None,
            "ad_cpo_calc": None,
            "ad_share_of_revenue_calc": None,
            "associated_atbs_percent_calc": None,
            "organic_cart_count": None,
            "organic_cart_share_calc": None,
            "ad_cost_per_all_carts_calc": None,
        }
    )

    assert float(row["ad_cpc_calc"]) == 2.0
    assert float(row["ad_cpm_calc"]) == 200.0
    assert float(row["ad_cost_per_cart_calc"]) == 6.0
    assert float(row["ad_cpo_calc"]) == 15.0
    assert float(row["ad_share_of_revenue_calc"]) == 15.0
    assert float(row["associated_atbs_percent_calc"]) == 20.0
    assert float(row["organic_cart_count"]) == 5.0
    assert float(row["organic_cart_share_calc"]) == 100.0
    assert abs(float(row["ad_cost_per_all_carts_calc"]) - (30 / 11)) < 1e-9


def test_enrich_streamlit_row_calculates_legacy_ad_metrics_from_common_funnel() -> None:
    row = enrich_streamlit_row(
        {
            "has_funnel": True,
            "has_stock": False,
            "has_ad_cost": True,
            "has_ad_campaign": True,
            "has_search": False,
            "has_localization_partial": False,
            "entry_point_status": "FILE_IMPORT_PENDING",
            "orders_geography_status": "FILE_IMPORT_PENDING",
            "vbro_status": "MANUAL_PENDING",
            "impressions": 3449,
            "card_clicks": 274,
            "cart_count": 21,
            "order_count": 2,
            "order_sum": 2346,
            "ad_campaign_spend_total": 137.48,
            "legacy_cpm_common_calc": None,
            "legacy_cost_per_card_click_calc": None,
            "legacy_cost_per_all_carts_calc": None,
            "legacy_cost_per_order_calc": None,
            "legacy_ad_share_of_order_sum_pct": None,
        }
    )

    assert abs(float(row["legacy_cpm_common_calc"]) - (137.48 / 3449 * 1000)) < 1e-9
    assert abs(float(row["legacy_cost_per_card_click_calc"]) - (137.48 / 274)) < 1e-9
    assert abs(float(row["legacy_cost_per_all_carts_calc"]) - (137.48 / 21)) < 1e-9
    assert abs(float(row["legacy_cost_per_order_calc"]) - (137.48 / 2)) < 1e-9
    assert abs(float(row["legacy_ad_share_of_order_sum_pct"]) - (137.48 / 2346 * 100)) < 1e-9


def test_enrich_streamlit_row_keeps_legacy_metrics_null_when_denominator_missing_or_zero() -> None:
    row = enrich_streamlit_row(
        {
            "has_funnel": True,
            "has_stock": False,
            "has_ad_cost": True,
            "has_ad_campaign": True,
            "has_search": False,
            "has_localization_partial": False,
            "entry_point_status": "FILE_IMPORT_PENDING",
            "orders_geography_status": "FILE_IMPORT_PENDING",
            "vbro_status": "MANUAL_PENDING",
            "impressions": None,
            "card_clicks": 0,
            "cart_count": 0,
            "order_count": None,
            "order_sum": 0,
            "ad_campaign_spend_total": 137.48,
            "legacy_cpm_common_calc": None,
            "legacy_cost_per_card_click_calc": None,
            "legacy_cost_per_all_carts_calc": None,
            "legacy_cost_per_order_calc": None,
            "legacy_ad_share_of_order_sum_pct": None,
        }
    )

    assert row["legacy_cpm_common_calc"] is None
    assert row["legacy_cost_per_card_click_calc"] is None
    assert row["legacy_cost_per_all_carts_calc"] is None
    assert row["legacy_cost_per_order_calc"] is None
    assert row["legacy_ad_share_of_order_sum_pct"] is None


def test_attach_wb_price_snapshot_fields_uses_exact_date_and_last_prior_success_price() -> None:
    rows = [
        {"report_date": "2026-06-10", "nm_id": 91470767},
        {"report_date": "2026-06-11", "nm_id": 91470767},
        {"report_date": "2026-06-11", "nm_id": 37320545},
    ]
    snapshot_rows = [
        {
            "snapshot_date": "2026-06-08",
            "snapshot_at": "2026-06-08T08:00:00+00:00",
            "nm_id": 91470767,
            "buyer_visible_price": "730.00",
            "fetch_status": "success",
        },
        {
            "snapshot_date": "2026-06-10",
            "snapshot_at": "2026-06-10T08:00:00+00:00",
            "nm_id": 91470767,
            "buyer_visible_price": "799.00",
            "fetch_status": "success",
        },
        {
            "snapshot_date": "2026-06-11",
            "snapshot_at": "2026-06-11T08:00:00+00:00",
            "nm_id": 91470767,
            "buyer_visible_price": "1022.00",
            "fetch_status": "success",
        },
        {
            "snapshot_date": "2026-06-11",
            "snapshot_at": "2026-06-11T08:05:00+00:00",
            "nm_id": 37320545,
            "buyer_visible_price": None,
            "fetch_status": "wb_interstitial",
        },
    ]

    attached = attach_wb_price_snapshot_fields(rows, snapshot_rows)

    assert float(attached[0]["wb_buyer_price"]) == 799.0
    assert float(attached[0]["previous_wb_buyer_price"]) == 730.0
    assert float(attached[0]["wb_price_delta"]) == 69.0
    assert attached[0]["wb_price_alert"] is True

    assert float(attached[1]["wb_buyer_price"]) == 1022.0
    assert float(attached[1]["previous_wb_buyer_price"]) == 799.0
    assert float(attached[1]["wb_price_delta"]) == 223.0
    assert attached[1]["wb_price_alert"] is True

    assert attached[2]["wb_buyer_price"] is None
    assert attached[2]["previous_wb_buyer_price"] is None
    assert attached[2]["wb_price_delta"] is None
    assert attached[2]["wb_price_alert"] is False
