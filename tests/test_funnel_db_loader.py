from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.dialects import postgresql

from src.db.funnel_loader import (
    FACT_FUNNEL_DAY_CONFLICT_COLUMNS,
    _duration_text_to_hours,
    build_fact_funnel_day_db_row,
    build_fact_funnel_day_upsert_statement,
    prepare_fact_funnel_day_upsert_rows,
)


def test_fact_funnel_day_conflict_columns_match_natural_key():
    assert FACT_FUNNEL_DAY_CONFLICT_COLUMNS == ("date", "nm_id")


def test_build_fact_funnel_day_db_row_keeps_missing_clicks_and_ctr_as_null():
    row = build_fact_funnel_day_db_row(
        {
            "date": "2026-06-01",
            "nm_id": 197330807,
            "impressions": 5420.0,
            "card_clicks": "",
            "ctr": "",
            "cartCount": 100,
            "orderCount": 50,
            "avg_delivery_time": "",
            "avg_delivery_time_prev": "",
            "data_status": "REAL_API",
            "source_status": "PARTIAL",
            "loaded_at": "2026-06-04T10:00:00+05:00",
        }
    )
    assert row["date"] == date(2026, 6, 1)
    assert row["nm_id"] == 197330807
    assert row["impressions"] == Decimal("5420.0")
    assert row["card_clicks"] is None
    assert row["ctr"] is None
    assert row["cart_count"] == Decimal("100")
    assert row["order_count"] == Decimal("50")


def test_build_fact_funnel_day_db_row_does_not_restore_open_count_as_card_clicks():
    row = build_fact_funnel_day_db_row(
        {
            "date": "2026-06-01",
            "nm_id": 197330807,
            "impressions": 100,
            "card_clicks": "",
            "ctr": "",
            "cartCount": "",
            "orderCount": "",
            "avg_delivery_time": "",
            "avg_delivery_time_prev": "",
            "data_status": "REAL_API",
            "source_status": "PARTIAL",
            "loaded_at": "2026-06-04T10:00:00+05:00",
        }
    )
    assert row["impressions"] == Decimal("100")
    assert row["card_clicks"] is None
    assert row["ctr"] is None


def test_build_fact_funnel_day_db_row_keeps_open_count_based_card_clicks_without_impressions():
    row = build_fact_funnel_day_db_row(
        {
            "date": "2026-06-01",
            "nm_id": 197330807,
            "impressions": "",
            "card_clicks": 100,
            "ctr": "",
            "cartCount": 10,
            "orderCount": 5,
            "addToCartConversion": 10,
            "cartToOrderConversion": 50,
            "avg_delivery_time": "",
            "avg_delivery_time_prev": "",
            "data_status": "REAL_API",
            "source_status": "PARTIAL",
            "loaded_at": "2026-06-04T10:00:00+05:00",
        }
    )
    assert row["impressions"] is None
    assert row["card_clicks"] == Decimal("100")
    assert row["ctr"] is None
    assert row["add_to_cart_conversion"] == Decimal("10")
    assert row["cart_to_order_conversion"] == Decimal("50")


def test_prepare_fact_funnel_day_upsert_rows_deduplicates_by_date_and_nm_id():
    rows = prepare_fact_funnel_day_upsert_rows(
        [
            {
                "date": "2026-06-01",
                "nm_id": 197330807,
                "impressions": 10,
                "card_clicks": "",
                "ctr": "",
                "cartCount": "",
                "orderCount": "",
                "avg_delivery_time": "",
                "avg_delivery_time_prev": "",
                "data_status": "REAL_API",
                "source_status": "PARTIAL",
                "loaded_at": "2026-06-04T10:00:00+05:00",
            },
            {
                "date": "2026-06-01",
                "nm_id": 197330807,
                "impressions": 20,
                "card_clicks": "",
                "ctr": "",
                "cartCount": "",
                "orderCount": "",
                "avg_delivery_time": "",
                "avg_delivery_time_prev": "",
                "data_status": "REAL_API",
                "source_status": "PARTIAL",
                "loaded_at": "2026-06-04T10:00:00+05:00",
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["impressions"] == Decimal("20")


def test_duration_text_to_hours_parses_sheet_friendly_duration():
    assert _duration_text_to_hours("1 д 2 ч 30 мин") == Decimal("26.5")
    assert _duration_text_to_hours("") is None

def test_prepare_fact_funnel_day_upsert_rows_keeps_non_null_impressions_from_earlier_duplicate():
    rows = prepare_fact_funnel_day_upsert_rows(
        [
            {
                "date": "2026-06-01",
                "nm_id": 197330807,
                "impressions": 120,
                "card_clicks": 12,
                "ctr": 10,
                "cartCount": "",
                "orderCount": "",
                "avg_delivery_time": "",
                "avg_delivery_time_prev": "",
                "data_status": "REAL_API",
                "source_status": "OK",
                "loaded_at": "2026-06-04T10:00:00+05:00",
            },
            {
                "date": "2026-06-01",
                "nm_id": 197330807,
                "impressions": "",
                "card_clicks": "",
                "ctr": "",
                "cartCount": 5,
                "orderCount": 2,
                "avg_delivery_time": "",
                "avg_delivery_time_prev": "",
                "data_status": "REAL_API",
                "source_status": "PARTIAL",
                "loaded_at": "2026-06-04T11:00:00+05:00",
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["impressions"] == Decimal("120")
    assert rows[0]["card_clicks"] == Decimal("12")
    assert rows[0]["cart_count"] == Decimal("5")
    assert rows[0]["order_count"] == Decimal("2")


def test_fact_funnel_day_upsert_statement_preserves_existing_non_null_metrics_on_null_update():
    rows = prepare_fact_funnel_day_upsert_rows(
        [
            {
                "date": "2026-06-01",
                "nm_id": 197330807,
                "impressions": 120,
                "card_clicks": 12,
                "ctr": 10,
                "cartCount": 5,
                "orderCount": 2,
                "avg_delivery_time": "",
                "avg_delivery_time_prev": "",
                "data_status": "REAL_API",
                "source_status": "OK",
                "loaded_at": "2026-06-04T10:00:00+05:00",
            }
        ]
    )
    stmt = build_fact_funnel_day_upsert_statement(rows)
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})).lower()

    assert "coalesce(excluded.impressions, fact_funnel_day.impressions)" in sql
    assert "coalesce(excluded.card_clicks, fact_funnel_day.card_clicks)" in sql
    assert "coalesce(excluded.ctr, fact_funnel_day.ctr)" in sql

