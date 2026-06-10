from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.db.stock_loader import (
    FACT_STOCK_SNAPSHOT_CONFLICT_COLUMNS,
    build_fact_stock_snapshot_db_row,
    prepare_fact_stock_snapshot_upsert_rows,
)


def test_fact_stock_snapshot_conflict_columns_match_natural_key():
    assert FACT_STOCK_SNAPSHOT_CONFLICT_COLUMNS == ("snapshot_date", "nm_id")


def test_build_fact_stock_snapshot_db_row_keeps_missing_fields_as_null():
    row = build_fact_stock_snapshot_db_row(
        {
            "snapshot_date": "2026-06-01",
            "nm_id": 197330807,
            "supplier_article": "BlackWOM5",
            "title": "Трусы комплект",
            "subject": "Трусы",
            "brand": "PALEY",
            "wb_stock_qty": 15,
            "mp_stock_qty": "",
            "stock_total_qty": 15,
            "stock_total_sum": "",
            "saleRate": "",
            "toClientCount": "",
            "fromClientCount": "",
            "availability": "",
            "data_status": "REAL_API",
            "source_status": "PARTIAL",
            "loaded_at": "2026-06-04T10:00:00+05:00",
        }
    )
    assert row["snapshot_date"] == date(2026, 6, 1)
    assert row["nm_id"] == 197330807
    assert row["wb_stock_qty"] == Decimal("15")
    assert row["mp_stock_qty"] is None
    assert row["stock_total_sum"] is None
    assert row["sale_rate"] is None
    assert row["availability"] is None


def test_prepare_fact_stock_snapshot_upsert_rows_deduplicates_by_snapshot_date_and_nm_id():
    rows = prepare_fact_stock_snapshot_upsert_rows(
        [
            {
                "snapshot_date": "2026-06-01",
                "nm_id": 197330807,
                "wb_stock_qty": 10,
                "mp_stock_qty": "",
                "stock_total_qty": 10,
                "stock_total_sum": "",
                "saleRate": "",
                "toClientCount": "",
                "fromClientCount": "",
                "availability": "",
                "data_status": "REAL_API",
                "source_status": "PARTIAL",
                "loaded_at": "2026-06-04T10:00:00+05:00",
            },
            {
                "snapshot_date": "2026-06-01",
                "nm_id": 197330807,
                "wb_stock_qty": 12,
                "mp_stock_qty": "",
                "stock_total_qty": 12,
                "stock_total_sum": "",
                "saleRate": "",
                "toClientCount": "",
                "fromClientCount": "",
                "availability": "",
                "data_status": "REAL_API",
                "source_status": "PARTIAL",
                "loaded_at": "2026-06-04T10:00:00+05:00",
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["wb_stock_qty"] == Decimal("12")


def test_build_fact_stock_snapshot_db_row_requires_snapshot_date():
    row = build_fact_stock_snapshot_db_row(
        {
            "snapshot_date": "2026-06-01",
            "nm_id": 37320545,
            "wb_stock_qty": "",
            "mp_stock_qty": "",
            "stock_total_qty": "",
            "stock_total_sum": "",
            "saleRate": "",
            "toClientCount": "",
            "fromClientCount": "",
            "availability": "",
            "data_status": "REAL_API",
            "source_status": "PARTIAL",
            "loaded_at": "2026-06-04T10:00:00+05:00",
        }
    )
    assert row["snapshot_date"] == date(2026, 6, 1)
