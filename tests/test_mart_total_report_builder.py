from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from src.db.mart_total_report_builder import (
    MART_TOTAL_REPORT_CONFLICT_COLUMNS,
    _build_mart_total_report_v2_row,
    aggregate_ad_cost_stats,
    aggregate_ad_campaign_stats,
    aggregate_entry_point_stats,
    aggregate_localization_stats,
    aggregate_search_stats,
    build_active_product_date_grid,
    build_calc_metrics,
    build_mart_ad_metrics,
    build_mart_total_report_row,
    prepare_mart_total_report_upsert_rows,
)


def test_mart_total_report_conflict_columns_match_grain():
    assert MART_TOTAL_REPORT_CONFLICT_COLUMNS == ("report_date", "nm_id")


def test_aggregate_ad_campaign_stats_splits_conversion_buckets():
    rows = [
        SimpleNamespace(
            date=date(2026, 6, 1),
            nm_id=197330807,
            ad_views=Decimal("100"),
            ad_clicks=Decimal("10"),
            ad_atbs=Decimal("3"),
            ad_orders=Decimal("1"),
            ad_revenue=Decimal("50"),
            ad_spend=Decimal("20"),
            avg_position=Decimal("5"),
            conversion_type="DIRECT",
        ),
        SimpleNamespace(
            date=date(2026, 6, 1),
            nm_id=197330807,
            ad_views=Decimal("50"),
            ad_clicks=Decimal("5"),
            ad_atbs=Decimal("2"),
            ad_orders=Decimal("1"),
            ad_revenue=Decimal("30"),
            ad_spend=Decimal("10"),
            avg_position=Decimal("7"),
            conversion_type="ASSOCIATED",
        ),
    ]
    aggregated = aggregate_ad_campaign_stats(rows)[(date(2026, 6, 1), 197330807)]
    assert aggregated["ad_views"] == Decimal("150")
    assert aggregated["ad_spend"] == Decimal("30")
    assert aggregated["direct_ad_atbs"] == Decimal("3")
    assert aggregated["associated_ad_atbs"] == Decimal("2")
    assert aggregated["multicard_ad_atbs"] is None


def test_aggregate_ad_campaign_stats_tracks_unknown_conversion_bucket():
    rows = [
        SimpleNamespace(
            date=date(2026, 6, 1),
            nm_id=197330807,
            ad_views=Decimal("100"),
            ad_clicks=Decimal("10"),
            ad_atbs=Decimal("4"),
            ad_orders=Decimal("2"),
            ad_revenue=Decimal("70"),
            ad_spend=Decimal("20"),
            avg_position=Decimal("4"),
            conversion_type="UNKNOWN",
        )
    ]
    aggregated = aggregate_ad_campaign_stats(rows)[(date(2026, 6, 1), 197330807)]
    assert aggregated["unknown_ad_atbs"] == Decimal("4")


def test_aggregate_ad_cost_stats_sums_multiple_campaign_rows_per_nm_day():
    rows = [
        SimpleNamespace(date=date(2026, 6, 1), nm_id=197330807, total_spend=Decimal("20")),
        SimpleNamespace(date=date(2026, 6, 1), nm_id=197330807, total_spend=Decimal("10")),
    ]
    aggregated = aggregate_ad_cost_stats(rows)[(date(2026, 6, 1), 197330807)]
    assert aggregated["ad_cost_spend"] == Decimal("30")


def test_aggregate_entry_point_stats_sums_metrics_and_builds_ctr():
    rows = [
        SimpleNamespace(
            date=date(2026, 6, 7),
            nm_id=197330807,
            impressions=Decimal("100"),
            card_clicks=Decimal("10"),
            cart_count=Decimal("4"),
            order_count=Decimal("2"),
        ),
        SimpleNamespace(
            date=date(2026, 6, 7),
            nm_id=197330807,
            impressions=Decimal("50"),
            card_clicks=Decimal("5"),
            cart_count=Decimal("1"),
            order_count=Decimal("1"),
        ),
    ]

    aggregated = aggregate_entry_point_stats(rows)[(date(2026, 6, 7), 197330807)]

    assert aggregated["entry_impressions_total"] == Decimal("150")
    assert aggregated["entry_card_clicks_total"] == Decimal("15")
    assert aggregated["entry_cart_total"] == Decimal("5")
    assert aggregated["entry_orders_total"] == Decimal("3")
    assert aggregated["entry_ctr_calc"] == Decimal("10")
    assert aggregated["entry_cart_conversion_calc"] == Decimal("33.33333333333333333333333333")
    assert aggregated["entry_order_conversion_calc"] == Decimal("60")


def test_aggregate_search_and_localization_stats_do_not_multiply_rows():
    search_rows = [
        SimpleNamespace(date=date(2026, 6, 1), nm_id=197330807, avg_position=Decimal("7"), visibility=Decimal("10"), search_clicks=Decimal("2"), search_cart=None, search_orders=None),
        SimpleNamespace(date=date(2026, 6, 1), nm_id=197330807, avg_position=Decimal("9"), visibility=Decimal("20"), search_clicks=Decimal("3"), search_cart=Decimal("1"), search_orders=None),
    ]
    localization_rows = [
        SimpleNamespace(date=date(2026, 6, 1), nm_id=197330807, region="Москва", orders_total_qty=Decimal("2"), sale_item_qty=Decimal("2"), sale_amount=Decimal("250")),
        SimpleNamespace(date=date(2026, 6, 1), nm_id=197330807, region="СПб", orders_total_qty=Decimal("1"), sale_item_qty=Decimal("1"), sale_amount=Decimal("100")),
    ]
    search = aggregate_search_stats(search_rows)[(date(2026, 6, 1), 197330807)]
    localization = aggregate_localization_stats(localization_rows)[(date(2026, 6, 1), 197330807)]
    assert search["search_queries_count"] == 2
    assert search["search_clicks"] == Decimal("5")
    assert localization["localization_regions_count"] == 2
    assert localization["localization_sale_amount"] == Decimal("350")


def test_aggregate_localization_stats_uses_period_end_as_report_date_for_period_level_rows():
    localization_rows = [
        SimpleNamespace(
            period_end=date(2026, 6, 2),
            date=date(2026, 6, 1),
            nm_id=197330807,
            region="Москва",
            orders_total_qty=Decimal("2"),
            sale_item_qty=Decimal("2"),
            sale_amount=Decimal("250"),
        ),
        SimpleNamespace(
            period_end=date(2026, 6, 2),
            date=date(2026, 6, 1),
            nm_id=197330807,
            region="СПб",
            orders_total_qty=Decimal("1"),
            sale_item_qty=Decimal("1"),
            sale_amount=Decimal("100"),
        ),
    ]

    aggregated = aggregate_localization_stats(localization_rows)

    assert (date(2026, 6, 2), 197330807) in aggregated
    assert (date(2026, 6, 1), 197330807) not in aggregated
    assert aggregated[(date(2026, 6, 2), 197330807)]["localization_regions_count"] == 2


def test_build_mart_total_report_row_keeps_manual_blocks_null_and_flags_sources():
    loaded_at = datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc)
    row = build_mart_total_report_row(
        funnel_row=SimpleNamespace(
            date=date(2026, 6, 1),
            nm_id=197330807,
            impressions=Decimal("100"),
            card_clicks=None,
            ctr=None,
            cart_count=Decimal("4"),
            order_count=Decimal("2"),
            order_sum=Decimal("500"),
            buyout_count=Decimal("1"),
            buyout_sum=Decimal("250"),
            buyout_percent=Decimal("50"),
            add_to_cart_conversion=Decimal("4"),
            cart_to_order_conversion=Decimal("50"),
            wishlist_count=Decimal("1"),
            avg_delivery_time=None,
            local_orders_percent=None,
            loaded_at=loaded_at,
        ),
        stock_row=None,
        ad_cost_stats=None,
        ad_campaign_stats={},
        search_stats={},
        localization_stats={},
    )
    assert row["report_date"] == date(2026, 6, 1)
    assert row["nm_id"] == 197330807
    assert row["card_clicks"] is None
    assert row["ctr"] is None
    assert row["vbro_organic_sales_qty"] is None
    assert row["vbro_operating_profit"] is None
    assert row["has_funnel"] is True
    assert row["has_stock"] is False
    assert row["has_search"] is False


def test_build_mart_total_report_row_sets_has_funnel_false_for_empty_funnel_payload():
    row = build_mart_total_report_row(
        funnel_row=SimpleNamespace(
            date=date(2026, 6, 1),
            nm_id=197330807,
            impressions=None,
            card_clicks=None,
            ctr=None,
            cart_count=None,
            order_count=None,
            order_sum=None,
            buyout_count=None,
            buyout_sum=None,
            buyout_percent=None,
            add_to_cart_conversion=None,
            cart_to_order_conversion=None,
            wishlist_count=None,
            avg_delivery_time=None,
            local_orders_percent=None,
            loaded_at=datetime(2026, 6, 5, 10, 0, tzinfo=timezone.utc),
        ),
        stock_row=None,
        ad_cost_stats=None,
        ad_campaign_stats={},
        search_stats={},
        localization_stats={},
    )

    assert row["has_funnel"] is False


def test_build_mart_total_report_v2_row_marks_detail_history_zero_activity_explicitly():
    row = _build_mart_total_report_v2_row(
        base_row={"report_date": date(2026, 6, 7), "nm_id": 197330807, "supplier_article": "BlackWOM5", "title": "Трусы", "subject": "Трусы", "brand": "PALEY"},
        stock_row=None,
        funnel_row=SimpleNamespace(
            impressions=None,
            card_clicks=Decimal("0"),
            ctr=None,
            cart_count=Decimal("0"),
            order_count=Decimal("0"),
            order_sum=Decimal("0"),
            buyout_count=Decimal("0"),
            buyout_sum=Decimal("0"),
            buyout_percent=None,
            add_to_cart_conversion=Decimal("0"),
            cart_to_order_conversion=Decimal("0"),
            wishlist_count=None,
            avg_delivery_time=None,
            local_orders_percent=None,
            source_status="DETAIL_HISTORY_REPORT",
            loaded_at=datetime(2026, 6, 12, 15, 21, tzinfo=timezone.utc),
        ),
        entry_point_stats=None,
        ad_cost_stats=None,
        ad_campaign_stats=None,
        search_stats=None,
        localization_stats=None,
    )

    assert row["has_funnel"] is True
    assert row["export_context_json"]["funnel_resolution_status"] == "NO_ACTIVITY"
    assert row["export_context_json"]["funnel_selected_source"] == "DETAIL_HISTORY_REPORT"


def test_build_mart_total_report_v2_row_ignores_hollow_legacy_funnel_rows():
    row = _build_mart_total_report_v2_row(
        base_row={"report_date": date(2026, 6, 7), "nm_id": 197330807, "supplier_article": "BlackWOM5", "title": "Трусы", "subject": "Трусы", "brand": "PALEY"},
        stock_row=None,
        funnel_row=SimpleNamespace(
            impressions=None,
            card_clicks=None,
            ctr=None,
            cart_count=None,
            order_count=None,
            order_sum=None,
            buyout_count=None,
            buyout_sum=None,
            buyout_percent=None,
            add_to_cart_conversion=None,
            cart_to_order_conversion=None,
            wishlist_count=None,
            avg_delivery_time=None,
            local_orders_percent=None,
            source_status="PARTIAL",
            loaded_at=datetime(2026, 6, 9, 16, 52, tzinfo=timezone.utc),
        ),
        entry_point_stats=None,
        ad_cost_stats=None,
        ad_campaign_stats=None,
        search_stats=None,
        localization_stats=None,
    )

    assert row["has_funnel"] is False
    assert row["export_context_json"]["funnel_resolution_status"] == "HOLLOW_LEGACY_IGNORED"
    assert row["export_context_json"]["funnel_selected_source"] == "PARTIAL"


def test_build_mart_total_report_v2_row_marks_meaningful_legacy_as_fallback():
    row = _build_mart_total_report_v2_row(
        base_row={"report_date": date(2026, 6, 7), "nm_id": 197330807, "supplier_article": "BlackWOM5", "title": "Трусы", "subject": "Трусы", "brand": "PALEY"},
        stock_row=None,
        funnel_row=SimpleNamespace(
            impressions=None,
            card_clicks=Decimal("5"),
            ctr=None,
            cart_count=Decimal("1"),
            order_count=Decimal("1"),
            order_sum=Decimal("100"),
            buyout_count=None,
            buyout_sum=None,
            buyout_percent=None,
            add_to_cart_conversion=Decimal("20"),
            cart_to_order_conversion=Decimal("100"),
            wishlist_count=None,
            avg_delivery_time=None,
            local_orders_percent=None,
            source_status="PARTIAL",
            loaded_at=datetime(2026, 6, 9, 16, 52, tzinfo=timezone.utc),
        ),
        entry_point_stats=None,
        ad_cost_stats=None,
        ad_campaign_stats=None,
        search_stats=None,
        localization_stats=None,
    )

    assert row["has_funnel"] is True
    assert row["export_context_json"]["funnel_resolution_status"] == "LEGACY_FALLBACK"
    assert row["export_context_json"]["funnel_selected_source"] == "PARTIAL"


def test_prepare_mart_total_report_upsert_rows_deduplicates():
    rows = prepare_mart_total_report_upsert_rows(
        [
            {"report_date": date(2026, 6, 1), "nm_id": 197330807, "impressions": Decimal("100")},
            {"report_date": date(2026, 6, 1), "nm_id": 197330807, "impressions": Decimal("120")},
        ]
    )
    assert len(rows) == 1
    assert rows[0]["impressions"] == Decimal("120")


def test_build_active_product_date_grid_uses_all_active_products_for_each_date():
    products = [
        SimpleNamespace(
            nm_id=197330807,
            supplier_article="BlackWOM5",
            title="Трусы",
            subject="Трусы",
            brand="PALEY",
            active=True,
        ),
        SimpleNamespace(
            nm_id=37320545,
            supplier_article="ABC",
            title="Носки",
            subject="Носки",
            brand="PALEY",
            active=True,
        ),
    ]

    rows = build_active_product_date_grid(
        start=date(2026, 5, 31),
        end=date(2026, 6, 1),
        products=products,
    )

    assert len(rows) == 4
    assert {(row["report_date"], row["nm_id"]) for row in rows} == {
        (date(2026, 5, 31), 197330807),
        (date(2026, 6, 1), 197330807),
        (date(2026, 5, 31), 37320545),
        (date(2026, 6, 1), 37320545),
    }
    assert rows[0]["supplier_article"] in {"BlackWOM5", "ABC"}


def test_build_calc_metrics_keeps_nulls_and_avoids_division_by_zero():
    calculated = build_calc_metrics(
        impressions=Decimal("100"),
        card_clicks=None,
        cart_count=Decimal("4"),
        order_count=Decimal("2"),
        order_sum=Decimal("500"),
        ad_spend=Decimal("20"),
        ad_views=Decimal("1000"),
        ad_clicks=Decimal("10"),
        ad_orders=Decimal("2"),
    )

    assert calculated["ctr_calc"] is None
    assert calculated["add_to_cart_conversion_calc"] is None
    assert calculated["cart_to_order_conversion_calc"] == Decimal("50")
    assert calculated["ad_cpc_calc"] == Decimal("2")
    assert calculated["ad_cpm_calc"] == Decimal("20")
    assert calculated["ad_cpo_calc"] == Decimal("10")
    assert calculated["ad_share_of_revenue_calc"] == Decimal("4")


def test_build_mart_ad_metrics_uses_ad_cost_for_spend_totals_and_campaign_for_performance():
    metrics = build_mart_ad_metrics(
        ad_cost_stats={"ad_cost_spend": Decimal("30")},
        ad_campaign_stats={
            "ad_spend": Decimal("31"),
            "ad_views": Decimal("150"),
            "ad_clicks": Decimal("15"),
            "ad_atbs": Decimal("5"),
            "ad_orders": Decimal("2"),
            "direct_ad_atbs": Decimal("3"),
            "associated_ad_atbs": Decimal("1"),
            "multicard_ad_atbs": None,
            "unknown_ad_atbs": Decimal("1"),
        },
        order_sum=Decimal("500"),
        cart_count=Decimal("5"),
    )
    assert metrics["ad_spend_total"] == Decimal("30")
    assert metrics["ad_cost_writeoff_total"] == Decimal("30")
    assert metrics["ad_campaign_spend_total"] == Decimal("31")
    assert metrics["ad_views_total"] == Decimal("150")
    assert metrics["ad_clicks_total"] == Decimal("15")
    assert metrics["ad_atbs_total"] == Decimal("5")
    assert metrics["ad_orders_total"] == Decimal("2")
    assert metrics["ad_cpc_calc"] == Decimal("2.066666666666666666666666667")
    assert metrics["ad_cpm_calc"] == Decimal("206.6666666666666666666666667")
    assert metrics["ad_cost_per_cart_calc"] == Decimal("6.2")
    assert metrics["ad_cpo_calc"] == Decimal("15.5")
    assert metrics["ad_share_of_revenue_calc"] == Decimal("6.2")
    assert metrics["associated_atbs_percent_calc"] == Decimal("20")
    assert metrics["organic_cart_count"] == Decimal("0")
    assert metrics["organic_cart_share_calc"] == Decimal("0")
    assert metrics["ad_cost_per_all_carts_calc"] == Decimal("5.166666666666666666666666667")
    assert metrics["organic_cart_share_status"] == "OK"


def test_build_mart_ad_metrics_keeps_formula_fields_null_when_sources_missing():
    metrics = build_mart_ad_metrics(
        ad_cost_stats={"ad_cost_spend": Decimal("30")},
        ad_campaign_stats={
            "ad_spend": Decimal("31"),
            "ad_views": Decimal("150"),
            "ad_clicks": Decimal("15"),
            "ad_atbs": None,
            "ad_orders": Decimal("2"),
            "direct_ad_atbs": Decimal("3"),
            "associated_ad_atbs": None,
            "multicard_ad_atbs": None,
            "unknown_ad_atbs": Decimal("1"),
        },
        order_sum=Decimal("500"),
        cart_count=None,
    )

    assert metrics["organic_cart_count"] is None
    assert metrics["organic_cart_share_calc"] is None
    assert metrics["ad_cost_per_all_carts_calc"] is None
    assert metrics["organic_cart_share_status"] == "MISSING_SOURCE"
