from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from src.ad_campaign_product_dataset import (
    AD_CAMPAIGN_PRODUCT_COLUMNS,
    build_ad_campaign_product_rows,
)


def test_build_ad_campaign_product_rows_calculates_metrics_and_uses_mart_identity() -> None:
    campaign_rows = [
        {
            "date": date(2026, 6, 7),
            "advert_id": 1001,
            "campaign_name": "РК 1001",
            "row_type": "PRODUCT",
            "conversion_type": "DIRECT",
            "conversion_type_raw": 1,
            "conversion_type_display": "Прямая",
            "nm_id": 197330807,
            "product_name": "Товар из fullstats",
            "ad_spend": Decimal("500.00"),
            "ad_views": Decimal("10000"),
            "ad_clicks": Decimal("250"),
            "ad_atbs": Decimal("50"),
            "ad_orders": Decimal("10"),
            "loaded_at": datetime(2026, 6, 9, tzinfo=timezone.utc),
        }
    ]
    mart_rows = [
        {
            "report_date": date(2026, 6, 7),
            "nm_id": 197330807,
            "supplier_article": "BlackWOM5",
            "title": "Трусы",
            "brand": "PALEY",
            "subject": "Трусы",
            "order_sum": Decimal("2500.00"),
        }
    ]
    ad_cost_event_rows = [
        {
            "date": date(2026, 6, 7),
            "advert_id": 1001,
            "nm_id": 197330807,
            "campaign_type": "Поиск",
        }
    ]

    rows = build_ad_campaign_product_rows(
        campaign_rows=campaign_rows,
        mart_rows=mart_rows,
        ad_cost_event_rows=ad_cost_event_rows,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["report_date"] == date(2026, 6, 7)
    assert row["supplier_article"] == "BlackWOM5"
    assert row["title"] == "Трусы"
    assert row["campaign_type"] == "Поиск"
    assert row["conversion_type"] == "Прямая"
    assert row["campaign_spend"] == Decimal("500.00")
    assert row["ad_cpc_calc"] == Decimal("2")
    assert row["ad_cpm_calc"] == Decimal("50")
    assert row["ad_cost_per_cart_calc"] == Decimal("10")
    assert row["ad_cpo_calc"] == Decimal("50")
    assert row["order_sum"] == Decimal("2500.00")
    assert row["ad_share_of_order_sum_calc"] == Decimal("20")


def test_build_ad_campaign_product_rows_keeps_nulls_when_denominator_missing() -> None:
    campaign_rows = [
        {
            "date": date(2026, 6, 7),
            "advert_id": 1002,
            "campaign_name": "РК 1002",
            "row_type": "PRODUCT",
            "conversion_type": "UNKNOWN",
            "conversion_type_raw": 64,
            "conversion_type_display": "UNKNOWN_CODE_64",
            "nm_id": 197330807,
            "product_name": "Товар из fullstats",
            "ad_spend": Decimal("100.00"),
            "ad_views": None,
            "ad_clicks": Decimal("0"),
            "ad_atbs": None,
            "ad_orders": Decimal("0"),
            "loaded_at": datetime(2026, 6, 9, tzinfo=timezone.utc),
        }
    ]
    mart_rows = [
        {
            "report_date": date(2026, 6, 7),
            "nm_id": 197330807,
            "supplier_article": "BlackWOM5",
            "title": "Трусы",
            "brand": "PALEY",
            "subject": "Трусы",
            "order_sum": None,
        }
    ]

    rows = build_ad_campaign_product_rows(
        campaign_rows=campaign_rows,
        mart_rows=mart_rows,
        ad_cost_event_rows=[],
    )

    row = rows[0]
    assert row["campaign_type"] is None
    assert row["conversion_type"] == "UNKNOWN_CODE_64"
    assert row["ad_cpc_calc"] is None
    assert row["ad_cpm_calc"] is None
    assert row["ad_cost_per_cart_calc"] is None
    assert row["ad_cpo_calc"] is None
    assert row["ad_share_of_order_sum_calc"] is None


def test_ad_campaign_product_columns_include_expected_export_fields() -> None:
    assert AD_CAMPAIGN_PRODUCT_COLUMNS == [
        "report_date",
        "supplier_article",
        "nm_id",
        "title",
        "brand",
        "subject",
        "advert_id",
        "campaign_name",
        "campaign_type",
        "conversion_type",
        "campaign_spend",
        "ad_views",
        "ad_clicks",
        "ad_atbs",
        "ad_orders",
        "ad_cpc_calc",
        "ad_cpm_calc",
        "ad_cost_per_cart_calc",
        "ad_cpo_calc",
        "order_sum",
        "ad_share_of_order_sum_calc",
    ]
