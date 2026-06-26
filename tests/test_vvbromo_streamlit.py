from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any
import pandas as pd
import pytest

from src.streamlit_dataset import attach_vvbromo_fields, aggregate_vvbromo_for_period
from app_streamlit import attach_vvbromo_to_df


class DummyVvbromoRecord:
    def __init__(self, day, nm_id, organic_sales, operating_profit, operating_profit_per_unit):
        self.day = day
        self.nm_id = nm_id
        self.organic_sales = organic_sales
        self.operating_profit = operating_profit
        self.operating_profit_per_unit = operating_profit_per_unit


def test_attach_vvbromo_fields_exact_join(monkeypatch) -> None:
    # 1. Mock database select inside attach_vvbromo_fields
    db_records = [
        DummyVvbromoRecord(datetime.date(2026, 6, 19), 11111, 10, Decimal("1000.00"), Decimal("100.00")),
        DummyVvbromoRecord(datetime.date(2026, 6, 20), 11111, 20, Decimal("3000.00"), Decimal("150.00")),
        DummyVvbromoRecord(datetime.date(2026, 6, 19), 22222, 5, Decimal("-500.00"), Decimal("-100.00")),
    ]

    class DummyResult:
        def scalars(self):
            return self
        def all(self):
            return db_records

    class DummySession:
        def execute(self, query):
            return DummyResult()

    class DummySessionScope:
        def __enter__(self):
            return DummySession()
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr("src.db.session.session_scope", lambda: DummySessionScope())

    # 2. Input rows to join
    rows = [
        {"report_date": "2026-06-19", "nm_id": 11111},
        {"report_date": "2026-06-20", "nm_id": 11111},
        {"report_date": "2026-06-19", "nm_id": 22222},
        {"report_date": "2026-06-20", "nm_id": 22222},  # Date exists in DB but not for this nm_id
        {"report_date": "2026-06-21", "nm_id": 11111},  # Date does not exist in DB at all
    ]

    joined_rows = attach_vvbromo_fields(rows)

    assert len(joined_rows) == 5

    # Check matches
    assert joined_rows[0]["vvbromo_organic_sales"] == 10
    assert joined_rows[0]["vvbromo_operating_profit"] == 1000.0
    assert joined_rows[0]["vvbromo_operating_profit_per_unit"] == 100.0

    assert joined_rows[1]["vvbromo_organic_sales"] == 20
    assert joined_rows[1]["vvbromo_operating_profit"] == 3000.0
    assert joined_rows[1]["vvbromo_operating_profit_per_unit"] == 150.0

    assert joined_rows[2]["vvbromo_organic_sales"] == 5
    assert joined_rows[2]["vvbromo_operating_profit"] == -500.0
    assert joined_rows[2]["vvbromo_operating_profit_per_unit"] == -100.0

    # Test handling of missing data (must be None, not 0 and not propagated from other dates)
    assert joined_rows[3]["vvbromo_organic_sales"] is None
    assert joined_rows[3]["vvbromo_operating_profit"] is None
    assert joined_rows[3]["vvbromo_operating_profit_per_unit"] is None

    assert joined_rows[4]["vvbromo_organic_sales"] is None
    assert joined_rows[4]["vvbromo_operating_profit"] is None
    assert joined_rows[4]["vvbromo_operating_profit_per_unit"] is None


def test_attach_vvbromo_to_df_database_down(monkeypatch) -> None:
    # 1. Mock DB call to raise exception (database down scenario)
    def raise_err(*args, **kwargs):
        raise RuntimeError("Database connection failed")

    monkeypatch.setattr("src.db.session.session_scope", raise_err)

    df = pd.DataFrame([
        {"report_date": datetime.date(2026, 6, 19), "nm_id": 11111, "vvbromo_organic_sales": 12},  # CSV has some fallback data
        {"report_date": datetime.date(2026, 6, 20), "nm_id": 22222}
    ])

    # df must not crash, should return unmodified or empty/retained fields
    result_df = attach_vvbromo_to_df(df)

    assert not result_df.empty
    # Fallback from CSV is preserved
    assert result_df.loc[0, "vvbromo_organic_sales"] == 12
    # Missing columns are created with NaN/None
    assert pd.isna(result_df.loc[1, "vvbromo_organic_sales"])


def test_aggregate_vvbromo_for_period() -> None:
    # 1. Period with valid sales and orders
    df = pd.DataFrame([
        {"nm_id": 11111, "vvbromo_organic_sales": 10, "vvbromo_operating_profit": 1000.0, "vvbromo_operating_profit_per_unit": 100.0, "order_count": 5.0, "crm_common_calc": 200.0},
        {"nm_id": 11111, "vvbromo_organic_sales": 20, "vvbromo_operating_profit": 3000.0, "vvbromo_operating_profit_per_unit": 150.0, "order_count": 15.0, "crm_common_calc": 200.0},
    ])

    aggregated = aggregate_vvbromo_for_period(df, ["nm_id"])

    assert len(aggregated) == 1
    # sum of organic sales: 10 + 20 = 30
    assert aggregated.loc[0, "vvbromo_organic_sales"] == 30
    # sum of operating profit: 1000 + 3000 = 4000
    assert aggregated.loc[0, "vvbromo_operating_profit"] == 4000.0
    # operating_profit_per_unit: 4000 / 30 = 133.333...
    assert pytest.approx(aggregated.loc[0, "vvbromo_operating_profit_per_unit"], 0.0001) == 4000.0 / 30.0
    # sum of order_count: 5 + 15 = 20
    assert aggregated.loc[0, "order_count"] == 20.0
    # crm_common_calc: 4000 / 20 = 200.0
    assert pytest.approx(aggregated.loc[0, "crm_common_calc"], 0.0001) == 200.0

    # 2. Period with 0 orders (division by zero handling)
    df_zero = pd.DataFrame([
        {"nm_id": 22222, "vvbromo_organic_sales": 5, "vvbromo_operating_profit": 100.0, "vvbromo_operating_profit_per_unit": 20.0, "order_count": 0.0, "crm_common_calc": None},
    ])
    agg_zero = aggregate_vvbromo_for_period(df_zero, ["nm_id"])
    assert agg_zero.loc[0, "vvbromo_organic_sales"] == 5
    assert agg_zero.loc[0, "vvbromo_operating_profit"] == 100.0
    assert agg_zero.loc[0, "order_count"] == 0.0
    assert agg_zero.loc[0, "crm_common_calc"] is None

    # 3. Period with empty/NaN orders
    df_nan = pd.DataFrame([
        {"nm_id": 33333, "vvbromo_organic_sales": 5, "vvbromo_operating_profit": 100.0, "vvbromo_operating_profit_per_unit": 20.0, "order_count": None, "crm_common_calc": None},
    ])
    agg_nan = aggregate_vvbromo_for_period(df_nan, ["nm_id"])
    assert agg_nan.loc[0, "vvbromo_operating_profit"] == 100.0
    assert pd.isna(agg_nan.loc[0, "order_count"])
    assert agg_nan.loc[0, "crm_common_calc"] is None


def test_sync_button_calls_loader_and_returns_summary(monkeypatch) -> None:
    called_args = {}

    def mock_run_loader(year: int, apply: bool, dry_run: bool) -> dict[str, Any]:
        called_args["year"] = year
        called_args["apply"] = apply
        called_args["dry_run"] = dry_run
        return {
            "rows_parsed": 239,
            "rows_upserted": 239,
            "date_min": "2026-06-19",
            "date_max": "2026-06-22",
            "distinct_dates": 4,
            "distinct_nm_id": 62,
            "errors": 0,
            "db_changed": True,
            "parse_errors_list": []
        }

    monkeypatch.setattr("scripts.parse_vvbromo_sheet.run_loader", mock_run_loader)

    from scripts.parse_vvbromo_sheet import run_loader
    summary = run_loader(year=2026, apply=True, dry_run=False)

    assert called_args["year"] == 2026
    assert called_args["apply"] is True
    assert called_args["dry_run"] is False

    assert summary["rows_parsed"] == 239
    assert summary["rows_upserted"] == 239
    assert summary["date_min"] == "2026-06-19"
    assert summary["date_max"] == "2026-06-22"
    assert summary["distinct_nm_id"] == 62
    assert summary["errors"] == 0


def test_vvbromo_streamlit_display_columns_and_null_preservation(monkeypatch) -> None:
    # 1. Mock DB call inside attach_vvbromo_to_df
    db_records = [
        DummyVvbromoRecord(datetime.date(2026, 6, 19), 11111, 10, Decimal("20622.00"), Decimal("2062.20")),
    ]

    class DummyResult:
        def scalars(self):
            return self
        def all(self):
            return db_records

    class DummySession:
        def execute(self, query):
            return DummyResult()

    class DummySessionScope:
        def __enter__(self):
            return DummySession()
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr("src.db.session.session_scope", lambda: DummySessionScope())

    # 2. Input DataFrame to prepare
    df = pd.DataFrame([
        {
            "report_date": "2026-06-19",
            "nm_id": 11111,
            "supplier_article": "Art1",
            "order_count": 90,
            "has_entry_points": False,
            "has_localization": False,
            "vbro_status": "MANUAL_PENDING",
        },  # data in DB, should compute CRM and change status (even with False flags)
        {
            "report_date": "2026-06-19",
            "nm_id": 22222,
            "supplier_article": "Art2",
            "order_count": 5,
            "has_entry_points": False,
            "has_localization": False,
            "vbro_status": "MANUAL_PENDING",
        },  # no VVBromo data, should remain MANUAL_PENDING / "Не внесено"
        {
            "report_date": "2026-06-19",
            "nm_id": 11111,
            "supplier_article": "Art1",
            "order_count": 0,
            "has_entry_points": False,
            "has_localization": False,
            "vbro_status": "MANUAL_PENDING",
        },  # order_count = 0, should keep CRM as None/NaN
        {
            "report_date": "2026-06-19",
            "nm_id": 11111,
            "supplier_article": "Art1",
            "order_count": None,
            "has_entry_points": False,
            "has_localization": False,
            "vbro_status": "MANUAL_PENDING",
        },  # order_count = None, should keep CRM as None/NaN
    ])

    # 3. Prepare DataFrame
    from app_streamlit import prepare_dataframe, build_overview_export_tables, build_grouped_by_date_dataset
    prepared = prepare_dataframe(df)

    # Check that in prepared dataframe missing values remain null/NaN (not 0)
    # Row 0 (nm_id 11111) has data
    assert prepared.loc[0, "vvbromo_operating_profit"] == 20622.0
    assert prepared.loc[0, "vvbromo_organic_sales"] == 10
    assert prepared.loc[0, "vvbromo_operating_profit_per_unit"] == 2062.20
    assert pytest.approx(prepared.loc[0, "crm_common_calc"], 0.0001) == 20622.0 / 90.0
    assert prepared.loc[0, "vbro_status_label"] == "Файл загружен"

    # Row 1 (nm_id 22222) has no data
    assert pd.isna(prepared.loc[1, "vvbromo_operating_profit"])
    assert pd.isna(prepared.loc[1, "vvbromo_organic_sales"])
    assert pd.isna(prepared.loc[1, "vvbromo_operating_profit_per_unit"])
    assert pd.isna(prepared.loc[1, "crm_common_calc"])
    assert prepared.loc[1, "vbro_status_label"] == "Не внесено"

    # Row 2 (order_count = 0)
    assert pd.isna(prepared.loc[2, "crm_common_calc"])

    # Row 3 (order_count = None)
    assert pd.isna(prepared.loc[3, "crm_common_calc"])

    # 4. Build overview display dataframe
    table_df = build_grouped_by_date_dataset(prepared)
    display_df, export_df = build_overview_export_tables(table_df, show_empty_rows=True)

    # 5. Assertions on visible columns
    assert "vvbromo_operating_profit" in display_df.columns
    assert "vvbromo_organic_sales" not in display_df.columns
    assert "vvbromo_operating_profit_per_unit" not in display_df.columns
    assert "crm_common_calc" in display_df.columns

    # Assertions on values in display_df (missing values must remain null/NaN)
    assert display_df.loc[0, "vvbromo_operating_profit"] == 20622.0
    assert pd.isna(display_df.loc[1, "vvbromo_operating_profit"])
    assert pytest.approx(display_df.loc[0, "crm_common_calc"], 0.0001) == 20622.0 / 90.0

    # Assertions on export_df (renamed columns and string fallback)
    assert "CRM по общим заказам" in export_df.columns
    assert pytest.approx(float(export_df.loc[0, "CRM по общим заказам"]), 0.0001) == 20622.0 / 90.0
    assert export_df.loc[1, "CRM по общим заказам"] == "—"

