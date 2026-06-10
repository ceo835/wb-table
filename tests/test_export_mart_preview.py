from __future__ import annotations

from datetime import date
from decimal import Decimal

from scripts.export_mart_preview import (
    is_ad_aggregates_check_row,
    is_formula_sample_row,
    is_without_any_data_row,
    project_rows,
)


def test_is_formula_sample_row_requires_at_least_one_calculated_metric():
    row = {
        "report_date": date(2026, 6, 1),
        "nm_id": 197330807,
        "ctr_calc": None,
        "ad_cost_per_cart_calc": Decimal("6"),
    }
    assert is_formula_sample_row(row) is True
    assert is_formula_sample_row({"ctr_calc": None, "ad_cpc_calc": None, "ad_cost_per_cart_calc": None}) is False


def test_is_without_any_data_row_checks_all_coverage_flags():
    empty_row = {
        "has_funnel": False,
        "has_stock": False,
        "has_ad_cost": False,
        "has_ad_campaign": False,
        "has_search": False,
        "has_localization_partial": False,
    }
    nonempty_row = {**empty_row, "has_search": True}
    assert is_without_any_data_row(empty_row) is True
    assert is_without_any_data_row(nonempty_row) is False


def test_project_rows_keeps_only_requested_columns():
    rows = [{"report_date": date(2026, 6, 1), "nm_id": 1, "extra": "x"}]
    assert project_rows(rows, ["report_date", "nm_id"]) == [{"report_date": date(2026, 6, 1), "nm_id": 1}]


def test_is_ad_aggregates_check_row_accepts_campaign_or_spend_rows():
    assert is_ad_aggregates_check_row({"has_ad_campaign": True, "ad_spend_total": None}) is True
    assert is_ad_aggregates_check_row({"has_ad_campaign": False, "ad_spend_total": Decimal("100")}) is True
    assert is_ad_aggregates_check_row({"has_ad_campaign": False, "ad_spend_total": None}) is False


def test_is_ad_aggregates_check_row_accepts_new_explicit_spend_sources():
    assert is_ad_aggregates_check_row({"has_ad_campaign": False, "ad_spend_total": None, "ad_cost_writeoff_total": Decimal("50")}) is True
    assert is_ad_aggregates_check_row({"has_ad_campaign": False, "ad_spend_total": None, "ad_campaign_spend_total": Decimal("55")}) is True
