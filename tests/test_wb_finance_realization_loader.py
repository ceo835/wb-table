from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd

from src.db.wb_finance_realization_loader import (
    FinanceRealizationPageResult,
    build_finance_realization_article_daily_aggregate,
    build_fact_finance_realization_line_db_row,
    build_finance_realization_office_daily_aggregate,
    build_last_7_vs_previous_7,
    fetch_report_detail_by_period_pages,
    prepare_fact_finance_realization_line_upsert_rows,
)


def _sample_row(**overrides):
    row = {
        "rrd_id": 101,
        "realizationreport_id": 9001,
        "rr_dt": "2026-07-14T10:00:00+00:00",
        "date_from": "2026-07-14",
        "date_to": "2026-07-14",
        "nm_id": 111,
        "sa_name": "SKU-111",
        "barcode": "460000000001",
        "srid": "SRID-1",
        "doc_type_name": "Продажа",
        "supplier_oper_name": "Логистика",
        "quantity": "2",
        "delivery_amount": "2",
        "return_amount": "0",
        "delivery_rub": "120.50",
        "storage_fee": "15.20",
        "acceptance": "5.00",
        "rebill_logistic_cost": "9.50",
        "deduction": "0",
        "penalty": "0",
        "additional_payment": "0",
        "ppvz_for_pay": "400.00",
        "office_name": "Коледино",
        "ppvz_office_name": "ПВЗ 1",
        "ppvz_office_id": 44,
        "fix_tariff_date_from": "2026-07-01T00:00:00+00:00",
        "fix_tariff_date_to": "2026-07-31T00:00:00+00:00",
        "delivery_method": "warehouse",
    }
    row.update(overrides)
    return row


def test_build_fact_finance_realization_line_db_row_maps_required_fields() -> None:
    loaded_at = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)

    mapped = build_fact_finance_realization_line_db_row(_sample_row(), loaded_at=loaded_at)

    assert mapped["rrd_id"] == 101
    assert mapped["operation_date"] == date(2026, 7, 14)
    assert mapped["operation_date_source"] == "rr_dt"
    assert mapped["nm_id"] == 111
    assert mapped["delivery_rub"] == Decimal("120.50")
    assert mapped["rebill_logistic_cost"] == Decimal("9.50")
    assert mapped["office_name"] == "Коледино"
    assert mapped["source_status"] == "API_200"
    assert mapped["loaded_at"] == loaded_at


def test_prepare_fact_finance_realization_line_upsert_rows_deduplicates_by_rrd_id() -> None:
    rows = [
        _sample_row(rrd_id=101, delivery_rub="10.00"),
        _sample_row(rrd_id=101, delivery_rub="15.00"),
        _sample_row(rrd_id=None),
        _sample_row(rrd_id=303, rr_dt=None, date_from=None, date_to=None),
    ]

    prepared, row_errors = prepare_fact_finance_realization_line_upsert_rows(rows)

    assert len(prepared) == 1
    assert prepared[0]["rrd_id"] == 101
    assert prepared[0]["delivery_rub"] == Decimal("15.00")
    assert {error["reason"] for error in row_errors} == {"missing_rrd_id", "missing_operation_date"}


def test_fetch_report_detail_by_period_pages_falls_back_limit_and_stops_on_empty_page() -> None:
    calls: list[dict[str, int]] = []

    def requester(params):
        calls.append({"limit": params["limit"], "rrdid": params["rrdid"]})
        if params["limit"] == 100000:
            return FinanceRealizationPageResult(http_status="400", payload={"error": "too large"}, error="too large", request_params=params)
        if params["rrdid"] == 0:
            return FinanceRealizationPageResult(
                http_status="200",
                payload=[_sample_row(rrd_id=101), _sample_row(rrd_id=102)],
                error="",
                request_params=params,
                limit_used=params["limit"],
            )
        return FinanceRealizationPageResult(
            http_status="200",
            payload=[],
            error="",
            request_params=params,
            limit_used=params["limit"],
        )

    rows, meta = fetch_report_detail_by_period_pages(
        start=date(2026, 7, 14),
        end=date(2026, 7, 14),
        requester=requester,
        page_limit_options=(100000, 200),
        window_days=7,
    )

    assert [item["rrd_id"] for item in rows] == [101, 102]
    assert meta["status"] == "200"
    assert meta["rows_raw"] == 2
    assert len(meta["page_logs"]) == 1
    assert calls[:2] == [{"limit": 100000, "rrdid": 0}, {"limit": 200, "rrdid": 0}]
    assert len(meta["request_attempts"]) == 2


def test_build_finance_realization_article_daily_aggregate_computes_daily_metrics() -> None:
    frame = pd.DataFrame.from_records(
        [
            {"operation_date": date(2026, 7, 14), "nm_id": 111, "sa_name": "A", "quantity": 2, "delivery_rub": 100, "rebill_logistic_cost": 20, "storage_fee": 5, "acceptance": 1, "deduction": 0, "penalty": 0, "additional_payment": 0, "office_name": "X"},
            {"operation_date": date(2026, 7, 15), "nm_id": 111, "sa_name": "A", "quantity": 4, "delivery_rub": 60, "rebill_logistic_cost": 10, "storage_fee": 2, "acceptance": 0, "deduction": 0, "penalty": 0, "additional_payment": 0, "office_name": "X"},
        ]
    )

    aggregated = build_finance_realization_article_daily_aggregate(frame)

    assert list(aggregated["logistics_total"]) == [120, 70]
    assert list(aggregated["logistics_per_unit"]) == [60, 17.5]
    assert pd.isna(aggregated.loc[0, "previous_day_logistics_total"])
    assert aggregated.loc[1, "previous_day_logistics_total"] == 120
    assert aggregated.loc[1, "day_over_day_logistics_delta"] == -50


def test_build_finance_realization_office_daily_aggregate_marks_office_as_unconfirmed() -> None:
    frame = pd.DataFrame.from_records(
        [
            {"operation_date": date(2026, 7, 14), "office_name": "Коледино", "quantity": 1, "delivery_rub": 50, "rebill_logistic_cost": 5, "storage_fee": 0, "acceptance": 0, "deduction": 0, "penalty": 0, "additional_payment": 0},
        ]
    )

    aggregated = build_finance_realization_office_daily_aggregate(frame)

    assert bool(aggregated.loc[0, "office_name_unconfirmed"]) is True
    assert "not a confirmed WB warehouse" in aggregated.loc[0, "attribute_note"]


def test_build_last_7_vs_previous_7_compares_adjacent_windows() -> None:
    records = []
    for day_number in range(1, 15):
        records.append(
            {
                "operation_date": date(2026, 7, day_number),
                "nm_id": 111,
                "sa_name": "A",
                "quantity": 1,
                "delivery_rub": day_number,
                "rebill_logistic_cost": 0,
                "storage_fee": 0,
                "acceptance": 0,
                "deduction": 0,
                "penalty": 0,
                "additional_payment": 0,
            }
        )
    frame = pd.DataFrame.from_records(records)

    comparison = build_last_7_vs_previous_7(frame, group_keys=("nm_id", "sa_name"), end_date=date(2026, 7, 14))

    assert comparison.loc[0, "last_7_logistics_total"] == sum(range(8, 15))
    assert comparison.loc[0, "prev_7_logistics_total"] == sum(range(1, 8))
    assert comparison.loc[0, "delta"] == sum(range(8, 15)) - sum(range(1, 8))
