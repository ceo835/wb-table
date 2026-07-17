from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from src.mcp_server.schemas import (
    WbDailyOperationalDiagnosticsResponse,
    WbDailyOperationalHighlightsResponse,
    WbDailyOperationalReportWindowResponse,
    WbDailyOperationalSourceFreshnessResponse,
    WbDailyOperationalSummaryResponse,
)
from src.mcp_server.wb_daily_operational_summary_analysis import (
    build_highlights_from_analysis,
    build_internal_analysis,
    build_metric_history,
)
from src.mcp_server.wb_daily_operational_summary_format import render_wb_daily_operational_summary_markdown
from src.mcp_server.wb_daily_operational_summary_rules import get_default_rules


REPORT_DATE = date(2026, 7, 15)


def _trend_rows(order_sums, clicks, carts, orders, impressions) -> list[dict[str, object]]:
    start = REPORT_DATE - timedelta(days=len(order_sums) - 1)
    rows = []
    for index, order_sum in enumerate(order_sums):
        rows.append(
            {
                "report_date": start + timedelta(days=index),
                "order_sum": Decimal(str(order_sum)),
                "card_clicks": Decimal(str(clicks[index])),
                "cart_count": Decimal(str(carts[index])),
                "order_count": Decimal(str(orders[index])),
                "impressions": Decimal(str(impressions[index])) if impressions[index] is not None else None,
            }
        )
    return rows


def _article(
    nm_id: int,
    *,
    order_sums,
    clicks,
    carts,
    orders,
    impressions,
    stock_qty: int = 50,
    with_stock: int = 2,
    zero_stock: int = 0,
    stock_status: str = "OK",
) -> dict[str, object]:
    trend = _trend_rows(order_sums, clicks, carts, orders, impressions)
    current = trend[-1]
    return {
        "nm_id": nm_id,
        "supplier_article": f"ART-{nm_id}",
        "title": f"Title {nm_id}",
        "impressions": current.get("impressions"),
        "card_clicks": current.get("card_clicks"),
        "cart_count": current.get("cart_count"),
        "order_count": current.get("order_count"),
        "order_sum": current.get("order_sum"),
        "stock_qty_same_day": Decimal(str(stock_qty)),
        "warehouses_with_stock": with_stock,
        "warehouses_zero_stock": zero_stock,
        "stock_status": stock_status,
        "trend_14d": trend,
    }


def _daily_rows(values) -> list[dict[str, object]]:
    start = REPORT_DATE - timedelta(days=len(values) - 1)
    rows = []
    for index, value in enumerate(values):
        rows.append(
            {
                "report_date": start + timedelta(days=index),
                "order_sum": Decimal(str(value)),
                "order_count": Decimal("10"),
                "card_clicks": Decimal("100"),
                "impressions": Decimal("1000"),
            }
        )
    return rows


def _response_with_analysis(analysis_payload: dict[str, object]) -> WbDailyOperationalSummaryResponse:
    highlights = build_highlights_from_analysis(analysis_payload, top_n=5)
    return WbDailyOperationalSummaryResponse(
        formula_version="v1",
        report_window=WbDailyOperationalReportWindowResponse(
            report_date=REPORT_DATE,
            compare_date=REPORT_DATE - timedelta(days=1),
            trend_current_from=REPORT_DATE - timedelta(days=6),
            trend_current_to=REPORT_DATE,
            trend_previous_from=REPORT_DATE - timedelta(days=13),
            trend_previous_to=REPORT_DATE - timedelta(days=7),
            report_date_source="requested",
        ),
        requested_options={"mode": "full", "diagnostic": False, "top_n": 5},
        source_freshness=[WbDailyOperationalSourceFreshnessResponse(source="mart_total_report", max_date=REPORT_DATE, status="OK", lag_days=0)],
        sections=[],
        highlights=highlights,
        diagnostics=WbDailyOperationalDiagnosticsResponse(included_sections=[], partial_sections=[], excluded_sections=[], query_count=0, formula_version="v1"),
        article_analysis=analysis_payload.get("article_analysis", []),
        ranked_signals=analysis_payload.get("ranked_signals", []),
        data_anomalies=analysis_payload.get("data_anomalies", []),
        analysis_summary=analysis_payload.get("analysis_summary", {}),
    )


def test_build_metric_history_marks_return_to_baseline_after_spike() -> None:
    values = [100, 100, 101, 99, 100, 100, 100, 220, 102]
    rows = _daily_rows(values)

    history = build_metric_history(rows, report_date=REPORT_DATE, date_key="report_date", metric_key="order_sum")

    assert history["trend_status"] == "return_to_baseline"


def test_decline_three_days_scores_higher_than_one_day_decline() -> None:
    article_long = _article(
        1,
        order_sums=[200, 200, 200, 200, 200, 190, 170, 150],
        clicks=[100, 100, 100, 100, 100, 90, 70, 60],
        carts=[20, 20, 20, 20, 20, 18, 14, 12],
        orders=[10, 10, 10, 10, 10, 9, 8, 7],
        impressions=[1000, 1000, 1000, 1000, 1000, 900, 800, 700],
    )
    article_short = _article(
        2,
        order_sums=[200, 200, 200, 200, 200, 200, 200, 140],
        clicks=[100, 100, 100, 100, 100, 100, 100, 60],
        carts=[20, 20, 20, 20, 20, 20, 20, 12],
        orders=[10, 10, 10, 10, 10, 10, 10, 7],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 700],
    )
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([500, 500, 500, 500, 500, 500, 500, 300]),
        article_context=[article_long, article_short],
        warehouse_context=[],
        campaign_context=[],
        search_query_context=[],
        entry_point_context=[],
        price_context=[],
        logistics_context=[],
        data_gaps=[],
        rules=get_default_rules(),
        top_n=5,
    )

    traffic_signals = [signal for signal in analysis["ranked_signals"] if signal["kind"] == "traffic"]
    by_nm = {signal["nm_id"]: signal for signal in traffic_signals}
    assert by_nm[1]["score"] > by_nm[2]["score"]


def test_search_position_without_traffic_drop_is_not_main_problem() -> None:
    article = _article(
        3,
        order_sums=[200, 200, 200, 200, 200, 200, 200, 200],
        clicks=[100, 100, 100, 100, 100, 100, 100, 100],
        carts=[20, 20, 20, 20, 20, 20, 20, 20],
        orders=[10, 10, 10, 10, 10, 10, 10, 10],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
    )
    search_context = [
        {
            "nm_id": 3,
            "search_query": "query",
            "avg_position": Decimal("320"),
            "previous_avg_position": Decimal("6"),
            "position_delta_day": Decimal("314"),
            "search_clicks": Decimal("15"),
            "search_orders": Decimal("3"),
            "clicks_delta_day": Decimal("0"),
            "orders_delta_day": Decimal("0"),
            "visibility": Decimal("12"),
            "previous_visibility": Decimal("12"),
            "trend_7d": [
                {"date": REPORT_DATE - timedelta(days=1), "search_clicks": Decimal("12")},
                {"date": REPORT_DATE, "search_clicks": Decimal("15")},
            ],
        }
    ]
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([500, 500, 500, 500, 500, 500, 500, 500]),
        article_context=[article],
        warehouse_context=[],
        campaign_context=[],
        search_query_context=search_context,
        entry_point_context=[],
        price_context=[],
        logistics_context=[],
        data_gaps=[],
        rules=get_default_rules(),
        top_n=5,
    )

    assert all(signal["kind"] != "search" for signal in analysis["ranked_signals"])
    main_problem = analysis["analysis_summary"].get("main_problem")
    assert main_problem is None or main_problem["kind"] != "search"


def test_low_traffic_position_jump_goes_to_anomalies() -> None:
    article = _article(
        4,
        order_sums=[200, 200, 200, 200, 200, 200, 200, 190],
        clicks=[100, 100, 100, 100, 100, 100, 100, 95],
        carts=[20, 20, 20, 20, 20, 20, 20, 19],
        orders=[10, 10, 10, 10, 10, 10, 10, 9],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
    )
    search_context = [
        {
            "nm_id": 4,
            "search_query": "rare query",
            "avg_position": Decimal("250"),
            "previous_avg_position": Decimal("3"),
            "position_delta_day": Decimal("247"),
            "search_clicks": Decimal("1"),
            "search_orders": Decimal("0"),
            "clicks_delta_day": Decimal("0"),
            "orders_delta_day": Decimal("0"),
            "visibility": Decimal("3"),
            "previous_visibility": Decimal("4"),
            "trend_7d": [
                {"date": REPORT_DATE - timedelta(days=1), "search_clicks": Decimal("1")},
                {"date": REPORT_DATE, "search_clicks": Decimal("1")},
            ],
        }
    ]
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([500, 500, 500, 500, 500, 500, 500, 480]),
        article_context=[article],
        warehouse_context=[],
        campaign_context=[],
        search_query_context=search_context,
        entry_point_context=[],
        price_context=[],
        logistics_context=[],
        data_gaps=[],
        rules=get_default_rules(),
        top_n=5,
    )

    assert any(anomaly["kind"] == "search_low_traffic_position_jump" for anomaly in analysis["data_anomalies"])


def test_logistics_is_not_used_as_causal_signal() -> None:
    article = _article(
        5,
        order_sums=[200, 200, 200, 200, 200, 200, 200, 180],
        clicks=[100, 100, 100, 100, 100, 100, 100, 100],
        carts=[20, 20, 20, 20, 20, 20, 20, 20],
        orders=[10, 10, 10, 10, 10, 10, 10, 10],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
    )
    logistics_context = [{"nm_id": 5, "total_logistics_delta_day": Decimal("5000"), "source_status": "PARTIAL"}]
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([500, 500, 500, 500, 500, 500, 500, 480]),
        article_context=[article],
        warehouse_context=[],
        campaign_context=[],
        search_query_context=[],
        entry_point_context=[],
        price_context=[],
        logistics_context=logistics_context,
        data_gaps=[],
        rules=get_default_rules(),
        top_n=5,
    )

    assert all(signal["kind"] != "logistics" for signal in analysis["ranked_signals"])


def test_partial_source_does_not_become_main_problem() -> None:
    article = _article(
        6,
        order_sums=[200, 200, 200, 200, 200, 180, 160, 140],
        clicks=[100, 100, 100, 100, 100, 100, 100, 100],
        carts=[20, 20, 20, 20, 20, 18, 16, 14],
        orders=[10, 10, 10, 10, 10, 9, 8, 7],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
        stock_qty=0,
        stock_status="PARTIAL",
    )
    warehouse_context = [{"nm_id": 6, "avg_orders_7d_article": Decimal("8"), "risk_type": "OUT_OF_STOCK", "warehouse_name": "WH-1"}]
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([500, 500, 500, 500, 500, 500, 500, 420]),
        article_context=[article],
        warehouse_context=warehouse_context,
        campaign_context=[],
        search_query_context=[],
        entry_point_context=[],
        price_context=[],
        logistics_context=[],
        data_gaps=[],
        rules=get_default_rules(),
        top_n=5,
    )

    stock_signals = [signal for signal in analysis["ranked_signals"] if signal["kind"] == "stock"]
    assert stock_signals
    assert stock_signals[0]["user_visible"] is False
    main_problem = analysis["analysis_summary"].get("main_problem")
    assert main_problem is None or main_problem["kind"] != "stock"


def test_stock_priority_text_contains_exact_values() -> None:
    article = _article(
        7,
        order_sums=[200, 200, 200, 200, 200, 180, 160, 140],
        clicks=[100, 100, 100, 100, 100, 90, 80, 70],
        carts=[20, 20, 20, 20, 20, 18, 16, 14],
        orders=[10, 10, 10, 10, 10, 9, 8, 7],
        impressions=[1000, 1000, 1000, 1000, 1000, 900, 850, 800],
        stock_qty=2,
        with_stock=1,
        zero_stock=3,
    )
    warehouse_context = [{"nm_id": 7, "avg_orders_7d_article": Decimal("8"), "risk_type": "LOW_STOCK", "warehouse_name": "WH-2"}]
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([500, 500, 500, 500, 500, 420, 380, 300]),
        article_context=[article],
        warehouse_context=warehouse_context,
        campaign_context=[],
        search_query_context=[],
        entry_point_context=[],
        price_context=[],
        logistics_context=[],
        data_gaps=[],
        rules=get_default_rules(),
        top_n=5,
    )

    stock_signal = next(signal for signal in analysis["ranked_signals"] if signal["kind"] == "stock")
    text = stock_signal["check"]["text"]
    assert "2" in text
    assert "8.0" in text
    assert "1" in text
    assert "3" in text

def test_priority_action_contains_concrete_object_fields() -> None:
    article = _article(
        8,
        order_sums=[200, 200, 200, 200, 200, 190, 170, 150],
        clicks=[100, 100, 100, 100, 100, 90, 70, 60],
        carts=[20, 20, 20, 20, 20, 18, 14, 12],
        orders=[10, 10, 10, 10, 10, 9, 8, 7],
        impressions=[1000, 1000, 1000, 1000, 1000, 900, 800, 700],
    )
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([500, 500, 500, 500, 500, 450, 380, 320]),
        article_context=[article],
        warehouse_context=[],
        campaign_context=[],
        search_query_context=[],
        entry_point_context=[],
        price_context=[],
        logistics_context=[],
        data_gaps=[],
        rules=get_default_rules(),
        top_n=5,
    )

    action = analysis["analysis_summary"]["priority_checks"][0]
    assert action["nm_id"] == 8
    assert action["metric"]
    assert action["text"]


def test_markdown_omits_internal_score_and_confidence() -> None:
    article = _article(
        9,
        order_sums=[200, 200, 200, 200, 200, 190, 170, 150],
        clicks=[100, 100, 100, 100, 100, 90, 70, 60],
        carts=[20, 20, 20, 20, 20, 18, 14, 12],
        orders=[10, 10, 10, 10, 10, 9, 8, 7],
        impressions=[1000, 1000, 1000, 1000, 1000, 900, 800, 700],
    )
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([500, 500, 500, 500, 500, 450, 380, 320]),
        article_context=[article],
        warehouse_context=[],
        campaign_context=[],
        search_query_context=[],
        entry_point_context=[],
        price_context=[],
        logistics_context=[],
        data_gaps=[],
        rules=get_default_rules(),
        top_n=5,
    )

    markdown = render_wb_daily_operational_summary_markdown(_response_with_analysis(analysis))
    assert "confidence" not in markdown.lower()
    assert "score" not in markdown.lower()


def test_response_contract_keeps_old_and_new_fields() -> None:
    response = _response_with_analysis({
        "article_analysis": [],
        "ranked_signals": [],
        "data_anomalies": [],
        "analysis_summary": {},
    })

    payload = response.model_dump()

    assert "sections" in payload
    assert "highlights" in payload
    assert "article_context" in payload
    assert "warehouse_context" in payload
    assert "article_analysis" in payload
    assert "ranked_signals" in payload
    assert "data_anomalies" in payload
    assert "analysis_summary" in payload


