from __future__ import annotations

from datetime import UTC, date, datetime

from src.reports.wb_api_data_availability import (
    build_recommendation,
    classify_source_status,
    resolve_target_date,
    summarize_metric_rows,
)


def test_resolve_target_date_uses_yesterday_in_project_timezone() -> None:
    now = datetime(2026, 6, 21, 0, 30, tzinfo=UTC)

    assert resolve_target_date(now=now, timezone_name="Europe/Moscow") == date(2026, 6, 20)


def test_classify_source_status_distinguishes_available_partial_empty_and_error() -> None:
    assert classify_source_status(
        rows_count=59,
        products_count=59,
        expected_products_count=59,
        has_nonzero_metrics=True,
    ) == "AVAILABLE"
    assert classify_source_status(
        rows_count=59,
        products_count=12,
        expected_products_count=59,
        has_nonzero_metrics=True,
    ) == "PARTIAL"
    assert classify_source_status(
        rows_count=10,
        products_count=10,
        expected_products_count=10,
        has_nonzero_metrics=False,
    ) == "PARTIAL"
    assert classify_source_status(
        rows_count=0,
        products_count=0,
        expected_products_count=59,
        has_nonzero_metrics=False,
    ) == "EMPTY"
    assert classify_source_status(
        rows_count=0,
        products_count=0,
        expected_products_count=59,
        has_nonzero_metrics=False,
        error_message="timeout",
    ) == "ERROR"


def test_summarize_metric_rows_counts_products_and_nonzero_fields() -> None:
    rows = [
        {"nm_id": 1, "card_clicks": 0, "orderCount": None},
        {"nm_id": 2, "card_clicks": 4, "orderCount": 0},
        {"nm_id": 2, "card_clicks": None, "orderCount": 0},
    ]

    summary = summarize_metric_rows(rows, metric_fields=("card_clicks", "orderCount"))

    assert summary["rows_count"] == 3
    assert summary["products_count"] == 2
    assert summary["has_nonzero_metrics"] is True
    assert summary["nonzero_metric_fields"] == ["card_clicks"]


def test_build_recommendation_flags_missing_core_refresh_when_api_is_available() -> None:
    source_results = [
        type(
            "SourceRow",
            (),
            {"source_name": "funnel", "status": "AVAILABLE"},
        )(),
        type(
            "SourceRow",
            (),
            {"source_name": "ad_cost", "status": "EMPTY"},
        )(),
    ]
    db_snapshot = {
        "mart_total_report": {
            "rows_count": 247,
            "card_clicks_rows": 0,
            "ad_spend_rows": 0,
            "search_rows": 0,
        }
    }

    recommendation = build_recommendation(
        source_results=source_results,
        db_snapshot=db_snapshot,
        scheduler_runs_core_refresh=False,
    )

    assert recommendation["conclusion"] == "scheduler_missing_core_refresh"
    assert recommendation["available_sources"] == ["funnel"]


def test_build_recommendation_flags_combined_scheduler_gap_and_api_latency() -> None:
    source_results = [
        type(
            "SourceRow",
            (),
            {"source_name": "ad_cost", "status": "PARTIAL"},
        )(),
    ]
    db_snapshot = {
        "mart_total_report": {
            "rows_count": 247,
            "card_clicks_rows": 0,
            "ad_spend_rows": 0,
            "search_rows": 0,
        }
    }

    recommendation = build_recommendation(
        source_results=source_results,
        db_snapshot=db_snapshot,
        scheduler_runs_core_refresh=False,
    )

    assert recommendation["conclusion"] == "combined_scheduler_gap_and_api_latency"
