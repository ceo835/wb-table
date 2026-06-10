from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.db.ad_campaign_loader import (
    FACT_AD_CAMPAIGN_DAY_CONFLICT_COLUMNS,
    FACT_AD_CAMPAIGN_NM_DAY_CONFLICT_COLUMNS,
    build_fact_ad_campaign_day_db_row,
    build_fact_ad_campaign_nm_day_db_row,
    prepare_fact_ad_campaign_day_upsert_rows,
    prepare_fact_ad_campaign_nm_day_upsert_rows,
)


def test_fact_ad_campaign_day_conflict_columns_match_natural_key():
    assert FACT_AD_CAMPAIGN_DAY_CONFLICT_COLUMNS == ("date", "advert_id", "row_type")


def test_fact_ad_campaign_nm_day_conflict_columns_match_natural_key():
    assert FACT_AD_CAMPAIGN_NM_DAY_CONFLICT_COLUMNS == ("date", "advert_id", "row_type", "conversion_type_raw", "nm_id")


def test_build_fact_ad_campaign_day_db_row_preserves_nulls():
    row = build_fact_ad_campaign_day_db_row(
        {
            "date": "2026-06-01",
            "advertId": 123,
            "campaign_name": "Campaign",
            "row_type": "Итог кампании",
            "ad_spend": 10.5,
            "ad_revenue": "",
            "ad_views": 20,
            "ad_clicks": "",
            "ad_atbs": "",
            "ad_orders": 2,
            "ordered_items_qty": "",
            "ad_cancels": "",
            "avg_position": "",
            "ad_ctr": "",
            "ad_cpc": "",
            "ad_cpm": "",
            "ad_cr": "",
            "ad_roi": "",
            "currency": "RUB",
            "data_status": "REAL_API",
            "source_status": "PARTIAL",
            "loaded_at": "2026-06-05T10:00:00+05:00",
        }
    )
    assert row["date"] == date(2026, 6, 1)
    assert row["ad_spend"] == Decimal("10.5")
    assert row["ad_revenue"] is None
    assert row["ad_clicks"] is None
    assert row["currency"] == "RUB"


def test_build_fact_ad_campaign_nm_day_db_row_preserves_conversion_fields():
    row = build_fact_ad_campaign_nm_day_db_row(
        {
            "date": "2026-06-01",
            "advertId": 123,
            "campaign_name": "Campaign",
            "row_type": "Товар",
            "conversion_type": "UNKNOWN",
            "conversion_type_raw": 64,
            "conversion_type_display": "UNKNOWN_CODE_64",
            "nm_id": 197330807,
            "product_name": "Product",
            "ad_spend": 12,
            "ad_revenue": "",
            "ad_views": 100,
            "ad_clicks": 2,
            "ad_atbs": "",
            "ad_orders": "",
            "ordered_items_qty": "",
            "ad_cancels": "",
            "avg_position": "",
            "ad_ctr": "",
            "ad_cpc": "",
            "ad_cpm": "",
            "ad_cr": "",
            "ad_roi": "",
            "currency": "RUB",
            "data_status": "REAL_API",
            "source_status": "PARTIAL",
            "loaded_at": "2026-06-05T10:00:00+05:00",
        }
    )
    assert row["conversion_type"] == "UNKNOWN"
    assert row["conversion_type_raw"] == 64
    assert row["conversion_type_display"] == "UNKNOWN_CODE_64"
    assert row["ad_spend"] == Decimal("12")
    assert row["ad_revenue"] is None


def test_build_fact_ad_campaign_nm_day_db_row_builds_display_from_raw_code():
    row = build_fact_ad_campaign_nm_day_db_row(
        {
            "date": "2026-06-01",
            "advertId": 123,
            "campaign_name": "Campaign",
            "row_type": "РўРѕРІР°СЂ",
            "conversion_type": "MULTICARD",
            "conversion_type_raw": 32,
            "nm_id": 197330807,
            "loaded_at": "2026-06-05T10:00:00+05:00",
        }
    )
    assert row["conversion_type_display"] == "Мультикарточка"


def test_build_fact_ad_campaign_nm_day_db_row_keeps_total_row_conversion_fields_empty():
    row = build_fact_ad_campaign_nm_day_db_row(
        {
            "date": "2026-06-01",
            "advertId": 123,
            "campaign_name": "Campaign",
            "row_type": "Итог кампании",
            "conversion_type": "",
            "conversion_type_raw": "",
            "conversion_type_display": "",
            "nm_id": 197330807,
            "loaded_at": "2026-06-05T10:00:00+05:00",
        }
    )
    assert row["conversion_type"] is None
    assert row["conversion_type_raw"] is None
    assert row["conversion_type_display"] is None


def test_prepare_fact_ad_campaign_day_upsert_rows_deduplicates():
    rows = prepare_fact_ad_campaign_day_upsert_rows(
        [
            {"date": "2026-06-01", "advertId": 123, "row_type": "Итог кампании", "ad_spend": 10, "loaded_at": "2026-06-05T10:00:00+05:00"},
            {"date": "2026-06-01", "advertId": 123, "row_type": "Итог кампании", "ad_spend": 20, "loaded_at": "2026-06-05T10:00:00+05:00"},
        ]
    )
    assert len(rows) == 1
    assert rows[0]["ad_spend"] == Decimal("20")


def test_prepare_fact_ad_campaign_nm_day_upsert_rows_deduplicates_by_raw_code():
    rows = prepare_fact_ad_campaign_nm_day_upsert_rows(
        [
            {
                "date": "2026-06-01",
                "advertId": 123,
                "row_type": "Товар",
                "conversion_type_raw": 64,
                "nm_id": 197330807,
                "ad_spend": 10,
                "loaded_at": "2026-06-05T10:00:00+05:00",
            },
            {
                "date": "2026-06-01",
                "advertId": 123,
                "row_type": "Товар",
                "conversion_type_raw": 64,
                "nm_id": 197330807,
                "ad_spend": 15,
                "loaded_at": "2026-06-05T10:00:00+05:00",
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["ad_spend"] == Decimal("15")


def test_prepare_fact_ad_campaign_nm_day_upsert_rows_keeps_null_metrics_null():
    rows = prepare_fact_ad_campaign_nm_day_upsert_rows(
        [
            {
                "date": "2026-06-01",
                "advertId": 123,
                "row_type": "РўРѕРІР°СЂ",
                "conversion_type_raw": 64,
                "nm_id": 197330807,
                "ad_clicks": "",
                "ad_ctr": "",
                "loaded_at": "2026-06-05T10:00:00+05:00",
            }
        ]
    )
    assert len(rows) == 1
    assert rows[0]["ad_clicks"] is None
    assert rows[0]["ad_ctr"] is None
