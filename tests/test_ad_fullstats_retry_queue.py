from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from src.db.ad_fullstats_retry_queue import (
    build_failed_group_row,
    classify_fullstats_error_type,
    schedule_next_retry_at,
)


def test_classify_fullstats_error_type_maps_rate_limit() -> None:
    assert classify_fullstats_error_type("429 Too Many Requests") == "RATE_LIMIT"
    assert classify_fullstats_error_type("500 Internal Server Error") == "API_ERROR"
    assert classify_fullstats_error_type("") == "EMPTY"


def test_schedule_next_retry_at_uses_attempt_count_multiplier() -> None:
    attempted_at = datetime(2026, 6, 17, 10, 0, tzinfo=UTC)

    assert schedule_next_retry_at(attempted_at, attempts_count=1, retry_delay_seconds=25) == attempted_at + timedelta(seconds=25)
    assert schedule_next_retry_at(attempted_at, attempts_count=3, retry_delay_seconds=25) == attempted_at + timedelta(seconds=75)


def test_build_failed_group_row_increments_attempts_and_sets_pending_retry() -> None:
    attempted_at = datetime(2026, 6, 17, 10, 0, tzinfo=UTC)

    row = build_failed_group_row(
        date_from=date(2026, 6, 8),
        date_to=date(2026, 6, 16),
        advert_id=33285505,
        group_key="2026-06-08:2026-06-16:33285505",
        campaign_name="Campaign A",
        nm_ids=[197330807, 37320545],
        error_type="RATE_LIMIT",
        last_error="429 Too Many Requests",
        attempts_count=2,
        attempted_at=attempted_at,
        retry_delay_seconds=25,
    )

    assert row["date_from"] == date(2026, 6, 8)
    assert row["date_to"] == date(2026, 6, 16)
    assert row["advert_id"] == 33285505
    assert row["group_key"] == "2026-06-08:2026-06-16:33285505"
    assert row["campaign_name"] == "Campaign A"
    assert row["nm_ids_json"] == [197330807, 37320545]
    assert row["error_type"] == "RATE_LIMIT"
    assert row["attempts_count"] == 2
    assert row["status"] == "pending"
    assert row["last_attempt_at"] == attempted_at
    assert row["next_retry_at"] == attempted_at + timedelta(seconds=50)
