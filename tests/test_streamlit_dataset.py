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
