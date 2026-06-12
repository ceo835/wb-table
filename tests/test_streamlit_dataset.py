from __future__ import annotations

from src.streamlit_dataset import enrich_streamlit_row


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
