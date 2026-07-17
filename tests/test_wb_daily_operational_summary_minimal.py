from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.mcp_server.schemas import (
    WbDailyOperationalDiagnosticsResponse,
    WbDailyOperationalHighlightsResponse,
    WbDailyOperationalReportWindowResponse,
    WbDailyOperationalSectionResponse,
    WbDailyOperationalSourceFreshnessResponse,
    WbDailyOperationalSummaryRequest,
    WbDailyOperationalSummaryResponse,
    WbDailyOperationalTableResponse,
)
import src.mcp_server.wb_daily_operational_summary as summary_module
import src.mcp_server.wb_daily_operational_summary_context_sql as context_sql_module
from src.mcp_server.wb_daily_operational_summary import (
    append_analysis_narratives,
    build_funnel_section,
    build_operational_summary,
    build_priority_section,
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


class _NoopSession:
    pass


def test_build_extended_context_preserves_trend_14d(monkeypatch) -> None:
    trend = [{"report_date": date(2026, 7, 14), "order_sum": Decimal("100")}, {"report_date": date(2026, 7, 15), "order_sum": Decimal("120")}]
    monkeypatch.setattr(context_sql_module, "fetch_additional_source_freshness", lambda session, query_counter: [])
    monkeypatch.setattr(context_sql_module, "fetch_article_context", lambda session, **kwargs: [{
        "nm_id": 101,
        "supplier_article": "ART-101",
        "title": "Title 101",
        "subject": "Subj",
        "brand": "Brand",
        "impressions": Decimal("1000"),
        "card_clicks": Decimal("100"),
        "cart_count": Decimal("20"),
        "order_count": Decimal("10"),
        "order_sum": Decimal("120"),
        "ad_spend_total": Decimal("0"),
        "search_avg_position": Decimal("5"),
        "search_visibility": Decimal("10"),
        "warehouse_stock_qty": Decimal("50"),
        "warehouses_with_stock": 2,
        "warehouses_zero_stock": 0,
        "stock_snapshot_date": date(2026, 7, 15),
        "buyout_count": Decimal("1"),
        "buyout_sum": Decimal("10"),
        "trend_14d": trend,
    }])
    monkeypatch.setattr(context_sql_module, "fetch_price_context", lambda session, **kwargs: [])
    monkeypatch.setattr(context_sql_module, "fetch_logistics_context", lambda session, **kwargs: [])
    monkeypatch.setattr(context_sql_module, "fetch_warehouse_context", lambda session, **kwargs: [])
    monkeypatch.setattr(context_sql_module, "fetch_campaign_context", lambda session, **kwargs: [])
    monkeypatch.setattr(context_sql_module, "fetch_search_query_context", lambda session, **kwargs: [])
    monkeypatch.setattr(context_sql_module, "fetch_entry_point_context", lambda session, **kwargs: {"rows": [], "context_date": date(2026, 7, 15), "status": "OK"})

    result = context_sql_module.build_extended_context(
        _NoopSession(),
        report_date=date(2026, 7, 15),
        compare_date=date(2026, 7, 14),
        trend_current_from=date(2026, 7, 9),
        top_n=5,
        nm_ids=[101],
        query_counter={"count": 0, "timings": []},
    )

    assert result["article_context"][0]["trend_14d"] == trend


def test_build_operational_summary_diagnostic_includes_stage_timings_and_keeps_query_count(monkeypatch) -> None:
    def _inc(query_counter, name, ms=1):
        query_counter["count"] = int(query_counter.get("count") or 0) + 1
        query_counter.setdefault("timings", []).append({"query": name, "ms": ms})

    monkeypatch.setattr(summary_module, "fetch_core_source_freshness", lambda session, query_counter: (_inc(query_counter, "core_source_freshness"), [{"source_name": "mart_total_report", "max_date": date(2026, 7, 15)}])[1])
    monkeypatch.setattr(summary_module, "fetch_mart_daily_overview", lambda session, report_date, compare_date, query_counter: (_inc(query_counter, "mart_daily_overview"), [
        {"report_date": compare_date, "impressions": Decimal("1000"), "card_clicks": Decimal("100"), "ctr": Decimal("10"), "cart_count": Decimal("20"), "add_to_cart_conversion": Decimal("20"), "order_count": Decimal("10"), "cart_to_order_conversion": Decimal("50"), "avg_check": Decimal("1000"), "order_sum": Decimal("10000"), "ad_spend": Decimal("1000"), "ad_views": Decimal("500"), "ad_clicks": Decimal("50"), "ad_atbs": Decimal("10"), "ad_orders": Decimal("5"), "drr": Decimal("10"), "cpc": Decimal("20"), "cpm": Decimal("2000"), "cpo": Decimal("200")},
        {"report_date": report_date, "impressions": Decimal("1200"), "card_clicks": Decimal("120"), "ctr": Decimal("10"), "cart_count": Decimal("24"), "add_to_cart_conversion": Decimal("20"), "order_count": Decimal("12"), "cart_to_order_conversion": Decimal("50"), "avg_check": Decimal("1000"), "order_sum": Decimal("12000"), "ad_spend": Decimal("900"), "ad_views": Decimal("450"), "ad_clicks": Decimal("45"), "ad_atbs": Decimal("9"), "ad_orders": Decimal("4"), "drr": Decimal("8"), "cpc": Decimal("20"), "cpm": Decimal("2000"), "cpo": Decimal("225")},
    ])[1])
    monkeypatch.setattr(summary_module, "fetch_mart_window_overview", lambda session, *args: [_inc(args[-1], "mart_window_overview"), [
        {"bucket": "current", "impressions": Decimal("7000"), "card_clicks": Decimal("700"), "ctr": Decimal("10"), "cart_count": Decimal("140"), "add_to_cart_conversion": Decimal("20"), "order_count": Decimal("70"), "cart_to_order_conversion": Decimal("50"), "avg_check": Decimal("1000"), "order_sum": Decimal("70000"), "ad_spend": Decimal("7000"), "ad_views": Decimal("3500"), "ad_clicks": Decimal("350"), "ad_atbs": Decimal("70"), "ad_orders": Decimal("35"), "drr": Decimal("10"), "cpc": Decimal("20"), "cpm": Decimal("2000"), "cpo": Decimal("200")},
        {"bucket": "previous", "impressions": Decimal("6500"), "card_clicks": Decimal("650"), "ctr": Decimal("10"), "cart_count": Decimal("130"), "add_to_cart_conversion": Decimal("20"), "order_count": Decimal("65"), "cart_to_order_conversion": Decimal("50"), "avg_check": Decimal("1000"), "order_sum": Decimal("65000"), "ad_spend": Decimal("6500"), "ad_views": Decimal("3250"), "ad_clicks": Decimal("325"), "ad_atbs": Decimal("65"), "ad_orders": Decimal("32"), "drr": Decimal("10"), "cpc": Decimal("20"), "cpm": Decimal("2000"), "cpo": Decimal("203")},
    ]][1])
    monkeypatch.setattr(summary_module, "fetch_assortment_changes", lambda session, report_date, compare_date, query_counter: (_inc(query_counter, "assortment_changes"), [])[1])
    monkeypatch.setattr(summary_module, "fetch_problem_campaigns", lambda session, report_date, compare_date, query_counter: (_inc(query_counter, "problem_campaigns"), [])[1])
    monkeypatch.setattr(summary_module, "fetch_stock_risks", lambda session, report_date, trend_current_from, query_counter: (_inc(query_counter, "stock_risks"), [])[1])
    monkeypatch.setattr(summary_module, "fetch_search_movers", lambda session, report_date, compare_date, query_counter: (_inc(query_counter, "search_movers"), [])[1])

    def _fake_build_extended_context(session, **kwargs):
        query_counter = kwargs["query_counter"]
        for query_name in (
            "additional_source_freshness",
            "article_context",
            "price_context_site",
            "price_context_seller_partial",
            "logistics_context",
            "warehouse_context",
            "campaign_context",
            "search_query_context",
            "entry_point_context_freshness",
            "entry_point_context",
        ):
            _inc(query_counter, query_name, 2)
        return {
            "additional_source_freshness": [],
            "article_context": [],
            "warehouse_context": [],
            "campaign_context": [],
            "search_query_context": [],
            "entry_point_context": [],
            "price_context": [],
            "logistics_context": [],
            "data_gaps": [],
        }

    monkeypatch.setattr(summary_module, "build_extended_context", _fake_build_extended_context)

    response = build_operational_summary(
        _NoopSession(),
        WbDailyOperationalSummaryRequest(report_date=date(2026, 7, 15), diagnostic=True, top_n=5),
    )

    stage_names = {item.get("stage") for item in response.diagnostics.query_timings if item.get("stage")}
    assert response.diagnostics.query_count == 17
    assert {
        "core_source_freshness",
        "mart_daily_overview",
        "mart_window_overview",
        "assortment_changes",
        "problem_campaigns",
        "stock_risks",
        "search_movers",
        "article_context",
        "warehouse_context",
        "campaign_context",
        "search_query_context",
        "entry_point_context",
        "price_context",
        "logistics_context",
        "analysis_layer",
        "markdown_formatting",
        "serialization",
        "total",
    }.issubset(stage_names)


def test_append_analysis_narratives_adds_ai_comment_and_action() -> None:
    section = build_traffic_section(
        {
            "impressions": Decimal("1000"),
            "card_clicks": Decimal("100"),
            "ctr": Decimal("10"),
            "ad_views": Decimal("500"),
            "ad_clicks": Decimal("50"),
        },
        {
            "impressions": Decimal("1200"),
            "card_clicks": Decimal("120"),
            "ctr": Decimal("10"),
            "ad_views": Decimal("600"),
            "ad_clicks": Decimal("60"),
        },
        {},
        {},
    )
    assert section is not None

    append_analysis_narratives(
        [section],
        analysis_summary={
            "section_narratives": {
                "traffic": {
                    "comment": "\u0410\u0440\u0442\u0438\u043a\u0443\u043b 37320545 \u0434\u0430\u0451\u0442 \u0437\u0430\u043c\u0435\u0442\u043d\u0443\u044e \u043f\u043e\u0442\u0435\u0440\u044e \u0442\u0440\u0430\u0444\u0438\u043a\u0430.",
                    "action": "\u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u043a\u043b\u0438\u043a\u0438 \u0438 \u0432\u043e\u0440\u043e\u043d\u043a\u0443 \u043f\u043e \u0430\u0440\u0442\u0438\u043a\u0443\u043b\u0443 37320545.",
                }
            }
        },
    )

    assert any(line.startswith("\u041c\u043d\u0435\u043d\u0438\u0435 \u0418\u0418:") for line in section.summary)
    assert any(line.startswith("\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u0435:") for line in section.summary)


def test_build_priority_and_scenario_use_analysis_narratives_without_fallback_duplication() -> None:
    highlights = WbDailyOperationalHighlightsResponse(
        worse=["\u041f\u0430\u0434\u0430\u0435\u0442 \u043e\u0431\u0449\u0438\u0439 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442."],
        better=["\u0410\u0440\u0442\u0438\u043a\u0443\u043b 898169514 \u0434\u0430\u043b \u0440\u043e\u0441\u0442."],
        priority_checks=["\u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0440\u0435\u043a\u043b\u0430\u043c\u0443."],
    )
    analysis_summary = {
        "priority_narratives": [
            {
                "text": "\u0410\u0440\u0442\u0438\u043a\u0443\u043b 37320545 \u0434\u0430\u043b \u043f\u043e\u0442\u0435\u0440\u044e \u043e\u0431\u043e\u0440\u043e\u0442\u0430 -58 715 \u20bd. \u0421\u043d\u0438\u0436\u0435\u043d\u0438\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0435\u0442\u0441\u044f \u043f\u0440\u043e\u0441\u0430\u0434\u043a\u043e\u0439 \u0442\u0440\u0430\u0444\u0438\u043a\u0430. \u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0434\u043e\u043b\u044e \u0442\u0440\u0430\u0444\u0438\u043a\u0430.",
                "action": "\u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0434\u043e\u043b\u044e \u0442\u0440\u0430\u0444\u0438\u043a\u0430.",
            }
        ],
        "scenario_narrative": "\u041f\u043e\u0434 \u0440\u0438\u0441\u043a\u043e\u043c \u0434\u043d\u044f \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f \u0430\u0440\u0442\u0438\u043a\u0443\u043b \u0441 \u043d\u0435\u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0451\u043d\u043d\u043e\u0439 \u043f\u0440\u0438\u0447\u0438\u043d\u043e\u0439; \u0441\u043d\u0430\u0447\u0430\u043b\u0430 \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0442\u0440\u0430\u0444\u0438\u043a \u0430\u0440\u0442\u0438\u043a\u0443\u043b\u0430 37320545.",
    }

    priority = build_priority_section(highlights, analysis_summary)
    scenario = build_scenario_section(highlights, analysis_summary)

    assert priority is not None
    assert priority.summary[0].startswith("\u0410\u0440\u0442\u0438\u043a\u0443\u043b 37320545")
    assert scenario.summary[0] == analysis_summary["scenario_narrative"]
    assert scenario.summary[0] != highlights.worse[0]
    assert priority.summary[0] != highlights.worse[0]


def test_render_markdown_shows_ai_opinion_and_action_after_table() -> None:
    section = WbDailyOperationalSectionResponse(
        key="assortment",
        title="\u0410\u0441\u0441\u043e\u0440\u0442\u0438\u043c\u0435\u043d\u0442",
        status="OK",
        summary=[
            "\u0422\u0430\u0431\u043b\u0438\u0446\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0435\u0442 \u0441\u043f\u0430\u0434.",
            "\u041c\u043d\u0435\u043d\u0438\u0435 \u0418\u0418: \u0430\u0440\u0442\u0438\u043a\u0443\u043b 37320545 \u0434\u0430\u0451\u0442 \u0437\u0430\u043c\u0435\u0442\u043d\u0443\u044e \u043f\u043e\u0442\u0435\u0440\u044e \u0432 \u0430\u0441\u0441\u043e\u0440\u0442\u0438\u043c\u0435\u043d\u0442\u0435.",
            "\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u0435: \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0437\u0430\u043f\u0430\u0441\u044b \u0438 \u0432\u043e\u0440\u043e\u043d\u043a\u0443 \u043f\u043e \u0430\u0440\u0442\u0438\u043a\u0443\u043b\u0443 37320545.",
        ],
        tables=[
            WbDailyOperationalTableResponse(
                title="\u0422\u043e\u043f \u043f\u043e\u0442\u0435\u0440\u044c",
                columns=["\u0410\u0440\u0442\u0438\u043a\u0443\u043b", "\u0412\u043a\u043b\u0430\u0434, \u20bd"],
                rows=[{"\u0410\u0440\u0442\u0438\u043a\u0443\u043b": "37320545", "\u0412\u043a\u043b\u0430\u0434, \u20bd": "-58 715 \u20bd"}],
            )
        ],
    )
    response = _build_response([section], WbDailyOperationalHighlightsResponse())

    markdown = render_wb_daily_operational_summary_markdown(response)

    assert "| \u0410\u0440\u0442\u0438\u043a\u0443\u043b | \u0412\u043a\u043b\u0430\u0434, \u20bd |" in markdown
    assert "\u041c\u043d\u0435\u043d\u0438\u0435 \u0418\u0418: \u0430\u0440\u0442\u0438\u043a\u0443\u043b 37320545 \u0434\u0430\u0451\u0442 \u0437\u0430\u043c\u0435\u0442\u043d\u0443\u044e \u043f\u043e\u0442\u0435\u0440\u044e \u0432 \u0430\u0441\u0441\u043e\u0440\u0442\u0438\u043c\u0435\u043d\u0442\u0435." in markdown
    assert "\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u0435: \u043f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c \u0437\u0430\u043f\u0430\u0441\u044b \u0438 \u0432\u043e\u0440\u043e\u043d\u043a\u0443 \u043f\u043e \u0430\u0440\u0442\u0438\u043a\u0443\u043b\u0443 37320545." in markdown
    assert markdown.index("| \u0410\u0440\u0442\u0438\u043a\u0443\u043b | \u0412\u043a\u043b\u0430\u0434, \u20bd |") < markdown.index("\u041c\u043d\u0435\u043d\u0438\u0435 \u0418\u0418:")
