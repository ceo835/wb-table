from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from src.mcp_server.schemas import (
    WbDailyOperationalDiagnosticsResponse,
    WbDailyOperationalHighlightsResponse,
    WbDailyOperationalReportWindowResponse,
    WbDailyOperationalSourceFreshnessResponse,
    WbDailyOperationalSummaryResponse,
    WbDailyOperationalMetricRowResponse,
    WbDailyOperationalSectionResponse,
    WbDailyOperationalTableResponse,
)
from src.mcp_server.wb_daily_operational_summary_analysis import (
    _merge_business_priorities,
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
        business_priorities=analysis_payload.get("business_priorities", analysis_payload.get("ranked_signals", [])),
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
    assert all(signal["kind"] != "search" for signal in analysis["ranked_signals"])


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
    assert "Оценка запаса по общей скорости артикула" in text

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
    assert "severity" not in markdown.lower()
    assert "cause_status" not in markdown.lower()
    assert "\u0441 \u0432\u044b\u0441\u043e\u043a\u043e\u0439 \u0443\u0432\u0435\u0440\u0435\u043d\u043d\u043e\u0441\u0442\u044c\u044e" not in markdown.lower()


def test_response_contract_keeps_old_and_new_fields() -> None:
    response = _response_with_analysis({
        "article_analysis": [],
        "business_priorities": [],
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
    assert "business_priorities" in payload
    assert "ranked_signals" in payload
    assert "data_anomalies" in payload
    assert "analysis_summary" in payload




def test_baseline_ignores_current_day_and_counts_available_days() -> None:
    rows = _daily_rows([100, 100, 100, 100, 100, 100, 100, 300])

    history = build_metric_history(rows, report_date=REPORT_DATE, date_key="report_date", metric_key="order_sum")

    assert history["avg_prev_7"] == Decimal("100")
    assert history["median_prev_7"] == Decimal("100")
    assert history["history_days_available"] == 7


def test_business_priorities_are_separated_from_data_anomalies() -> None:
    article = _article(
        10,
        order_sums=[200, 200, 200, 200, 200, 200, 200, 190],
        clicks=[100, 100, 100, 100, 100, 100, 100, 95],
        carts=[20, 20, 20, 20, 20, 20, 20, 19],
        orders=[10, 10, 10, 10, 10, 10, 10, 9],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
    )
    search_context = [{
        "nm_id": 10,
        "search_query": "rare query",
        "avg_position": Decimal("250"),
        "previous_avg_position": Decimal("3"),
        "position_delta_day": Decimal("247"),
        "search_clicks": Decimal("1"),
        "search_orders": Decimal("0"),
        "clicks_delta_day": Decimal("0"),
        "orders_delta_day": Decimal("0"),
        "visibility": Decimal("0"),
        "previous_visibility": Decimal("4"),
        "trend_7d": [
            {"date": REPORT_DATE - timedelta(days=1), "search_clicks": Decimal("1")},
            {"date": REPORT_DATE, "search_clicks": Decimal("1")},
        ],
    }]
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

    assert len(analysis["business_priorities"]) <= len(analysis["ranked_signals"])
    assert all(signal["kind"] != "anomaly" for signal in analysis["business_priorities"])
    assert analysis["data_anomalies"]


def test_response_contains_no_mojibake() -> None:
    article = _article(
        11,
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
    response = _response_with_analysis(analysis)
    markdown = render_wb_daily_operational_summary_markdown(response)

    bad_markers = ("Р ", "СЃ", "вЂ", "РџС")
    serialized = str(response.model_dump()) + markdown
    assert not any(marker in serialized for marker in bad_markers)


def test_article_analysis_baseline_is_filled_with_sufficient_history() -> None:
    article = _article(
        12,
        order_sums=[100, 100, 100, 100, 100, 100, 100, 120],
        clicks=[50, 50, 50, 50, 50, 50, 50, 55],
        carts=[10, 10, 10, 10, 10, 10, 10, 11],
        orders=[5, 5, 5, 5, 5, 5, 5, 6],
        impressions=[500, 500, 500, 500, 500, 500, 500, 550],
    )
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([500, 500, 500, 500, 500, 500, 500, 520]),
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

    baseline = analysis["article_analysis"][0]["sales"]["baseline"]
    assert baseline["history_days_available"] == 7
    assert baseline["avg_prev_7"] == Decimal("100")
    assert baseline["median_prev_7"] == Decimal("100")
    assert baseline["avg_prev_14"] is None
    assert baseline["delta_vs_previous_day"] == Decimal("20")
    assert baseline["trend_status"] != "insufficient_history"


def test_large_turnover_loss_is_created_without_confirmed_cause() -> None:
    article = _article(
        13,
        order_sums=[100000, 100000, 100000, 100000, 100000, 100000, 100000, 70000],
        clicks=[100, 100, 100, 100, 100, 100, 100, 100],
        carts=[20, 20, 20, 20, 20, 20, 20, 20],
        orders=[10, 10, 10, 10, 10, 10, 10, 10],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
    )
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([200000, 200000, 200000, 200000, 200000, 200000, 200000, 170000]),
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

    signal = next(signal for signal in analysis["business_priorities"] if signal["kind"] == "large_turnover_loss")
    assert signal["nm_id"] == 13
    assert signal["cause_status"] == "unconfirmed"
    assert signal["impact_rub"] == Decimal("-30000")
    assert signal["supported_factors"] == []
    assert signal["missing_evidence"] == ["confirmed_primary_cause"]


def test_large_turnover_growth_is_created_without_confirmed_cause() -> None:
    article = _article(
        14,
        order_sums=[60000, 60000, 60000, 60000, 60000, 60000, 60000, 85000],
        clicks=[100, 100, 100, 100, 100, 100, 100, 100],
        carts=[20, 20, 20, 20, 20, 20, 20, 20],
        orders=[10, 10, 10, 10, 10, 10, 10, 10],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
    )
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([300000, 300000, 300000, 300000, 300000, 300000, 300000, 325000]),
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

    assert any(signal["kind"] == "large_turnover_growth" for signal in analysis["ranked_signals"])
    signal = next(signal for signal in analysis["business_priorities"] if signal["nm_id"] == 14)
    assert signal["kind"] == "article_growth"
    assert signal["cause_status"] == "confirmed"
    assert signal["impact_rub"] == Decimal("25000")
    assert any(item["kind"] == "large_turnover_growth" for item in signal["supporting_signals"])


def test_generic_turnover_signal_does_not_assert_unconfirmed_cause() -> None:
    article = _article(
        15,
        order_sums=[100000, 100000, 100000, 100000, 100000, 100000, 100000, 70000],
        clicks=[100, 100, 100, 100, 100, 100, 100, 100],
        carts=[20, 20, 20, 20, 20, 20, 20, 20],
        orders=[10, 10, 10, 10, 10, 10, 10, 10],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
    )
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([200000, 200000, 200000, 200000, 200000, 200000, 200000, 170000]),
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

    signal = next(signal for signal in analysis["business_priorities"] if signal["kind"] == "large_turnover_loss")
    combined_text = f"{signal['title']} {signal['summary']} {signal['check']['text']}".lower()
    assert "из-за" not in combined_text
    assert "причина пока не подтверждена" in combined_text


def test_business_priorities_include_large_monetary_effect() -> None:
    article = _article(
        16,
        order_sums=[100000, 100000, 100000, 100000, 100000, 100000, 100000, 70000],
        clicks=[100, 100, 100, 100, 100, 100, 100, 100],
        carts=[20, 20, 20, 20, 20, 20, 20, 20],
        orders=[10, 10, 10, 10, 10, 10, 10, 10],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
    )
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([200000, 200000, 200000, 200000, 200000, 200000, 200000, 170000]),
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

    assert any(signal["kind"] == "large_turnover_loss" for signal in analysis["business_priorities"])


def test_stock_signal_can_enter_business_priorities_for_confirmed_growth_risk() -> None:
    article = _article(
        577510563,
        order_sums=[10000, 10000, 10000, 10000, 10000, 12000, 14000, 18000],
        clicks=[100, 100, 100, 100, 100, 110, 120, 130],
        carts=[20, 20, 20, 20, 20, 22, 24, 26],
        orders=[10, 10, 10, 10, 10, 12, 14, 16],
        impressions=[1000, 1000, 1000, 1000, 1000, 1100, 1200, 1300],
        stock_qty=4,
        with_stock=1,
        zero_stock=3,
        stock_status="OK",
    )
    warehouse_context = [{"nm_id": 577510563, "avg_orders_7d_article": Decimal("8"), "risk_type": "LOW_STOCK", "warehouse_name": "WH-1"}]
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([100000, 100000, 100000, 100000, 100000, 105000, 110000, 118000]),
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

    stock_signal = next(signal for signal in analysis["business_priorities"] if signal["kind"] == "stock")
    assert stock_signal["nm_id"] == 577510563
    assert stock_signal["cause_status"] == "confirmed"


def test_previous_day_spike_refers_to_previous_day_vs_baseline() -> None:
    rows = _daily_rows([100, 100, 100, 100, 100, 100, 100, 220, 150])

    history = build_metric_history(rows, report_date=REPORT_DATE, date_key="report_date", metric_key="order_sum")

    assert history["previous_day"] == Decimal("220")
    assert history["previous_day_pct_vs_avg_prev_7"] == Decimal("120")
    assert history["trend_status"] == "previous_day_spike"


def test_previous_day_drop_refers_to_previous_day_vs_baseline() -> None:
    rows = _daily_rows([100, 100, 100, 100, 100, 100, 100, 40, 80])

    history = build_metric_history(rows, report_date=REPORT_DATE, date_key="report_date", metric_key="order_sum")

    assert history["previous_day"] == Decimal("40")
    assert history["previous_day_pct_vs_avg_prev_7"] == Decimal("-60")
    assert history["trend_status"] == "previous_day_drop"


def test_business_priorities_deduplicate_same_nm_id_and_preserve_ranked_signals() -> None:
    article = _article(
        17,
        order_sums=[100000, 100000, 100000, 100000, 100000, 100000, 100000, 70000],
        clicks=[100, 100, 100, 100, 100, 100, 100, 70],
        carts=[20, 20, 20, 20, 20, 20, 20, 14],
        orders=[10, 10, 10, 10, 10, 10, 10, 7],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 700],
    )
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([200000, 200000, 200000, 200000, 200000, 200000, 200000, 170000]),
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

    ranked_same_nm = [signal for signal in analysis["ranked_signals"] if signal.get("nm_id") == 17]
    priority_same_nm = [signal for signal in analysis["business_priorities"] if signal.get("nm_id") == 17]
    assert len(ranked_same_nm) >= 2
    assert {signal["kind"] for signal in ranked_same_nm} >= {"traffic", "large_turnover_loss"}
    assert len(priority_same_nm) == 1
    merged = priority_same_nm[0]
    assert merged["kind"] == "traffic"
    assert merged["impact_rub"] == Decimal("-30000")
    assert any(item["kind"] == "large_turnover_loss" for item in merged["supporting_signals"])
    assert "clicks_down" in merged["evidence"]


def test_merge_business_priorities_keeps_different_entity_types_separate() -> None:
    merged = _merge_business_priorities([
        {
            "kind": "traffic",
            "entity_type": "product",
            "entity_id": 42,
            "nm_id": 42,
            "direction": "negative",
            "impact_rub": Decimal("-1000"),
            "cause_status": "confirmed",
            "score": Decimal("10"),
            "summary": "product",
            "check": {"text": "check product"},
            "supported_factors": ["traffic"],
            "evidence": ["clicks_down"],
            "user_visible": True,
        },
        {
            "kind": "ads",
            "entity_type": "campaign",
            "entity_id": 42,
            "advert_id": 42,
            "direction": "negative",
            "impact_rub": Decimal("-800"),
            "cause_status": "confirmed",
            "score": Decimal("9"),
            "summary": "campaign",
            "check": {"text": "check campaign"},
            "supported_factors": ["ads"],
            "evidence": ["ad_spend"],
            "user_visible": True,
        },
    ])

    assert len(merged) == 2


def test_merge_business_priorities_keeps_primary_signal_and_recommended_checks() -> None:
    merged = _merge_business_priorities([
        {
            "kind": "traffic",
            "entity_type": "product",
            "entity_id": 42,
            "nm_id": 42,
            "direction": "negative",
            "impact_rub": Decimal("-30000"),
            "cause_status": "confirmed",
            "score": Decimal("20"),
            "summary": "traffic summary",
            "title": "traffic title",
            "check": {"text": "check traffic"},
            "supported_factors": ["traffic"],
            "evidence": ["clicks_down"],
            "missing_evidence": [],
            "user_visible": True,
        },
        {
            "kind": "large_turnover_loss",
            "entity_type": "product",
            "entity_id": 42,
            "nm_id": 42,
            "direction": "negative",
            "impact_rub": Decimal("-30000"),
            "cause_status": "unconfirmed",
            "score": Decimal("10"),
            "summary": "loss summary",
            "title": "loss title",
            "check": {"text": "check loss"},
            "supported_factors": [],
            "evidence": [],
            "missing_evidence": ["confirmed_primary_cause"],
            "user_visible": True,
        },
    ])

    assert merged[0]["primary_signal"]["kind"] == "traffic"
    assert merged[0]["recommended_checks"] == ["check traffic", "check loss"]
    assert merged[0]["missing_evidence"] == ["confirmed_primary_cause"]


def test_priority_narrative_uses_supporting_signal_language() -> None:
    article = _article(
        18,
        order_sums=[100000, 100000, 100000, 100000, 100000, 100000, 100000, 70000],
        clicks=[100, 100, 100, 100, 100, 100, 100, 70],
        carts=[20, 20, 20, 20, 20, 20, 20, 14],
        orders=[10, 10, 10, 10, 10, 10, 10, 7],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 700],
    )
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([200000, 200000, 200000, 200000, 200000, 200000, 200000, 170000]),
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

    narrative = next(item for item in analysis["analysis_summary"]["priority_narratives"] if item.get("nm_id") == 18)
    assert "\u043f\u0440\u043e\u0441\u0430\u0434\u043a\u043e\u0439 \u0442\u0440\u0430\u0444\u0438\u043a\u0430 \u0438 \u043a\u043b\u0438\u043a\u043e\u0432" in narrative["text"]


def test_assortment_narrative_contains_concrete_nm_id_and_impact() -> None:
    decline = _article(
        19,
        order_sums=[100000, 100000, 100000, 100000, 100000, 100000, 100000, 70000],
        clicks=[100, 100, 100, 100, 100, 100, 100, 100],
        carts=[20, 20, 20, 20, 20, 20, 20, 20],
        orders=[10, 10, 10, 10, 10, 10, 10, 10],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
    )
    growth = _article(
        20,
        order_sums=[60000, 60000, 60000, 60000, 60000, 60000, 60000, 85000],
        clicks=[100, 100, 100, 100, 100, 100, 100, 100],
        carts=[20, 20, 20, 20, 20, 20, 20, 20],
        orders=[10, 10, 10, 10, 10, 10, 10, 10],
        impressions=[1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
    )
    analysis = build_internal_analysis(
        report_date=REPORT_DATE,
        daily_rows=_daily_rows([300000, 300000, 300000, 300000, 300000, 300000, 300000, 295000]),
        article_context=[decline, growth],
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

    comment = analysis["analysis_summary"]["section_narratives"]["assortment"]["comment"]
    assert "19" in comment
    assert "20" in comment
    assert "30 000" in comment or "25 000" in comment


def test_highlights_priority_checks_use_short_actions_not_full_narratives() -> None:
    highlights = build_highlights_from_analysis(
        {
            "analysis_summary": {
                "user_worse": ["????? ???? ???????."],
                "user_better": ["???? ????? ?????."],
                "priority_narratives": [
                    {
                        "text": "??????? 1 ??? ?????? ??????? -10 000 ?. ???????? ?????????????? ????????.",
                        "action": "????????? ?????? ???????? 1.",
                    }
                ],
                "action_items": [{"text": "????????? ?????? ???????? 1."}],
            }
        },
        top_n=5,
    )

    assert highlights.priority_checks == ["????????? ?????? ???????? 1."]
    assert "??????? 1 ??? ?????? ???????" not in highlights.priority_checks[0]


def _build_test_metric(metric: str, value: Any = None, previous_value: Any = None, delta_abs: Any = None, delta_pct: Decimal | None = None, delta_pp: Decimal | None = None, trend_7d_pct: Decimal | None = None, trend_7d_pp: Decimal | None = None) -> WbDailyOperationalMetricRowResponse:
    return WbDailyOperationalMetricRowResponse(
        metric=metric,
        value=value,
        previous_value=previous_value,
        delta_abs=delta_abs,
        delta_pct=delta_pct,
        delta_pp=delta_pp,
        trend_7d_pct=trend_7d_pct,
        trend_7d_pp=trend_7d_pp,
    )


def _build_test_section(key: str, metrics: list[WbDailyOperationalMetricRowResponse], tables: list[WbDailyOperationalTableResponse] = None) -> WbDailyOperationalSectionResponse:
    return WbDailyOperationalSectionResponse(
        key=key,
        title=key.upper(),
        status="OK",
        summary=[],
        metrics=metrics,
        tables=tables or [],
    )


def _build_mock_mcp_response(
    report_date: date,
    *,
    profit_val: Decimal | None = None,
    profit_delta: Decimal | None = None,
    profit_trend: Decimal | None = None,
    drr_val: Decimal | None = None,
    drr_delta: Decimal | None = None,
    cpo_val: Decimal | None = None,
    cpo_delta: Decimal | None = None,
    ad_orders_change: Decimal | None = None,
    ad_spend_change: Decimal | None = None,
    turnover_change: Decimal | None = None,
    turnover_trend: Decimal | None = None,
    orders_change: Decimal | None = None,
    orders_trend: Decimal | None = None,
    business_priorities: list[dict[str, Any]] = None,
    stock_table_rows: list[dict[str, Any]] = None,
) -> WbDailyOperationalSummaryResponse:
    compare_date = report_date - timedelta(days=1)
    
    sections = []
    
    # Overview section
    overview_metrics = []
    if turnover_change is not None:
        overview_metrics.append(_build_test_metric("Оборот заказов", value=Decimal("100000"), previous_value=Decimal("90000"), delta_pct=turnover_change, trend_7d_pct=turnover_trend))
    if orders_change is not None:
        overview_metrics.append(_build_test_metric("Заказы", value=Decimal("100"), previous_value=Decimal("90"), delta_pct=orders_change, trend_7d_pct=orders_trend))
    if ad_spend_change is not None:
        overview_metrics.append(_build_test_metric("Фактические рекламные списания", value=Decimal("15000"), previous_value=Decimal("14000"), delta_pct=ad_spend_change))
    sections.append(_build_test_section("overview", overview_metrics))
    
    # Profit section
    if profit_val is not None or profit_delta is not None or profit_trend is not None:
        sections.append(_build_test_section("profit", [
            _build_test_metric("Операционная прибыль", value=profit_val, delta_abs=profit_delta, trend_7d_pct=profit_trend)
        ]))
        
    # Ads section
    ads_metrics = []
    if drr_val is not None:
        ads_metrics.append(_build_test_metric("ДРР (по кампаниям)", value=drr_val, delta_pp=drr_delta))
    if cpo_val is not None:
        ads_metrics.append(_build_test_metric("CPO", value=cpo_val, delta_pct=cpo_delta))
    if ad_orders_change is not None:
        ads_metrics.append(_build_test_metric("Рекламные заказы", value=Decimal("50"), delta_pct=ad_orders_change))
    if ad_spend_change is not None:
        ads_metrics.append(_build_test_metric("Расход по статистике кампаний", value=Decimal("20000"), delta_pct=ad_spend_change))
    
    # Stock section
    stock_tables = []
    if stock_table_rows is not None:
        stock_tables.append(WbDailyOperationalTableResponse(
            title="Складские риски",
            columns=["Артикул", "Артикул продавца", "Товар", "Склад", "Остаток", "Средние заказы 7д", "Оценка запаса", "Риск"],
            rows=stock_table_rows
        ))
    sections.append(_build_test_section("ads", ads_metrics))
    sections.append(_build_test_section("stock", [], tables=stock_tables))
    
    return WbDailyOperationalSummaryResponse(
        formula_version="v1",
        report_window=WbDailyOperationalReportWindowResponse(
            report_date=report_date,
            compare_date=compare_date,
            trend_current_from=report_date - timedelta(days=6),
            trend_current_to=report_date,
            trend_previous_from=report_date - timedelta(days=13),
            trend_previous_to=report_date - timedelta(days=7),
            report_date_source="requested",
        ),
        requested_options={"mode": "full", "diagnostic": False, "top_n": 5},
        source_freshness=[WbDailyOperationalSourceFreshnessResponse(source="mart_total_report", max_date=report_date, status="OK", lag_days=0)],
        sections=sections,
        highlights=WbDailyOperationalHighlightsResponse(worse=[], better=[], priority_checks=[]),
        diagnostics=WbDailyOperationalDiagnosticsResponse(included_sections=[], partial_sections=[], excluded_sections=[], query_count=0, formula_version="v1"),
        article_analysis=[],
        business_priorities=business_priorities or [],
        ranked_signals=business_priorities or [],
        data_anomalies=[],
        analysis_summary={},
    )


def test_actions_prioritization_negative_profit_and_ads() -> None:
    # 1. P1 Negative profit and P2 advertising worsening are present.
    response = _build_mock_mcp_response(
        date(2026, 7, 19),
        profit_val=Decimal("-5543"),
        drr_val=Decimal("22.1"),
        drr_delta=Decimal("2.1"),
        cpo_val=Decimal("346"),
        cpo_delta=Decimal("15.5"),
        ad_orders_change=Decimal("-10.2"),
        ad_spend_change=Decimal("5.0"),
        business_priorities=[
            {"kind": "article_growth", "direction": "positive", "nm_id": 221311710, "score": Decimal("25"), "user_visible": True}
        ]
    )
    
    markdown = render_wb_daily_operational_summary_markdown(response)
    
    # Assert actions are present and prioritized
    assert "1. Проверить причины отрицательной прибыли по VVBromo: −5 543 ₽." in markdown
    assert "2. Пересмотреть рекламу: ДРР 22,1%, CPO 346 ₽, рекламные заказы −10,2% за сутки." in markdown
    assert "3. Проверить устойчивость роста по артикулу 221311710." in markdown


def test_actions_prioritization_stock_score_competition() -> None:
    # Stock risk with supply <= 3 should get a boost and beat growth
    business_priorities = [
        {"kind": "stock", "direction": "negative", "nm_id": 1111, "score": Decimal("10"), "user_visible": True},
        {"kind": "article_growth", "direction": "positive", "nm_id": 221311710, "score": Decimal("25"), "user_visible": True}
    ]
    stock_rows = [
        {"Артикул": "1111", "Оценка запаса": "2 дн."}
    ]
    
    response = _build_mock_mcp_response(
        date(2026, 7, 19),
        profit_val=Decimal("-5543"),
        drr_val=Decimal("22.1"),
        drr_delta=Decimal("2.1"),
        cpo_val=Decimal("346"),
        cpo_delta=Decimal("15.5"),
        ad_orders_change=Decimal("-10.2"),
        ad_spend_change=Decimal("5.0"),
        business_priorities=business_priorities,
        stock_table_rows=stock_rows
    )
    
    markdown = render_wb_daily_operational_summary_markdown(response)
    
    # Since days of supply <= 3, the score of 1111 is boosted by 100 to 110, which beats 25 (growth).
    assert "3. Проверить остатки 1111: запас 2 дня." in markdown
    assert "221311710" not in markdown.split("## Действия на день")[1]


def test_actions_prioritization_dynamic_analytical_summary_line_synthetic_date() -> None:
    # Test on a synthetic date date(2026, 8, 20) with matching criteria
    response = _build_mock_mcp_response(
        date(2026, 8, 20),
        turnover_change=Decimal("5.0"),     # daily grew
        turnover_trend=Decimal("-3.0"),     # weekly trend negative
        ad_spend_change=Decimal("2.0"),     # spend grew or stable
        ad_orders_change=Decimal("-5.0"),   # ad orders down
        profit_val=Decimal("-2000"),        # profit negative
        business_priorities=[]
    )
    
    markdown = render_wb_daily_operational_summary_markdown(response)
    
    # Verify analytical line is present
    expected_line = (
        "Продажи восстановились относительно предыдущего дня, но недельная динамика остаётся отрицательной; "
        "рост рекламных расходов не дал сопоставимого роста рекламных заказов, поэтому прибыль по VVBromo "
        "осталась отрицательной."
    )
    assert expected_line in markdown


def test_actions_prioritization_negative_scenarios_no_actions_or_summary_line() -> None:
    # Positive profit, positive trend, no ad orders drop: no actions and no analytical summary line
    response = _build_mock_mcp_response(
        date(2026, 8, 20),
        turnover_change=Decimal("5.0"),     # daily grew
        turnover_trend=Decimal("3.0"),      # weekly trend positive (NOT negative!)
        ad_spend_change=Decimal("-2.0"),
        ad_orders_change=Decimal("5.0"),    # ad orders grew (NOT down!)
        profit_val=Decimal("12000"),        # profit positive
        business_priorities=[]
    )
    
    markdown = render_wb_daily_operational_summary_markdown(response)
    
    expected_line = (
        "Продажи восстановились относительно предыдущего дня, но недельная динамика остаётся отрицательной; "
        "рост рекламных расходов не дал сопоставимого роста рекламных заказов, поэтому прибыль по VVBromo "
        "осталась отрицательной."
    )
    # Check that neither P1, P2 nor the summary line are present
    assert expected_line not in markdown
    assert "Проверить причины отрицательной прибыли" not in markdown
    assert "Пересмотреть рекламу" not in markdown
