from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.mcp_server.schemas import (
    WbDailyOperationalDiagnosticsResponse,
    WbDailyOperationalHighlightsResponse,
    WbDailyOperationalMetricRowResponse,
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
    assert "sum(coalesce(impressions, entry_impressions_total)) as impressions" in sql
    assert "sum(coalesce(card_clicks, entry_card_clicks_total)) as card_clicks" in sql
    assert "sum(coalesce(card_clicks, entry_card_clicks_total)) / nullif(sum(coalesce(impressions, entry_impressions_total)), 0) * 100 end as ctr" in sql
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
    assert "sum(coalesce(impressions, entry_impressions_total)) as impressions" in sql
    assert "sum(coalesce(card_clicks, entry_card_clicks_total)) as card_clicks" in sql
    assert "sum(coalesce(card_clicks, entry_card_clicks_total)) / nullif(sum(coalesce(impressions, entry_impressions_total)), 0) * 100 end as ctr" in sql
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
    assert "database_audit" in payload
    assert "operating_profit_context" in payload
    assert "logistics_summary" in payload
    assert "pricing_spp_context" in payload
    assert "competitor_context" in payload
    assert "additional_data_candidates" in payload
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
    monkeypatch.setattr(summary_module, "fetch_database_audit_block", lambda session, *, query_counter: (_inc(query_counter, "database_audit_vvbromo"), {"status": "OK", "inventory": []})[1])
    monkeypatch.setattr(summary_module, "fetch_operating_profit_block", lambda session, **kwargs: (_inc(kwargs["query_counter"], "operating_profit_daily"), {"status": "OK", "overall": {}})[1])
    monkeypatch.setattr(summary_module, "fetch_logistics_summary_block", lambda session, **kwargs: (_inc(kwargs["query_counter"], "logistics_summary_daily"), {"status": "PARTIAL", "overall": {}})[1])
    monkeypatch.setattr(summary_module, "fetch_pricing_spp_block", lambda session, **kwargs: (_inc(kwargs["query_counter"], "pricing_spp_rows"), {"status": "OK", "top_price_changes": []})[1])
    monkeypatch.setattr(summary_module, "fetch_competitor_block", lambda session, **kwargs: (_inc(kwargs["query_counter"], "competitor_snapshot_meta"), {"status": "PARTIAL", "items": []})[1])
    monkeypatch.setattr(summary_module, "build_additional_data_candidates", lambda **kwargs: [{"candidate_key": "wb_site_price_alerts"}])

    response = build_operational_summary(
        _NoopSession(),
        WbDailyOperationalSummaryRequest(report_date=date(2026, 7, 15), diagnostic=True, top_n=5),
    )

    stage_names = {item.get("stage") for item in response.diagnostics.query_timings if item.get("stage")}
    assert response.diagnostics.query_count == 22
    assert {
        "core_source_freshness",
        "mart_daily_overview",
        "mart_window_overview",
        "assortment_changes",
        "problem_campaigns",
        "stock_risks",
        "search_movers",
        "database_audit",
        "operating_profit_context",
        "logistics_summary",
        "pricing_spp_context",
        "competitor_context",
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


def test_build_operational_summary_returns_unavailable_additional_block_when_helper_fails(monkeypatch) -> None:
    def _inc(query_counter, name, ms=1):
        query_counter["count"] = int(query_counter.get("count") or 0) + 1
        query_counter.setdefault("timings", []).append({"query": name, "ms": ms})

    monkeypatch.setattr(summary_module, "fetch_core_source_freshness", lambda session, query_counter: (_inc(query_counter, "core_source_freshness"), [{"source_name": "mart_total_report", "max_date": date(2026, 7, 15)}])[1])
    monkeypatch.setattr(summary_module, "fetch_mart_daily_overview", lambda session, report_date, compare_date, query_counter: (_inc(query_counter, "mart_daily_overview"), [{"report_date": compare_date}, {"report_date": report_date}])[1])
    monkeypatch.setattr(summary_module, "fetch_mart_window_overview", lambda session, *args: [_inc(args[-1], "mart_window_overview"), [{"bucket": "current"}, {"bucket": "previous"}]][1])
    monkeypatch.setattr(summary_module, "fetch_assortment_changes", lambda session, report_date, compare_date, query_counter: (_inc(query_counter, "assortment_changes"), [])[1])
    monkeypatch.setattr(summary_module, "fetch_problem_campaigns", lambda session, report_date, compare_date, query_counter: (_inc(query_counter, "problem_campaigns"), [])[1])
    monkeypatch.setattr(summary_module, "fetch_stock_risks", lambda session, report_date, trend_current_from, query_counter: (_inc(query_counter, "stock_risks"), [])[1])
    monkeypatch.setattr(summary_module, "fetch_search_movers", lambda session, report_date, compare_date, query_counter: (_inc(query_counter, "search_movers"), [])[1])
    monkeypatch.setattr(summary_module, "build_extended_context", lambda session, **kwargs: {"additional_source_freshness": [], "article_context": [], "warehouse_context": [], "campaign_context": [], "search_query_context": [], "entry_point_context": [], "price_context": [], "logistics_context": [], "data_gaps": []})
    monkeypatch.setattr(summary_module, "fetch_database_audit_block", lambda session, *, query_counter: (_inc(query_counter, "database_audit_vvbromo"), {"status": "OK", "inventory": []})[1])
    monkeypatch.setattr(summary_module, "fetch_operating_profit_block", lambda session, **kwargs: (_ for _ in ()).throw(RuntimeError("missing profit source")))
    monkeypatch.setattr(summary_module, "fetch_logistics_summary_block", lambda session, **kwargs: {"status": "PARTIAL"})
    monkeypatch.setattr(summary_module, "fetch_pricing_spp_block", lambda session, **kwargs: {"status": "OK"})
    monkeypatch.setattr(summary_module, "fetch_competitor_block", lambda session, **kwargs: {"status": "MISSING"})
    monkeypatch.setattr(summary_module, "build_additional_data_candidates", lambda **kwargs: [])

    response = build_operational_summary(_NoopSession(), WbDailyOperationalSummaryRequest(report_date=date(2026, 7, 15), top_n=5))

    assert response.operating_profit_context["status"] == "UNAVAILABLE"
    assert response.operating_profit_context["source_table"] == "fact_vvbromo_product_day"
    assert response.operating_profit_context["diagnostic"]["error_type"] == "RuntimeError"


def test_build_operational_summary_keeps_report_when_fetch_profit_overview_fails(monkeypatch) -> None:
    monkeypatch.setattr(summary_module, "fetch_core_source_freshness", lambda session, query_counter: [{"source_name": "mart_total_report", "max_date": date(2026, 7, 15)}])
    monkeypatch.setattr(summary_module, "fetch_mart_daily_overview", lambda session, report_date, compare_date, query_counter: [{"report_date": compare_date}, {"report_date": report_date}])
    monkeypatch.setattr(summary_module, "fetch_mart_window_overview", lambda session, *args: [{"bucket": "current"}, {"bucket": "previous"}])
    monkeypatch.setattr(summary_module, "fetch_assortment_changes", lambda session, report_date, compare_date, query_counter: [])
    monkeypatch.setattr(summary_module, "fetch_problem_campaigns", lambda session, report_date, compare_date, query_counter: [])
    monkeypatch.setattr(summary_module, "fetch_stock_risks", lambda session, report_date, trend_current_from, query_counter: [])
    monkeypatch.setattr(summary_module, "fetch_search_movers", lambda session, report_date, compare_date, query_counter: [])
    monkeypatch.setattr(summary_module, "build_extended_context", lambda session, **kwargs: {"additional_source_freshness": [], "article_context": [], "warehouse_context": [], "campaign_context": [], "search_query_context": [], "entry_point_context": [], "price_context": [], "logistics_context": [], "data_gaps": []})
    monkeypatch.setattr(summary_module, "fetch_database_audit_block", lambda session, *, query_counter: {"status": "OK", "inventory": []})
    monkeypatch.setattr(summary_module, "fetch_operating_profit_block", lambda session, **kwargs: {"status": "MISSING"})
    monkeypatch.setattr(summary_module, "fetch_logistics_summary_block", lambda session, **kwargs: {"status": "PARTIAL"})
    monkeypatch.setattr(summary_module, "fetch_pricing_spp_block", lambda session, **kwargs: {"status": "OK"})
    monkeypatch.setattr(summary_module, "fetch_competitor_block", lambda session, **kwargs: {"status": "MISSING"})
    monkeypatch.setattr(summary_module, "build_additional_data_candidates", lambda **kwargs: [])
    monkeypatch.setattr(summary_module, "fetch_profit_overview", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("missing organic_sales field")))

    response = build_operational_summary(
        _NoopSession(),
        WbDailyOperationalSummaryRequest(report_date=date(2026, 7, 15), include_profit=True, include_partial_sections=True, top_n=5),
    )

    excluded_profit = next(item for item in response.diagnostics.excluded_sections if item.key == "profit")
    assert "временно недоступен" in excluded_profit.reason
    assert all(section.key != "profit" for section in response.sections)


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






def _build_compact_markdown_response() -> WbDailyOperationalSummaryResponse:
    report_date = date(2026, 7, 17)
    compare_date = date(2026, 7, 16)
    current = {
        "impressions": Decimal("125000"),
        "card_clicks": Decimal("12500"),
        "ctr": Decimal("10.0"),
        "ad_views": Decimal("210000"),
        "ad_clicks": Decimal("6400"),
        "cart_count": Decimal("2310"),
        "add_to_cart_conversion": Decimal("18.5"),
        "order_count": Decimal("968"),
        "cart_to_order_conversion": Decimal("41.9"),
        "avg_check": Decimal("1420"),
        "order_sum": Decimal("1375013"),
        "ad_spend": Decimal("5047911.06"),
        "ad_writeoff_total": Decimal("5047911.06"),
        "ad_campaign_spend_total": Decimal("5047911.06"),
        "ad_revenue_total": Decimal("22945050"),
        "cpc": Decimal("31.4"),
        "cpm": Decimal("210"),
        "cpo": Decimal("152.38"),
        "cost_per_cart": Decimal("66"),
        "ad_atbs": Decimal("2310"),
        "ad_orders": Decimal("529"),
        "search_avg_position": Decimal("48.4"),
        "search_visibility": Decimal("12.5"),
        "search_clicks": Decimal("5800"),
        "search_cart": Decimal("920"),
        "search_orders": Decimal("410"),
    }
    previous = {
        "impressions": Decimal("120000"),
        "card_clicks": Decimal("12050"),
        "ctr": Decimal("10.04"),
        "ad_views": Decimal("208000"),
        "ad_clicks": Decimal("6350"),
        "cart_count": Decimal("2280"),
        "add_to_cart_conversion": Decimal("17.9"),
        "order_count": Decimal("1012"),
        "cart_to_order_conversion": Decimal("42.1"),
        "avg_check": Decimal("1390"),
        "order_sum": Decimal("1433728"),
        "ad_spend": Decimal("4927911.06"),
        "ad_writeoff_total": Decimal("4927911.06"),
        "ad_campaign_spend_total": Decimal("4927911.06"),
        "ad_revenue_total": Decimal("24639555.30"),
        "cpc": Decimal("31.8"),
        "cpm": Decimal("212"),
        "cpo": Decimal("152.78"),
        "cost_per_cart": Decimal("59"),
        "ad_atbs": Decimal("2280"),
        "ad_orders": Decimal("534"),
        "search_avg_position": Decimal("46.3"),
        "search_visibility": Decimal("11.4"),
        "search_clicks": Decimal("6000"),
        "search_cart": Decimal("950"),
        "search_orders": Decimal("430"),
    }
    current_7d = {
        "impressions": Decimal("840000"),
        "card_clicks": Decimal("84000"),
        "ctr": Decimal("10.0"),
        "ad_views": Decimal("1470000"),
        "ad_clicks": Decimal("44800"),
        "cart_count": Decimal("16170"),
        "add_to_cart_conversion": Decimal("19.0"),
        "order_count": Decimal("6776"),
        "cart_to_order_conversion": Decimal("41.9"),
        "avg_check": Decimal("1418"),
        "order_sum": Decimal("9625091"),
        "ad_spend": Decimal("35335373"),
        "ad_writeoff_total": Decimal("35335373"),
        "ad_campaign_spend_total": Decimal("35335373"),
        "ad_revenue_total": Decimal("160615331.82"),
        "cpc": Decimal("31.5"),
        "cpm": Decimal("211"),
        "cpo": Decimal("152.0"),
        "cost_per_cart": Decimal("64.7"),
        "ad_atbs": Decimal("54600"),
        "ad_orders": Decimal("2321"),
        "search_avg_position": Decimal("47.1"),
        "search_visibility": Decimal("12.7"),
        "search_clicks": Decimal("40100"),
        "search_cart": Decimal("6500"),
        "search_orders": Decimal("2840"),
    }
    previous_7d = {
        "impressions": Decimal("792000"),
        "card_clicks": Decimal("81100"),
        "ctr": Decimal("9.98"),
        "ad_views": Decimal("1430000"),
        "ad_clicks": Decimal("44100"),
        "cart_count": Decimal("15550"),
        "add_to_cart_conversion": Decimal("18.7"),
        "order_count": Decimal("6620"),
        "cart_to_order_conversion": Decimal("41.4"),
        "avg_check": Decimal("1393"),
        "order_sum": Decimal("9320180"),
        "ad_spend": Decimal("33813000"),
        "ad_writeoff_total": Decimal("33813000"),
        "ad_campaign_spend_total": Decimal("33813000"),
        "ad_revenue_total": Decimal("169065000"),
        "cpc": Decimal("31.25"),
        "cpm": Decimal("208.7"),
        "cpo": Decimal("149.5"),
        "cost_per_cart": Decimal("63.4"),
        "ad_atbs": Decimal("53300"),
        "ad_orders": Decimal("2262"),
        "search_avg_position": Decimal("46.1"),
        "search_visibility": Decimal("12.3"),
        "search_clicks": Decimal("39280"),
        "search_cart": Decimal("6420"),
        "search_orders": Decimal("2812"),
    }
    rules = summary_module.get_default_rules()
    sections = [
        summary_module.build_overview_section(current, previous, current_7d, previous_7d),
        build_traffic_section(current, previous, current_7d, previous_7d),
        build_funnel_section(current, previous, current_7d, previous_7d),
        build_sales_section(current, previous, current_7d, previous_7d),
        summary_module.build_ads_section(
            current,
            previous,
            current_7d,
            previous_7d,
            campaign_rows=[
                {"campaign_name": "Campaign A", "advert_id": 101, "row_type": "auction", "spend_current": Decimal("250000"), "spend_previous": Decimal("210000"), "orders_current": Decimal("0"), "orders_previous": Decimal("2"), "revenue_current": Decimal("0")},
                {"campaign_name": "Campaign B", "advert_id": 102, "row_type": "search", "spend_current": Decimal("500000"), "spend_previous": Decimal("460000"), "orders_current": Decimal("25"), "orders_previous": Decimal("29"), "revenue_current": Decimal("1612903")},
                {"campaign_name": "Campaign C", "advert_id": 103, "row_type": "catalog", "spend_current": Decimal("120000"), "spend_previous": Decimal("90000"), "orders_current": Decimal("11"), "orders_previous": Decimal("11"), "revenue_current": Decimal("666667")},
                {"campaign_name": "Campaign D", "advert_id": 104, "row_type": "catalog", "spend_current": Decimal("50000"), "spend_previous": Decimal("40000"), "orders_current": Decimal("8"), "orders_previous": Decimal("8"), "revenue_current": Decimal("333333")},
            ],
            top_n=4,
            rules=rules,
        ),
        summary_module.build_profit_section(
            {
                "daily": [
                    {"day": compare_date, "operating_profit": Decimal("16000"), "profit_per_unit": Decimal("44.0")},
                    {"day": report_date, "operating_profit": Decimal("17826"), "profit_per_unit": Decimal("47.3")},
                ],
                "trend": [
                    {"bucket": "current", "operating_profit": Decimal("124782"), "profit_per_unit": Decimal("46.4")},
                    {"bucket": "previous", "operating_profit": Decimal("121000"), "profit_per_unit": Decimal("45.5")},
                ],
                "max_day": report_date,
            },
            report_date,
            compare_date,
        ),
        summary_module.build_assortment_section(
            assortment_rows=[
                {"nm_id": 577510563, "supplier_article": "GROW-1", "title": "Growth 1", "order_sum_current": Decimal("210000"), "order_sum_previous": Decimal("165660"), "order_sum_delta": Decimal("44340"), "order_count_current": Decimal("120"), "ad_spend_current": Decimal("10000"), "current_stock_qty": Decimal("85")},
                {"nm_id": 577510564, "supplier_article": "GROW-2", "title": "Growth 2", "order_sum_current": Decimal("180000"), "order_sum_previous": Decimal("154820"), "order_sum_delta": Decimal("25180"), "order_count_current": Decimal("95"), "ad_spend_current": Decimal("9500"), "current_stock_qty": Decimal("44")},
                {"nm_id": 577510565, "supplier_article": "GROW-3", "title": "Growth 3", "order_sum_current": Decimal("170000"), "order_sum_previous": Decimal("150800"), "order_sum_delta": Decimal("19200"), "order_count_current": Decimal("90"), "ad_spend_current": Decimal("8100"), "current_stock_qty": Decimal("33")},
                {"nm_id": 577510566, "supplier_article": "GROW-4", "title": "Growth 4", "order_sum_current": Decimal("160000"), "order_sum_previous": Decimal("155000"), "order_sum_delta": Decimal("5000"), "order_count_current": Decimal("70"), "ad_spend_current": Decimal("7100"), "current_stock_qty": Decimal("22")},
                {"nm_id": 37320545, "supplier_article": "DROP-1", "title": "Drop 1", "order_sum_current": Decimal("155000"), "order_sum_previous": Decimal("213715"), "order_sum_delta": Decimal("-58715"), "order_count_current": Decimal("88"), "ad_spend_current": Decimal("12000"), "current_stock_qty": Decimal("9")},
                {"nm_id": 221311710, "supplier_article": "DROP-2", "title": "Drop 2", "order_sum_current": Decimal("130000"), "order_sum_previous": Decimal("174340"), "order_sum_delta": Decimal("-44340"), "order_count_current": Decimal("74"), "ad_spend_current": Decimal("11000"), "current_stock_qty": Decimal("6")},
                {"nm_id": 335760311, "supplier_article": "DROP-3", "title": "Drop 3", "order_sum_current": Decimal("120000"), "order_sum_previous": Decimal("145180"), "order_sum_delta": Decimal("-25180"), "order_count_current": Decimal("61"), "ad_spend_current": Decimal("10500"), "current_stock_qty": Decimal("4")},
                {"nm_id": 335760399, "supplier_article": "DROP-4", "title": "Drop 4", "order_sum_current": Decimal("119000"), "order_sum_previous": Decimal("127000"), "order_sum_delta": Decimal("-8000"), "order_count_current": Decimal("58"), "ad_spend_current": Decimal("9800"), "current_stock_qty": Decimal("3")},
            ],
            top_n=4,
        ),
        summary_module.build_search_section(
            current,
            previous,
            current_7d,
            previous_7d,
            search_rows=[
                {"nm_id": 1001, "supplier_article": "S-UP-1", "title": "Search Up 1", "avg_position_current": Decimal("12.0"), "avg_position_previous": Decimal("37.1"), "visibility_current": Decimal("9.0"), "search_clicks_current": Decimal("110"), "search_orders_current": Decimal("15")},
                {"nm_id": 1002, "supplier_article": "S-UP-2", "title": "Search Up 2", "avg_position_current": Decimal("18.0"), "avg_position_previous": Decimal("39.0"), "visibility_current": Decimal("8.2"), "search_clicks_current": Decimal("105"), "search_orders_current": Decimal("14")},
                {"nm_id": 1003, "supplier_article": "S-UP-3", "title": "Search Up 3", "avg_position_current": Decimal("21.0"), "avg_position_previous": Decimal("40.0"), "visibility_current": Decimal("7.8"), "search_clicks_current": Decimal("101"), "search_orders_current": Decimal("12")},
                {"nm_id": 1004, "supplier_article": "S-UP-4", "title": "Search Up 4", "avg_position_current": Decimal("22.0"), "avg_position_previous": Decimal("39.0"), "visibility_current": Decimal("7.1"), "search_clicks_current": Decimal("99"), "search_orders_current": Decimal("11")},
                {"nm_id": 0, "supplier_article": "S-UP-0", "title": "Zero Pos", "avg_position_current": Decimal("0.0"), "avg_position_previous": Decimal("25.0"), "visibility_current": Decimal("0.0"), "search_clicks_current": Decimal("0"), "search_orders_current": Decimal("0")},
                {"nm_id": 2001, "supplier_article": "S-DN-1", "title": "Search Down 1", "avg_position_current": Decimal("78.7"), "avg_position_previous": Decimal("44.0"), "visibility_current": Decimal("5.0"), "search_clicks_current": Decimal("75"), "search_orders_current": Decimal("8")},
                {"nm_id": 2002, "supplier_article": "S-DN-2", "title": "Search Down 2", "avg_position_current": Decimal("73.0"), "avg_position_previous": Decimal("42.0"), "visibility_current": Decimal("4.8"), "search_clicks_current": Decimal("71"), "search_orders_current": Decimal("7")},
                {"nm_id": 2003, "supplier_article": "S-DN-3", "title": "Search Down 3", "avg_position_current": Decimal("69.0"), "avg_position_previous": Decimal("40.0"), "visibility_current": Decimal("4.5"), "search_clicks_current": Decimal("66"), "search_orders_current": Decimal("6")},
                {"nm_id": 2004, "supplier_article": "S-DN-4", "title": "Search Down 4", "avg_position_current": Decimal("65.0"), "avg_position_previous": Decimal("39.0"), "visibility_current": Decimal("4.2"), "search_clicks_current": Decimal("61"), "search_orders_current": Decimal("5")},
            ],
            top_n=4,
            rules=rules,
        ),
    ]
    sections = [section for section in sections if section is not None]
    response = _build_response(
        sections,
        WbDailyOperationalHighlightsResponse(
            worse=["Есть потеря по артикулу 37320545."],
            better=["Есть рост по артикулу 577510563."],
            priority_checks=[
                "Проверить причины снижения 37320545.",
                "Проверить остатки 221311710.",
                "Проверить рекламу по кампании 101.",
            ],
        ),
    )
    return response.model_copy(update={
        "report_window": WbDailyOperationalReportWindowResponse(
            report_date=report_date,
            compare_date=compare_date,
            trend_current_from=date(2026, 7, 11),
            trend_current_to=report_date,
            trend_previous_from=date(2026, 7, 4),
            trend_previous_to=date(2026, 7, 10),
            report_date_source="requested",
        ),
        "requested_options": {"mode": "full", "diagnostic": False, "top_n": 5},
        "article_analysis": [
            {"nm_id": 37320545, "title": "Drop 1", "stock": {"stock_qty_same_day": Decimal("9"), "warehouses_with_stock": 2, "warehouses_zero_stock": 3, "warehouse_rows": [{"total_stock_qty": Decimal("9"), "avg_orders_7d_article": Decimal("4.5")}]}, "funnel": {"order_count_baseline": {"avg_prev_7": Decimal("4.5")}}},
            {"nm_id": 221311710, "title": "Drop 2", "stock": {"stock_qty_same_day": Decimal("6"), "warehouses_with_stock": 1, "warehouses_zero_stock": 4, "warehouse_rows": [{"total_stock_qty": Decimal("6"), "avg_orders_7d_article": Decimal("3.0")}]}, "funnel": {"order_count_baseline": {"avg_prev_7": Decimal("3.0")}}},
            {"nm_id": 335760311, "title": "Drop 3", "stock": {"stock_qty_same_day": Decimal("4"), "warehouses_with_stock": 1, "warehouses_zero_stock": 5, "warehouse_rows": [{"total_stock_qty": Decimal("4"), "avg_orders_7d_article": Decimal("2.0")}]}, "funnel": {"order_count_baseline": {"avg_prev_7": Decimal("2.0")}}},
            {"nm_id": 577510563, "title": "Growth 1", "stock": {"stock_qty_same_day": Decimal("85"), "warehouses_with_stock": 5, "warehouses_zero_stock": 0, "warehouse_rows": [{"total_stock_qty": Decimal("85"), "avg_orders_7d_article": Decimal("12.0")}]}, "funnel": {"order_count_baseline": {"avg_prev_7": Decimal("12.0")}}},
        ],
        "business_priorities": [
            {"entity_type": "product", "entity_id": 37320545, "nm_id": 37320545, "kind": "large_turnover_loss", "direction": "negative", "impact_rub": Decimal("-58715"), "recommended_check": "Проверить причины снижения 37320545", "cause_status": "confirmed", "supporting_signals": [{"kind": "traffic"}], "supported_factors": ["traffic"], "user_visible": True},
            {"entity_type": "product", "entity_id": 221311710, "nm_id": 221311710, "kind": "stock", "direction": "negative", "impact_rub": Decimal("-44340"), "recommended_check": "Проверить остатки 221311710", "cause_status": "confirmed", "supporting_signals": [{"kind": "stock"}], "supported_factors": ["stock"], "user_visible": True},
            {"entity_type": "campaign", "entity_id": 101, "advert_id": 101, "kind": "ads", "direction": "negative", "impact_rub": Decimal("-25000"), "recommended_check": "Проверить рекламу по кампании 101", "cause_status": "confirmed", "supporting_signals": [{"kind": "ads", "advert_id": 101}], "supported_factors": ["ads"], "user_visible": True},
            {"entity_type": "product", "entity_id": 577510563, "nm_id": 577510563, "kind": "large_turnover_growth", "direction": "positive", "impact_rub": Decimal("44340"), "recommended_check": "Подтвердить рост по артикулу 577510563", "cause_status": "confirmed", "supporting_signals": [{"kind": "traffic"}], "supported_factors": ["traffic"], "user_visible": True},
        ],
        "analysis_summary": {
            "priority_narratives": [
                {"entity_type": "product", "entity_id": 37320545, "nm_id": 37320545, "action": "Проверить причины снижения 37320545"},
                {"entity_type": "product", "entity_id": 221311710, "nm_id": 221311710, "action": "Проверить остатки 221311710"},
                {"entity_type": "campaign", "entity_id": 101, "advert_id": 101, "action": "Проверить рекламу по кампании 101"},
                {"entity_type": "product", "entity_id": 577510563, "nm_id": 577510563, "action": "Подтвердить рост по артикулу 577510563"},
            ],
            "top_anomalies": [{"summary": "Статус seller price требует осторожной интерпретации."}],
        },
    })


def _legacy_like_markdown(response: WbDailyOperationalSummaryResponse) -> str:
    def metric_row(metric: WbDailyOperationalMetricRowResponse) -> list[str]:
        return [
            metric.metric,
            str(metric.value),
            str(metric.delta_abs if metric.delta_abs is not None else metric.delta_pct if metric.delta_pct is not None else metric.delta_pp),
            str(metric.trend_7d_pct if metric.trend_7d_pct is not None else metric.trend_7d_pp),
            str(metric.previous_value),
        ]

    lines = [
        "# LEGACY REPORT",
        f"???? ??????: {response.report_window.report_date.isoformat()}",
        f"?????????: {response.report_window.report_date.isoformat()} ?????? {response.report_window.compare_date.isoformat()}",
        "## ??? ??????????",
        *[f"- {item}" for item in response.highlights.worse],
        "## ??? ???????",
        *[f"- {item}" for item in response.highlights.better],
    ]
    for section in response.sections:
        lines.append(f"## {section.title}")
        if section.metrics:
            lines.append("| ?????????? | ???????? | ???. ?? ????? | ????? 7 ???? | ????. ???? |")
            lines.append("| --- | --- | --- | --- | --- |")
            for row in section.metrics:
                lines.append("| " + " | ".join(metric_row(row)) + " |")
        for table in section.tables:
            lines.append(f"**{table.title}**")
            lines.append("| " + " | ".join(table.columns) + " |")
            lines.append("| " + " | ".join(["---"] * len(table.columns)) + " |")
            for table_row in table.rows:
                lines.append("| " + " | ".join(str(table_row.get(column, "")) for column in table.columns) + " |")
        for summary_line in section.summary[:3]:
            lines.append(f"- {summary_line}")
        lines.append("")
    lines.append("## ???????????? ????????")
    lines.extend(f"- {item}" for item in response.highlights.priority_checks)
    lines.append("## ????????? ????")
    lines.append("- ????????? fallback ?? ???????????.")
    return "\n".join(lines)

def test_render_markdown_compact_structure_and_limits() -> None:
    response = _build_compact_markdown_response()
    markdown = render_wb_daily_operational_summary_markdown(response)

    for heading in ("Мнение ИИ", "Сценарный итог", "Приоритетные проверки", "Что ухудшилось", "Что выросло"):
        assert heading not in markdown
    assert markdown.count("## Действия на день") == 1
    assert sum(1 for line in markdown.splitlines() if line.startswith(("1. ", "2. ", "3. ", "4. "))) == 3
    assert "577510566" not in markdown
    assert "335760399" not in markdown
    assert "Campaign D" not in markdown
    assert "1004" not in markdown
    assert "2004" not in markdown
    assert "0000" not in markdown
    assert "-25,1 позиции — улучшение" in markdown
    assert "+34,7 позиции — ухудшение" in markdown
    assert "## Операционная прибыль по VVBromo" in markdown


def test_render_markdown_formats_currency_pp_and_normalizes_negative_zero() -> None:
    response = _build_compact_markdown_response()
    markdown = render_wb_daily_operational_summary_markdown(response)

    assert "22,0%" in markdown
    assert "+2,0 п.п." in markdown
    assert "66 ₽" in markdown
    assert "0 ₽" in markdown
    for bad in ("-0 ₽", "−0 ₽", "-0,0%", "−0,0%", "-0,0 п.п.", "−0,0 п.п."):
        assert bad not in markdown


def test_render_markdown_2026_07_17_is_shorter_than_legacy_without_losing_core_sections() -> None:
    response = _build_compact_markdown_response()
    compact = render_wb_daily_operational_summary_markdown(response)
    legacy = _legacy_like_markdown(response)

    assert response.report_window.report_date == date(2026, 7, 17)
    assert len(compact) <= len(legacy) * 0.7
    assert "Период 7 дней" in compact
    assert "К предыдущим 7 дням" in compact
    assert "## Операционная прибыль по VVBromo" in compact
    assert "## Действия на день" in compact


def test_total_impressions_equals_sum_of_row_impressions() -> None:
    current = {"impressions": Decimal("5000"), "card_clicks": Decimal("250"), "ctr": Decimal("5.0")}
    previous = {"impressions": Decimal("4000"), "card_clicks": Decimal("160"), "ctr": Decimal("4.0")}
    current_7d = {"impressions": Decimal("35000"), "card_clicks": Decimal("1750"), "ctr": Decimal("5.0")}
    previous_7d = {"impressions": Decimal("30000"), "card_clicks": Decimal("1200"), "ctr": Decimal("4.0")}

    section = build_traffic_section(current, previous, current_7d, previous_7d)
    assert section is not None
    impressions_row = next(m for m in section.metrics if m.metric == "Общие показы")
    assert impressions_row.value == Decimal("5000")
    assert impressions_row.previous_value == Decimal("4000")


def test_total_clicks_equals_sum_of_row_clicks() -> None:
    current = {"impressions": Decimal("5000"), "card_clicks": Decimal("250"), "ctr": Decimal("5.0")}
    previous = {"impressions": Decimal("4000"), "card_clicks": Decimal("160"), "ctr": Decimal("4.0")}
    current_7d = {"impressions": Decimal("35000"), "card_clicks": Decimal("1750"), "ctr": Decimal("5.0")}
    previous_7d = {"impressions": Decimal("30000"), "card_clicks": Decimal("1200"), "ctr": Decimal("4.0")}

    section = build_traffic_section(current, previous, current_7d, previous_7d)
    assert section is not None
    clicks_row = next(m for m in section.metrics if m.metric == "Общие клики")
    assert clicks_row.value == Decimal("250")
    assert clicks_row.previous_value == Decimal("160")


def test_ctr_calculated_from_total_sums() -> None:
    # Article A: 10,000 impressions, 1,000 clicks (CTR 10%)
    # Article B: 100 impressions, 1 click (CTR 1%)
    # Total impressions = 10,100, Total clicks = 1,001 -> Correct Total CTR = 1,001 / 10,100 * 100 = 9.91089%
    row_a_imp, row_a_clicks = Decimal("10000"), Decimal("1000")
    row_b_imp, row_b_clicks = Decimal("100"), Decimal("1")
    total_imp = row_a_imp + row_b_imp
    total_clicks = row_a_clicks + row_b_clicks
    total_ctr = (total_clicks / total_imp * Decimal("100")) if total_imp > 0 else None

    assert total_ctr is not None
    assert round(float(total_ctr), 4) == 9.9109

    current = {"impressions": total_imp, "card_clicks": total_clicks, "ctr": total_ctr}
    previous = {"impressions": Decimal("10000"), "card_clicks": Decimal("800"), "ctr": Decimal("8.0")}
    current_7d = {"impressions": total_imp * 7, "card_clicks": total_clicks * 7, "ctr": total_ctr}
    previous_7d = {"impressions": Decimal("70000"), "card_clicks": Decimal("5600"), "ctr": Decimal("8.0")}

    section = build_traffic_section(current, previous, current_7d, previous_7d)
    assert section is not None
    ctr_row = next(m for m in section.metrics if m.metric == "CTR общий")
    assert ctr_row.value == total_ctr


def test_ctr_not_equal_simple_average_of_article_ctrs() -> None:
    # Article A: 10,000 impressions, 1,000 clicks (CTR 10.0%)
    # Article B: 100 impressions, 1 click (CTR 1.0%)
    # Simple average CTR = (10.0 + 1.0) / 2 = 5.5%
    # Weighted Total CTR = (1000 + 1) / (10000 + 100) * 100 = 9.91089%
    simple_average_ctr = Decimal("5.5")
    total_imp = Decimal("10100")
    total_clicks = Decimal("1001")
    total_ctr = total_clicks / total_imp * Decimal("100")

    assert total_ctr != simple_average_ctr
    assert abs(total_ctr - simple_average_ctr) > Decimal("4.0")


def test_zero_or_null_impressions_yields_null_ctr() -> None:
    current = {"impressions": Decimal("0"), "card_clicks": Decimal("0"), "ctr": None}
    previous = {"impressions": None, "card_clicks": None, "ctr": None}
    current_7d = {"impressions": Decimal("0"), "card_clicks": Decimal("0"), "ctr": None}
    previous_7d = {"impressions": None, "card_clicks": None, "ctr": None}

    section = build_traffic_section(current, previous, current_7d, previous_7d)
    assert section is not None
    ctr_row = next(m for m in section.metrics if m.metric == "CTR общий")
    assert ctr_row.value is None

    markdown = render_wb_daily_operational_summary_markdown(_build_response([section], WbDailyOperationalHighlightsResponse()))
    assert "| CTR общий | н/д | н/д | н/д |" in markdown


def test_ctr_daily_and_weekly_deltas_expressed_in_percentage_points() -> None:
    current = {"impressions": Decimal("1000"), "card_clicks": Decimal("100"), "ctr": Decimal("10.0")}
    previous = {"impressions": Decimal("1000"), "card_clicks": Decimal("80"), "ctr": Decimal("8.0")}
    current_7d = {"impressions": Decimal("7000"), "card_clicks": Decimal("700"), "ctr": Decimal("10.0")}
    previous_7d = {"impressions": Decimal("7000"), "card_clicks": Decimal("420"), "ctr": Decimal("6.0")}

    section = build_traffic_section(current, previous, current_7d, previous_7d)
    assert section is not None
    ctr_row = next(m for m in section.metrics if m.metric == "CTR общий")
    assert ctr_row.delta_pp == Decimal("2.0")
    assert ctr_row.delta_pct is None
    assert ctr_row.trend_7d_pp == Decimal("4.0")
    assert ctr_row.trend_7d_pct is None

    markdown = render_wb_daily_operational_summary_markdown(_build_response([section], WbDailyOperationalHighlightsResponse()))
    assert "| CTR общий | 10,0% | +2,0 п.п. | +4,0 п.п. |" in markdown


def test_other_report_sections_remain_unchanged() -> None:
    current = {
        "order_sum": Decimal("1000000"),
        "order_count": Decimal("700"),
        "ad_writeoff_total": Decimal("90000"),
        "ad_spend": Decimal("90000"),
        "cart_count": Decimal("3000"),
        "add_to_cart_conversion": Decimal("8.0"),
        "cart_to_order_conversion": Decimal("23.0"),
        "avg_check": Decimal("1400"),
    }
    previous = {
        "order_sum": Decimal("900000"),
        "order_count": Decimal("650"),
        "ad_writeoff_total": Decimal("80000"),
        "ad_spend": Decimal("80000"),
        "cart_count": Decimal("2800"),
        "add_to_cart_conversion": Decimal("8.2"),
        "cart_to_order_conversion": Decimal("23.5"),
        "avg_check": Decimal("1380"),
    }
    current_7d = dict(current)
    previous_7d = dict(previous)

    sales_sec = build_sales_section(current, previous, current_7d, previous_7d)
    funnel_sec = build_funnel_section(current, previous, current_7d, previous_7d)
    assert sales_sec is not None
    assert funnel_sec is not None
    assert sales_sec.key == "sales"
    assert funnel_sec.key == "funnel"
    assert any(m.metric in ("Оборот заказов", "Сумма заказов") for m in sales_sec.metrics)
    assert any(m.metric in ("Конверсия в корзину", "Заказы") for m in funnel_sec.metrics)
