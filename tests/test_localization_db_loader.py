from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.db.localization_loader import (
    FACT_LOCALIZATION_REGION_DAY_CONFLICT_COLUMNS,
    build_fact_localization_region_day_db_row,
    prepare_fact_localization_region_day_upsert_rows,
)


def test_fact_localization_region_day_conflict_columns_match_period_level_key():
    assert FACT_LOCALIZATION_REGION_DAY_CONFLICT_COLUMNS == ("period_start", "period_end", "nm_id", "region")


def test_build_fact_localization_region_day_db_row_uses_period_end_as_report_date_and_keeps_nulls():
    row = build_fact_localization_region_day_db_row(
        {
            "date": "2026-06-01",
            "nm_id": 197330807,
            "supplier_article": "BlackWOM5",
            "title": "Product",
            "subject": "Трусы",
            "brand": "PALEY",
            "country": "Россия",
            "region": "Москва",
            "city": "Москва",
            "orders_total_qty": 2,
            "sale_item_qty": 2,
            "sale_amount": 250,
            "wb_stock_qty": "",
            "mp_stock_qty": "",
            "delivery_time": "",
            "loaded_at": "2026-06-05T10:00:00+05:00",
        },
        period_start=date(2026, 5, 31),
        period_end=date(2026, 6, 1),
    )
    assert row["period_start"] == date(2026, 5, 31)
    assert row["period_end"] == date(2026, 6, 1)
    assert row["date"] == date(2026, 6, 1)
    assert row["orders_total_qty"] == Decimal("2")
    assert row["sale_amount"] == Decimal("250")
    assert row["wb_stock_qty"] is None
    assert row["mp_stock_qty"] is None
    assert row["delivery_time"] is None
    assert row["source_status"] == "PARTIAL"


def test_prepare_fact_localization_region_day_upsert_rows_deduplicates():
    rows = prepare_fact_localization_region_day_upsert_rows(
        [
            {
                "date": "2026-06-01",
                "nm_id": 197330807,
                "region": "Москва",
                "orders_total_qty": 2,
                "loaded_at": "2026-06-05T10:00:00+05:00",
            },
            {
                "date": "2026-06-01",
                "nm_id": 197330807,
                "region": "Москва",
                "orders_total_qty": 3,
                "loaded_at": "2026-06-05T10:00:00+05:00",
            },
        ],
        period_start=date(2026, 5, 31),
        period_end=date(2026, 6, 1),
    )
    assert len(rows) == 1
    assert rows[0]["orders_total_qty"] == Decimal("3")


def test_prepare_fact_localization_region_day_upsert_rows_keeps_local_nonlocal_and_stock_null():
    rows = prepare_fact_localization_region_day_upsert_rows(
        [
            {
                "date": "2026-06-01",
                "nm_id": 197330807,
                "region": "Москва",
                "orders_local_qty": "",
                "orders_nonlocal_qty": "",
                "orders_nonlocal_percent": "",
                "wb_stock_orders_local_qty": "",
                "wb_stock_orders_nonlocal_qty": "",
                "wb_stock_orders_nonlocal_percent": "",
                "mp_orders_local_qty": "",
                "mp_orders_nonlocal_qty": "",
                "mp_orders_nonlocal_percent": "",
                "wb_stock_qty": "",
                "mp_stock_qty": "",
                "delivery_time": "",
                "loaded_at": "2026-06-05T10:00:00+05:00",
            }
        ],
        period_start=date(2026, 5, 31),
        period_end=date(2026, 6, 1),
    )
    assert len(rows) == 1
    assert rows[0]["orders_local_qty"] is None
    assert rows[0]["orders_nonlocal_qty"] is None
    assert rows[0]["wb_stock_qty"] is None
    assert rows[0]["mp_stock_qty"] is None
    assert rows[0]["delivery_time"] is None
