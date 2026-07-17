from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.mcp_server.schemas import (
    WbDailyOperationalDiagnosticsResponse,
    WbDailyOperationalHighlightsResponse,
    WbDailyOperationalReportWindowResponse,
    WbDailyOperationalSourceFreshnessResponse,
    WbDailyOperationalSummaryResponse,
)
from src.mcp_server.wb_daily_operational_summary import (
    build_funnel_section,
    build_sales_section,
    build_scenario_section,
    build_traffic_section,
    collect_highlights,
)
from src.mcp_server.wb_daily_operational_summary_format import render_wb_daily_operational_summary_markdown
from src.mcp_server.wb_daily_operational_summary_sql import fetch_mart_daily_overview, fetch_mart_window_overview


class _FakeResult:
    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict[str, object]]:
        return []


class _CapturingSession:
    def __init__(self) -> None:
        self.statements: list[object] = []
        self.params: list[dict[str, object] | None] = []

    def execute(self, statement, params=None) -> _FakeResult:
        self.statements.append(statement)
        self.params.append(params)
        return _FakeResult()


def _build_response(
    sections,
    highlights: WbDailyOperationalHighlightsResponse,
    *,
    data_gaps: list[dict[str, object]] | None = None,
) -> WbDailyOperationalSummaryResponse:
    return WbDailyOperationalSummaryResponse(
        formula_version="v1",
        report_window=WbDailyOperationalReportWindowResponse(
            report_date=date(2026, 7, 15),
            compare_date=date(2026, 7, 14),
            trend_current_from=date(2026, 7, 9),
            trend_current_to=date(2026, 7, 15),
            trend_previous_from=date(2026, 7, 2),
            trend_previous_to=date(2026, 7, 8),
            report_date_source="requested",
        ),
        requested_options={"mode": "full", "diagnostic": False, "top_n": 5},
        source_freshness=[
            WbDailyOperationalSourceFreshnessResponse(
                source="mart_total_report",
                max_date=date(2026, 7, 15),
                status="OK",
                lag_days=0,
            )
        ],
        sections=sections,
        highlights=highlights,
        diagnostics=WbDailyOperationalDiagnosticsResponse(
            included_sections=[section.key for section in sections],
            partial_sections=[],
            excluded_sections=[],
            query_count=0,
            execution_ms=0,
            formula_version="v1",
        ),
        data_gaps=data_gaps or [],
    )


def test_buyouts_are_hidden_from_markdown_highlights_and_scenario() -> None:
    current = {
        "cart_count": Decimal("100"),
        "add_to_cart_conversion": Decimal("20"),
        "order_count": Decimal("50"),
        "cart_to_order_conversion": Decimal("50"),
        "avg_check": Decimal("1000"),
        "order_sum": Decimal("50000"),
        "buyout_count": Decimal("2"),
        "buyout_sum": Decimal("2000"),
    }
    previous = {
        "cart_count": Decimal("100"),
        "add_to_cart_conversion": Decimal("20"),
        "order_count": Decimal("50"),
        "cart_to_order_conversion": Decimal("50"),
        "avg_check": Decimal("1000"),
        "order_sum": Decimal("50000"),
        "buyout_count": Decimal("20"),
        "buyout_sum": Decimal("20000"),
    }
    funnel = build_funnel_section(current, previous, current, previous)
    sales = build_sales_section(current, previous, current, previous)

    assert funnel is not None
    assert sales is not None
    assert all(metric.metric != "Выкупы" for metric in funnel.metrics)
    assert all(metric.metric not in {"Выкупы", "Сумма выкупов"} for metric in sales.metrics)

    highlights = collect_highlights([funnel, sales], top_n=5)
    scenario = build_scenario_section(highlights)
    response = _build_response(
        [funnel, sales, scenario],
        highlights,
        data_gaps=[{"kind": "buyout_semantics", "status": "PARTIAL", "message": "technical only"}],
    )
    markdown = render_wb_daily_operational_summary_markdown(response)

    assert "Выкупы" not in markdown
    assert "Сумма выкупов" not in markdown
    assert "buyout_semantics" not in markdown
    assert all("выкуп" not in item.lower() for item in highlights.worse + highlights.better + highlights.priority_checks)
    assert all("выкуп" not in item.lower() for item in scenario.summary)


def test_build_traffic_section_keeps_general_and_ad_metrics_separate() -> None:
    current = {
        "impressions": Decimal("1200"),
        "card_clicks": Decimal("120"),
        "ctr": Decimal("10"),
        "ad_views": Decimal("700"),
        "ad_clicks": Decimal("70"),
    }
    previous = {
        "impressions": Decimal("1000"),
        "card_clicks": Decimal("90"),
        "ctr": Decimal("9"),
        "ad_views": Decimal("600"),
        "ad_clicks": Decimal("60"),
    }
    section = build_traffic_section(current, previous, current, previous)

    assert section is not None
    metrics = {metric.metric: metric for metric in section.metrics}
    assert list(metrics) == ["Общие показы", "Общие клики", "CTR общий", "Рекламные показы", "Рекламные клики"]
    assert metrics["Общие показы"].value == Decimal("1200")
    assert metrics["Общие клики"].value == Decimal("120")
    assert metrics["CTR общий"].value == Decimal("10")
    assert metrics["Рекламные показы"].value == Decimal("700")
    assert metrics["Рекламные клики"].value == Decimal("70")


def test_build_traffic_section_keeps_ctr_null_when_impressions_are_zero() -> None:
    current = {
        "impressions": Decimal("0"),
        "card_clicks": Decimal("5"),
        "ctr": None,
        "ad_views": Decimal("10"),
        "ad_clicks": Decimal("1"),
    }
    previous = {
        "impressions": Decimal("10"),
        "card_clicks": Decimal("1"),
        "ctr": Decimal("10"),
        "ad_views": Decimal("8"),
        "ad_clicks": Decimal("1"),
    }
    section = build_traffic_section(current, previous, current, previous)

    assert section is not None
    metrics = {metric.metric: metric for metric in section.metrics}
    assert metrics["CTR общий"].value is None


def test_fetch_mart_daily_overview_sql_uses_weighted_ctr_from_sums() -> None:
    session = _CapturingSession()
    query_counter: dict[str, int] = {}

    fetch_mart_daily_overview(session, date(2026, 7, 15), date(2026, 7, 14), query_counter)

    sql = str(session.statements[0])
    assert "sum(impressions) as impressions" in sql
    assert "sum(card_clicks) as card_clicks" in sql
    assert "sum(card_clicks) / nullif(sum(impressions), 0) * 100 end as ctr" in sql
    assert "avg(ctr)" not in sql


def test_fetch_mart_window_overview_sql_uses_weighted_ctr_from_sums() -> None:
    session = _CapturingSession()
    query_counter: dict[str, int] = {}

    fetch_mart_window_overview(
        session,
        date(2026, 7, 9),
        date(2026, 7, 15),
        date(2026, 7, 2),
        date(2026, 7, 8),
        query_counter,
    )

    sql = str(session.statements[0])
    assert "sum(impressions) as impressions" in sql
    assert "sum(card_clicks) as card_clicks" in sql
    assert "sum(card_clicks) / nullif(sum(impressions), 0) * 100 end as ctr" in sql
    assert "avg(ctr)" not in sql


def test_response_contract_keeps_existing_context_fields() -> None:
    response = _build_response([], WbDailyOperationalHighlightsResponse(), data_gaps=[{"kind": "finance_semantics", "status": "PARTIAL"}])

    payload = response.model_dump()

    assert "article_context" in payload
    assert "warehouse_context" in payload
    assert "campaign_context" in payload
    assert "search_query_context" in payload
    assert "entry_point_context" in payload
    assert "price_context" in payload
    assert "logistics_context" in payload
    assert payload["data_gaps"] == [{"kind": "finance_semantics", "status": "PARTIAL"}]
