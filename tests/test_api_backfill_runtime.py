from __future__ import annotations

from datetime import date

from scripts.backfill_target_products_api_data import (
    TARGET_METRIC_FIELDS,
    _completed_chunk_keys,
    _error_type_from_text,
    _filter_already_completed_plan,
    _normalize_sources,
    _resolve_window_bounds,
    _row_has_target_metric,
    _split_date_windows,
    _status_from_result,
)


def test_target_metric_fields_include_requested_business_metrics():
    assert "impressions" in TARGET_METRIC_FIELDS
    assert "card_clicks" in TARGET_METRIC_FIELDS
    assert "cart_count" in TARGET_METRIC_FIELDS
    assert "order_count" in TARGET_METRIC_FIELDS
    assert "order_sum" in TARGET_METRIC_FIELDS
    assert "ad_campaign_spend_total" in TARGET_METRIC_FIELDS
    assert "ad_views_total" in TARGET_METRIC_FIELDS
    assert "ad_clicks_total" in TARGET_METRIC_FIELDS
    assert "ad_atbs_total" in TARGET_METRIC_FIELDS
    assert "ad_orders_total" in TARGET_METRIC_FIELDS
    assert "current_stock_qty" in TARGET_METRIC_FIELDS
    assert "current_mp_stock_qty" in TARGET_METRIC_FIELDS
    assert "search_queries_count" in TARGET_METRIC_FIELDS
    assert "local_orders_percent" in TARGET_METRIC_FIELDS


def test_row_has_target_metric_detects_any_non_null_business_field():
    assert _row_has_target_metric({"nm_id": 1, "order_sum": None, "search_queries_count": None}) is False
    assert _row_has_target_metric({"nm_id": 1, "order_sum": "100.00", "search_queries_count": None}) is True
    assert _row_has_target_metric({"nm_id": 1, "order_sum": None, "search_queries_count": 0}) is True


def test_split_date_windows_respects_31_day_limit():
    assert _split_date_windows(date(2026, 5, 1), date(2026, 6, 7), 31) == [
        (date(2026, 5, 1), date(2026, 5, 31)),
        (date(2026, 6, 1), date(2026, 6, 7)),
    ]


def test_error_type_marks_api_date_limit_as_deterministic():
    assert _error_type_from_text(
        '400 {"detail":"validate: invalid start day: excess limit on days"}'
    ) == "API_DATE_LIMIT"
    assert _error_type_from_text(
        '400 {"detail":"validate: invalid start day: excess limit"}'
    ) == "API_DATE_LIMIT"
    assert _error_type_from_text('429 {"title":"too many requests"}') == "429"
    assert _error_type_from_text("timeout while waiting for response") == "TIMEOUT"


def test_status_from_result_distinguishes_empty_response_and_no_data():
    assert _status_from_result("stocks", {"rows_fetched": 0, "pages_loaded": 1}, "") == ("EMPTY_RESPONSE", "EMPTY_RESPONSE")
    assert _status_from_result("search", {"rows_fetched": 0}, "") == ("NO_DATA", "NO_DATA")
    assert _status_from_result("funnel", {"rows_fetched": 0}, "") == ("NO_DATA", "NO_DATA")
    assert _status_from_result("search", {"rows_fetched": 10, "current_failed_pages": [{"offset": 100}]}, "") == (
        "FAILED_PAGES",
        "FAILED_PAGES",
    )


def test_normalize_sources_validates_and_preserves_order():
    assert _normalize_sources(["search", "stocks"]) == ("search", "stocks")


def test_completed_chunk_keys_include_ok_and_no_data_statuses():
    state = {
        "source_logs": [
            {"source_name": "search", "report_date": "2026-05-01", "chunk_number": 1, "status": "OK", "advert_id": None},
            {"source_name": "search", "report_date": "2026-05-01", "chunk_number": 2, "status": "NO_DATA", "advert_id": None},
            {"source_name": "search", "report_date": "2026-05-01", "chunk_number": 3, "status": "FAILED_CHUNK", "advert_id": None},
            {"source_name": "stocks", "report_date": "2026-05-01", "chunk_number": 1, "status": "OK", "advert_id": None},
        ]
    }
    assert _completed_chunk_keys(state, "search") == {
        ("search", "2026-05-01", 1, None),
        ("search", "2026-05-01", 2, None),
    }


def test_filter_already_completed_plan_skips_previously_completed_items():
    plan = [
        {"report_date": "2026-05-01", "chunk_number": 1, "nm_ids": [1, 2]},
        {"report_date": "2026-05-01", "chunk_number": 2, "nm_ids": [3, 4]},
        {"report_date": "2026-05-02", "chunk_number": 1, "nm_ids": [1, 2]},
    ]
    completed = {
        ("search", "2026-05-01", 1, None),
        ("search", "2026-05-02", 1, None),
    }
    assert _filter_already_completed_plan(plan, source_name="search", completed_keys=completed) == [
        {"report_date": "2026-05-01", "chunk_number": 2, "nm_ids": [3, 4]},
    ]


def test_resolve_window_bounds_supports_window_strings_and_explicit_keys():
    assert _resolve_window_bounds({"report_date": "2026-05-01..2026-05-07"}) == (
        date(2026, 5, 1),
        date(2026, 5, 7),
    )
    assert _resolve_window_bounds({"window_start": "2026-05-08", "window_end": "2026-05-14", "report_date": "ignored"}) == (
        date(2026, 5, 8),
        date(2026, 5, 14),
    )
