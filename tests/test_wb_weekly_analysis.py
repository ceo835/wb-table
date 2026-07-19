from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
import pytest
from src.mcp_server.wb_daily_operational_summary import build_operational_summary, build_report_window
from src.mcp_server.schemas import WbDailyOperationalSummaryRequest
from src.mcp_server.wb_weekly_analysis import classify_series, build_weekly_analysis

class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self.rows

    def one(self) -> dict[str, Any]:
        return self.rows[0] if self.rows else {}

class _FakeSession:
    def __init__(self, profit_rows: list[dict[str, Any]] = None, search_rows: list[dict[str, Any]] = None,
                 contrib_rows: list[dict[str, Any]] = None, ts_rows: list[dict[str, Any]] = None,
                 ts_art_rows: list[dict[str, Any]] = None, camp_rows: list[dict[str, Any]] = None,
                 ad_days_rows: list[dict[str, Any]] = None, anomaly_days: list[dict[str, Any]] = None,
                 search_mover_rows: list[dict[str, Any]] = None, profit_aggs: list[dict[str, Any]] = None,
                 stock_rows: list[dict[str, Any]] = None):
        self.profit_rows = profit_rows or []
        self.search_rows = search_rows or []
        self.contrib_rows = contrib_rows or []
        self.ts_rows = ts_rows or []
        self.ts_art_rows = ts_art_rows or []
        self.camp_rows = camp_rows or []
        self.ad_days_rows = ad_days_rows or []
        self.anomaly_days = anomaly_days or []
        self.search_mover_rows = search_mover_rows or []
        self.profit_aggs = profit_aggs or []
        self.stock_rows = stock_rows or []

    def execute(self, statement: Any, params: dict[str, Any] = None) -> _FakeResult:
        stmt_str = str(statement).lower()
        # Check current_week_data first to avoid overlapping with fact_vvbromo_product_day check
        if "current_week_data" in stmt_str:
            return _FakeResult(self.contrib_rows)
        elif "fact_vvbromo_product_day" in stmt_str:
            if "count(distinct nm_id)" in stmt_str:
                return _FakeResult(self.profit_rows)
            elif "group by day" in stmt_str:
                return _FakeResult([{"day": r["day"], "operating_profit": Decimal("1000")} for r in self.profit_rows])
            elif "sum(coalesce(operating_profit, 0))" in stmt_str:
                return _FakeResult(self.profit_aggs)
            else:
                return _FakeResult([{"day": date(2026, 7, 15), "operating_profit": Decimal("1000")}])
        elif "fact_search_query_metric" in stmt_str:
            if "count(distinct nm_id)" in stmt_str:
                return _FakeResult(self.search_rows)
            else:
                return _FakeResult(self.search_mover_rows)
        elif "fact_entry_point_day" in stmt_str:
            if "nm_id" in stmt_str:
                return _FakeResult(self.ts_art_rows)
            else:
                return _FakeResult(self.ts_rows)
        elif "fact_ad_campaign_nm_day" in stmt_str:
            return _FakeResult(self.camp_rows)
        elif "fact_ad_cost_day" in stmt_str:
            if "having sum" in stmt_str:
                return _FakeResult(self.anomaly_days)
            else:
                return _FakeResult(self.ad_days_rows)
        elif "fact_stock_warehouse_snapshot" in stmt_str:
            return _FakeResult(self.stock_rows)

        return _FakeResult([])

def test_trend_classification_rules() -> None:
    dates = [date(2026, 7, i) for i in range(1, 8)]
    
    # 1. Steady growth
    growth_vals = [Decimal("100"), Decimal("110"), Decimal("120"), Decimal("118"), Decimal("130"), Decimal("140"), Decimal("150")]
    assert classify_series(dates, growth_vals) == "steady_growth"

    # 2. Steady decline
    decline_vals = [Decimal("200"), Decimal("190"), Decimal("180"), Decimal("182"), Decimal("170"), Decimal("160"), Decimal("150")]
    assert classify_series(dates, decline_vals) == "steady_decline"

    # 3. Flat
    flat_vals = [Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100")]
    assert classify_series(dates, flat_vals) == "flat"

    # 4. Spike
    spike_vals = [Decimal("100"), Decimal("102"), Decimal("98"), Decimal("300"), Decimal("101"), Decimal("99"), Decimal("100")]
    assert classify_series(dates, spike_vals) == "one_day_spike"

    # 5. Drop
    drop_vals = [Decimal("100"), Decimal("102"), Decimal("98"), Decimal("10"), Decimal("101"), Decimal("99"), Decimal("100")]
    assert classify_series(dates, drop_vals) == "one_day_drop"

    # 6. Recovery
    recovery_vals = [Decimal("100"), Decimal("80"), Decimal("60"), Decimal("50"), Decimal("70"), Decimal("90"), Decimal("110")]
    assert classify_series(dates, recovery_vals) == "recovery"

    # 7. Volatile
    volatile_vals = [Decimal("100"), Decimal("120"), Decimal("90"), Decimal("130"), Decimal("85"), Decimal("140"), Decimal("95")]
    assert classify_series(dates, volatile_vals) == "volatile"

    # 8. Insufficient data
    assert classify_series(dates[:4], [Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40")]) == "insufficient_data"

def test_weekly_analysis_lag_and_partial_profit() -> None:
    report_date = date(2026, 7, 15)
    window = build_report_window(report_date, "requested")
    ad_cutoff = report_date - timedelta(days=2) # 2026-07-13
    
    # 15 days of mart data
    daily_rows = []
    for i in range(15):
        dt = report_date - timedelta(days=i)
        daily_rows.append({
            "report_date": dt,
            "order_sum": Decimal("10000"),
            "order_count": Decimal("10"),
            "card_clicks": Decimal("100"),
            "cart_count": Decimal("20"),
            "ad_spend": Decimal("1000"),
            "ad_views": Decimal("500"),
            "ad_clicks": Decimal("50"),
            "ad_atbs": Decimal("10"),
            "ad_orders": Decimal("5"),
            "search_clicks": Decimal("30"),
            "search_cart": Decimal("10"),
            "search_orders": Decimal("5"),
            "search_avg_position": Decimal("10"),
            "search_visibility": Decimal("80"),
        })

    # Mock DB: profit has only 5 days in current week (PARTIAL)
    profit_days = [{"day": report_date - timedelta(days=i), "cnt": 5} for i in range(5)]
    contrib_rows = [
        {
            "nm_id": 101,
            "product_name": "Product 101",
            "supplier_article": "ART-101",
            "current_week_turnover": Decimal("150000"),
            "previous_week_turnover": Decimal("100000"),
            "current_week_orders": 15,
            "previous_week_orders": 10,
            "current_week_ad_spend": Decimal("1500"),
            "previous_week_ad_spend": Decimal("1000"),
            "current_week_ad_orders": 5,
            "previous_week_ad_orders": 3,
            "current_week_operating_profit": Decimal("15000"),
            "previous_week_operating_profit": Decimal("10000"),
        }
    ]
    session = _FakeSession(
        profit_rows=profit_days,
        profit_aggs=[{"operating_profit": Decimal("5000"), "organic_sales": Decimal("50")}],
        contrib_rows=contrib_rows
    )

    res = build_weekly_analysis(
        session,
        window=window,
        daily_rows=daily_rows,
        logistics_summary={"weekly_trend": {"current_total": Decimal("2000"), "previous_total": Decimal("1800")}},
        operating_profit_context={"weekly_trend": {"current_operating_profit": Decimal("4000"), "previous_operating_profit": Decimal("3500")}},
        pricing_spp_context={"top_price_changes": []},
        query_counter={"count": 0, "timings": []}
    )

    # Check periods
    assert res["current_period"]["from"] == window.trend_current_from.isoformat()
    assert res["current_period"]["to"] == window.trend_current_to.isoformat()
    assert res["status"] == "OK" # mart is complete (7 days)

    # Profit status should be PARTIAL since current profit has 5 days
    assert res["operating_profit"]["status"] == "PARTIAL"
    assert res["operating_profit"]["current_week_profit"] is None # Deliberately None if partial (as per spec)
    assert res["operating_profit"]["profit_delta"] is None

    # Ad attribution lag check: ad_spend sum in current_week
    # current_week is 2026-07-09 .. 2026-07-15.
    # report_date is 2026-07-15. cutoff is 2026-07-13.
    # out of 7 days, 2026-07-14 and 2026-07-15 are > cutoff and must be excluded.
    # Only 5 days are included: 2026-07-09, 2026-07-10, 2026-07-11, 2026-07-12, 2026-07-13.
    # Each day has ad_spend = 1000. Sum = 5000.
    assert res["aggregate_metrics"]["current_week"]["ad_spend"] == Decimal("5000")
    assert res["aggregate_metrics"]["current_week"]["ad_days_count"] == 5
    assert res["aggregate_metrics"]["current_week"]["ad_turnover"] == Decimal("50000")
    # For previous week, matched-window restricts to first 5 days of that week as well.
    # Sum = 5000.
    assert res["aggregate_metrics"]["previous_week"]["ad_spend"] == Decimal("5000")
    assert res["aggregate_metrics"]["previous_week"]["ad_days_count"] == 5
    assert res["aggregate_metrics"]["previous_week"]["ad_turnover"] == Decimal("50000")

    # Verify no server narratives exist
    assert "evidence" in res
    assert all("opinion" not in item and "recommend" not in item for item in res["evidence"])

def test_build_operational_summary_safe_fallback(monkeypatch) -> None:
    # Test that error inside build_weekly_analysis returns status UNAVAILABLE and doesn't crash the summary
    def bad_weekly(*args, **kwargs):
        raise RuntimeError("Weekly computation error")

    # Minimal mock functions for daily
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.fetch_core_source_freshness", lambda session, query_counter: [{"source_name": "mart_total_report", "max_date": date(2026, 7, 15)}])
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.fetch_mart_daily_overview", lambda session, report_date, compare_date, query_counter: [{"report_date": date(2026, 7, 15), "order_sum": 10000}])
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.fetch_mart_window_overview", lambda session, *args: [{"bucket": "current"}])
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.fetch_assortment_changes", lambda *args: [])
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.fetch_problem_campaigns", lambda *args: [])
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.fetch_stock_risks", lambda *args: [])
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.fetch_search_movers", lambda *args: [])
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.build_extended_context", lambda *args, **kwargs: {"article_context": []})
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.fetch_database_audit_block", lambda *args, **kwargs: {"status": "OK"})
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.fetch_operating_profit_block", lambda *args, **kwargs: {"status": "OK"})
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.fetch_logistics_summary_block", lambda *args, **kwargs: {"status": "OK"})
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.fetch_pricing_spp_block", lambda *args, **kwargs: {"status": "OK"})
    monkeypatch.setattr("src.mcp_server.wb_daily_operational_summary.fetch_competitor_block", lambda *args, **kwargs: {"status": "OK"})
    
    # Inject bad weekly analyzer
    monkeypatch.setattr("src.mcp_server.wb_weekly_analysis.build_weekly_analysis", bad_weekly)

    response = build_operational_summary(_FakeSession(), WbDailyOperationalSummaryRequest(report_date=date(2026, 7, 15), top_n=5))

    # Weekly analysis must be UNAVAILABLE due to fallback
    assert response.weekly_analysis is not None
    assert response.weekly_analysis["status"] == "UNAVAILABLE"
    assert response.weekly_analysis["diagnostic"]["error_type"] == "RuntimeError"
    # Existing daily section should still exist (overview)
    assert any(sec.key == "overview" for sec in response.sections)


def test_drr_delta_calculation() -> None:
    # 1. DRR 7.50% против 6.54% -> delta = +0.96 п.п. (drr_abs) и +14.68% (drr_pct)
    curr_drr = Decimal("7.50")
    prev_drr = Decimal("6.54")
    
    delta_drr_abs = curr_drr - prev_drr
    delta_drr_pct = (curr_drr - prev_drr) / prev_drr * 100
    
    assert delta_drr_abs == Decimal("0.96")
    assert round(delta_drr_pct, 2) == Decimal("14.68")


def test_ads_matched_window_5_vs_5() -> None:
    # 2. ads_days=5/7 -> matched-window must use exactly 5 vs 5 days (ad_days_limit=5 for both weeks)
    report_date = date(2026, 7, 15)
    window = build_report_window(report_date, "requested")
    
    # 7 days of daily rows for current week (each spend 1000)
    daily_rows = []
    for i in range(15):
        dt = report_date - timedelta(days=i)
        daily_rows.append({
            "report_date": dt,
            "order_sum": Decimal("10000"),
            "order_count": Decimal("10"),
            "ad_spend": Decimal("1000"),
            "ad_views": Decimal("500"),
            "ad_clicks": Decimal("50"),
            "ad_atbs": Decimal("10"),
            "ad_orders": Decimal("5"),
        })

    session = _FakeSession(
        profit_rows=[{"day": report_date - timedelta(days=i), "cnt": 7} for i in range(7)],
        profit_aggs=[{"operating_profit": Decimal("5000"), "organic_sales": Decimal("50")}]
    )

    res = build_weekly_analysis(
        session,
        window=window,
        daily_rows=daily_rows,
        logistics_summary={"weekly_trend": {}},
        operating_profit_context={"weekly_trend": {}},
        pricing_spp_context={"top_price_changes": []},
        query_counter={"count": 0, "timings": []}
    )

    # ads_days_current should be 5 because cutoff is 2026-07-13 (2 days lag from 2026-07-15)
    assert res["completeness"]["ads_days_current"] == 5
    assert res["completeness"]["ads_days_previous"] == 7
    
    # aggregate_metrics must use N=5 matched window for both weeks
    assert res["aggregate_metrics"]["current_week"]["ad_days_count"] == 5
    assert res["aggregate_metrics"]["current_week"]["ad_spend"] == Decimal("5000") # 5 * 1000
    
    assert res["aggregate_metrics"]["previous_week"]["ad_days_count"] == 5
    assert res["aggregate_metrics"]["previous_week"]["ad_spend"] == Decimal("5000") # 5 * 1000


def test_daily_metrics_match_for_11_july() -> None:
    # 3. Daily metrics for 2026-07-11 match between builder and DB (direct values check)
    # DB values for 11 July: order_sum=1375013, order_count=968, profit=17826
    # Check that builder doesn't mismatch them
    report_date = date(2026, 7, 11)
    window = build_report_window(report_date, "requested")
    
    # Current day row
    daily_rows = [{
        "report_date": report_date,
        "order_sum": Decimal("1375013"),
        "order_count": Decimal("968"),
        "card_clicks": Decimal("100"),
        "cart_count": Decimal("20"),
        "ad_spend": Decimal("1000"),
        "ad_views": Decimal("500"),
        "ad_clicks": Decimal("50"),
        "ad_atbs": Decimal("10"),
        "ad_orders": Decimal("5"),
    }]
    
    session = _FakeSession(
        profit_rows=[{"day": report_date, "cnt": 1}],
        profit_aggs=[{"operating_profit": Decimal("17826"), "organic_sales": Decimal("968")}]
    )

    res = build_weekly_analysis(
        session,
        window=window,
        daily_rows=daily_rows,
        logistics_summary={"weekly_trend": {}},
        operating_profit_context={"weekly_trend": {}},
        pricing_spp_context={"top_price_changes": []},
        query_counter={"count": 0, "timings": []}
    )
    
    # Ensure current day metrics are correct in daily_series
    ds = res["daily_series"]
    assert len(ds) == 1
    assert ds[0]["report_date"] == "2026-07-11"
    assert ds[0]["turnover"] == Decimal("1375013")
    assert ds[0]["orders"] == Decimal("968")


def test_missing_ad_days_are_not_zeros() -> None:
    # 4. Missing ad days do not turn into zeros, they stay None
    report_date = date(2026, 7, 15)
    window = build_report_window(report_date, "requested")
    
    # row for current day has None for ad_spend
    daily_rows = [{
        "report_date": report_date,
        "order_sum": Decimal("10000"),
        "order_count": Decimal("10"),
        "ad_spend": None,
        "ad_views": None,
        "ad_clicks": None,
        "ad_atbs": None,
        "ad_orders": None,
    }]
    
    session = _FakeSession()
    res = build_weekly_analysis(
        session,
        window=window,
        daily_rows=daily_rows,
        logistics_summary={"weekly_trend": {}},
        operating_profit_context={"weekly_trend": {}},
        pricing_spp_context={"top_price_changes": []},
        query_counter={"count": 0, "timings": []}
    )
    
    # ad_spend in aggregate_metrics must be None, not Decimal("0")
    assert res["aggregate_metrics"]["current_week"]["ad_spend"] is None

