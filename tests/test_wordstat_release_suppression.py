from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from src.services.external_context.service import (
    _wordstat_display_decision,
    wordstat_release_key,
)


class _ScalarSession:
    def __init__(self, state=None):
        self.state = state

    def scalar(self, _statement):
        return self.state


def _metric(retrieved_at: datetime, period_start=date(2026, 7, 13), period_end=date(2026, 7, 19)):
    return SimpleNamespace(
        metric_code="search_demand_womens_tshirts",
        period_start=period_start,
        period_end=period_end,
        retrieved_at=retrieved_at,
        published_at=None,
    )


def _state(metric, *, wb_change_pct=Decimal("5"), wb_direction="growth", comparison_direction="matching"):
    return SimpleNamespace(
        wordstat_release_key=wordstat_release_key(metric),
        first_shown_report_date=date(2026, 7, 19),
        last_shown_report_date=date(2026, 7, 19),
        last_wb_change_pct=wb_change_pct,
        last_wb_direction=wb_direction,
        last_comparison_direction=comparison_direction,
    )


def test_wordstat_release_is_shown_on_first_available_report_day():
    metric = _metric(datetime(2026, 7, 19, 10, 0))
    result = _wordstat_display_decision(
        _ScalarSession(), metric, date(2026, 7, 19), Decimal("5"), "matching"
    )

    assert result["should_show"] is True
    assert result["is_new_release"] is True
    assert result["is_repeat_suppressed"] is False
    assert result["repeat_reason"] == "new_wordstat_release"
    assert result["first_shown_report_date"] == date(2026, 7, 19)


def test_same_wordstat_release_is_suppressed_on_next_day_without_material_change():
    metric = _metric(datetime(2026, 7, 19, 10, 0))
    result = _wordstat_display_decision(
        _ScalarSession(_state(metric)), metric, date(2026, 7, 20), Decimal("8"), "matching"
    )

    assert result["should_show"] is False
    assert result["is_repeat_suppressed"] is True
    assert result["repeat_reason"] == "same_wordstat_release_no_material_change"


def test_new_wordstat_period_is_shown_as_new_release():
    old_metric = _metric(datetime(2026, 7, 19, 10, 0))
    new_metric = _metric(
        datetime(2026, 7, 26, 10, 0),
        period_start=date(2026, 7, 20),
        period_end=date(2026, 7, 26),
    )
    result = _wordstat_display_decision(
        _ScalarSession(), new_metric, date(2026, 7, 26), Decimal("5"), "matching"
    )

    assert wordstat_release_key(old_metric) != wordstat_release_key(new_metric)
    assert result["should_show"] is True
    assert result["is_new_release"] is True


def test_wb_direction_change_allows_same_release_repeat():
    metric = _metric(datetime(2026, 7, 19, 10, 0))
    result = _wordstat_display_decision(
        _ScalarSession(_state(metric)), metric, date(2026, 7, 20), Decimal("-2"), "matching"
    )

    assert result["should_show"] is True
    assert result["is_repeat_suppressed"] is False
    assert "wb_direction_changed" in result["repeat_reason"]


def test_wb_change_below_ten_percentage_points_does_not_allow_repeat():
    metric = _metric(datetime(2026, 7, 19, 10, 0))
    result = _wordstat_display_decision(
        _ScalarSession(_state(metric)), metric, date(2026, 7, 20), Decimal("14.9"), "matching"
    )

    assert result["should_show"] is False
    assert result["is_repeat_suppressed"] is True

def test_retrieval_timestamp_is_part_of_wordstat_release_key():
    first = _metric(datetime(2026, 7, 19, 10, 0))
    refetched = _metric(datetime(2026, 7, 20, 10, 0))

    assert wordstat_release_key(first) != wordstat_release_key(refetched)