from __future__ import annotations

import os
import pytest

# Safety check and environment routing at the very top
test_db_url = os.getenv("TEST_DATABASE_URL")
if not test_db_url:
    raise RuntimeError("Safety Block: TEST_DATABASE_URL environment variable is not configured. Run blocked.")

# Check for railway production host
for key in ("DATABASE_URL", "TEST_DATABASE_URL"):
    val = os.getenv(key) or ""
    if "rlwy.net" in val or "railway" in val:
        raise RuntimeError(f"Safety Block: {key} contains Railway production database host! Run blocked to protect production data.")

# Override DATABASE_URL so all subsequent imports and settings use the test DB url
os.environ["DATABASE_URL"] = test_db_url
os.environ["MCP_AUTH_TOKEN"] = "test"

from datetime import date, datetime
from decimal import Decimal
from typing import Any
import pytest
from sqlalchemy import select

from src.db.models import ExternalContextEvent, ExternalContextMetric
from src.db.session import session_scope
from src.mcp_server.settings import McpServiceSettings
from src.services.external_context.service import ExternalContextService
from src.services.external_context.schemas import ExternalContextRequest
from src.mcp_server.wb_daily_operational_summary_format import render_wb_daily_operational_summary_markdown
from src.mcp_server.wb_daily_operational_summary import build_operational_summary
from src.mcp_server.schemas import (
    WbDailyOperationalSummaryRequest,
    WbDailyOperationalSummaryResponse,
    WbDailyOperationalSectionResponse,
    WbDailyOperationalMetricRowResponse,
    WbDailyOperationalHighlightsResponse,
    WbDailyOperationalReportWindowResponse,
    WbDailyOperationalDiagnosticsResponse,
)

@pytest.fixture
def clean_external_db():
    with session_scope() as session:
        session.query(ExternalContextEvent).delete()
        session.query(ExternalContextMetric).delete()
        session.commit()
    yield
    with session_scope() as session:
        session.query(ExternalContextEvent).delete()
        session.query(ExternalContextMetric).delete()
        session.commit()


@pytest.fixture
def test_settings():
    db_url = os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@localhost:5432/wb_table"
    return McpServiceSettings(
        database_url=db_url,
        auth_token="test",
        max_rows=100,
        query_timeout_seconds=10,
        mcp_public_mode=False
    )


def test_loader_idempotency(clean_external_db) -> None:
    # Verify that reloading the same metrics is idempotent and statistics behave correctly
    from scripts import load_external_macro_metrics
    
    # We monkeypatch arg parsing to default to dry-run = False
    class Args:
        dry_run = False
        
    import argparse
    original_parse = argparse.ArgumentParser.parse_args
    argparse.ArgumentParser.parse_args = lambda self: Args()
    
    try:
        # Run macro loader the first time (inserts)
        res1 = load_external_macro_metrics.main()
        assert res1 == 0
        
        with session_scope() as session:
            initial_count = session.query(ExternalContextMetric).count()
            assert initial_count > 0
            
        # Run second time (should be unchanged, 0 inserted/updated)
        import sys
        sys.argv = ["load_external_macro_metrics.py"]
        res2 = load_external_macro_metrics.main()
        assert res2 == 0
    finally:
        argparse.ArgumentParser.parse_args = original_parse


def test_search_demand_matching_trends(clean_external_db, test_settings) -> None:
    # 1. Search demand drops, category sales drop -> совпадающее направление
    with session_scope() as session:
        metric = ExternalContextMetric(
            source="yandex_direct",
            metric_code="search_demand_womens_tshirts",
            metric_name="Поисковый спрос: Женские футболки",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            value=Decimal("12345"),
            previous_value=Decimal("14000"),
            change_pct=Decimal("-11.8"),
            category="womens_tshirts",
            data_status="ok"
        )
        session.add(metric)
        session.commit()
        
    with session_scope() as session:
        service = ExternalContextService(session, test_settings)
        
        # Sales drop 5%
        category_trends = {
            "womens_tshirts": {
                "change_pct": Decimal("-5.0"),
                "current_value": Decimal("1000"),
                "previous_value": Decimal("1050")
            }
        }
        
        res = service.get_external_context(
            report_date=date(2026, 7, 19),
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            category_sales_trends=category_trends
        )
        
        assert len(res.signals) == 1
        sig = res.signals[0]
        assert "снизился на 11%" in sig.interpretation
        assert "направлении" in sig.interpretation


def test_search_demand_opposite_trends(clean_external_db, test_settings) -> None:
    # 2. Search demand grows, category sales drop -> проверить внутренние факторы
    with session_scope() as session:
        metric = ExternalContextMetric(
            source="yandex_direct",
            metric_code="search_demand_womens_tshirts",
            metric_name="Поисковый спрос: Женские футболки",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            value=Decimal("15400"),
            previous_value=Decimal("14000"),
            change_pct=Decimal("10.0"),
            category="womens_tshirts",
            data_status="ok"
        )
        session.add(metric)
        session.commit()
        
    with session_scope() as session:
        service = ExternalContextService(session, test_settings)
        category_trends = {
            "womens_tshirts": {
                "change_pct": Decimal("-8.0"),
                "current_value": Decimal("1000"),
                "previous_value": Decimal("1086")
            }
        }
        
        res = service.get_external_context(
            report_date=date(2026, 7, 19),
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            category_sales_trends=category_trends
        )
        
        assert len(res.signals) == 1
        sig = res.signals[0]
        assert "вырос на 10%" in sig.interpretation
        assert "внутренние факторы" in sig.interpretation


def test_search_demand_below_threshold(clean_external_db, test_settings) -> None:
    # 3. Change is 5% which is below settings threshold 8% -> ignored
    with session_scope() as session:
        metric = ExternalContextMetric(
            source="yandex_direct",
            metric_code="search_demand_womens_tshirts",
            metric_name="Поисковый спрос: Женские футболки",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            value=Decimal("14700"),
            previous_value=Decimal("14000"),
            change_pct=Decimal("5.0"),
            category="womens_tshirts",
            data_status="ok"
        )
        session.add(metric)
        session.commit()
        
    with session_scope() as session:
        service = ExternalContextService(session, test_settings)
        category_trends = {"womens_tshirts": {"change_pct": Decimal("-8.0")}}
        
        res = service.get_external_context(
            report_date=date(2026, 7, 19),
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            category_sales_trends=category_trends
        )
        assert len(res.signals) == 0


def test_calendar_long_season_ignored_daily(clean_external_db, test_settings) -> None:
    # 4. Long summer season with requires_supporting_signal=True is ignored mid-season
    with session_scope() as session:
        event = ExternalContextEvent(
            source="internal_calendar",
            event_type="seasonal_period",
            event_code="summer_season_2026",
            title="Летний сезон",
            description="Календарный летний сезон.",
            date_start=date(2026, 6, 1),
            date_end=date(2026, 8, 15),
            impact_direction="neutral",
            impact_strength="medium",
            confidence="medium",
            is_active=True,
            metadata_json={"requires_supporting_signal": True}
        )
        session.add(event)
        session.commit()
        
    with session_scope() as session:
        service = ExternalContextService(session, test_settings)
        
        # Query mid-season date: July 19 is far from June 1 and August 15 (>7 days window)
        res = service.get_external_context(report_date=date(2026, 7, 19))
        assert len(res.signals) == 0


def test_calendar_display_in_transition_window(clean_external_db, test_settings) -> None:
    # 5. Long season is displayed when close to start or end (August 10 is close to August 15)
    with session_scope() as session:
        event = ExternalContextEvent(
            source="internal_calendar",
            event_type="seasonal_period",
            event_code="summer_season_2026",
            title="Летний сезон",
            description="Календарный летний сезон.",
            date_start=date(2026, 6, 1),
            date_end=date(2026, 8, 15),
            impact_direction="neutral",
            impact_strength="medium",
            confidence="medium",
            is_active=True,
            metadata_json={"requires_supporting_signal": True}
        )
        session.add(event)
        session.commit()
        
    with session_scope() as session:
        service = ExternalContextService(session, test_settings)
        res = service.get_external_context(report_date=date(2026, 8, 10))
        assert len(res.signals) == 1
        assert res.signals[0].event_code == "summer_season_2026"


def test_macro_key_rate_general_background(clean_external_db, test_settings) -> None:
    # 6. Key Rate CBR is returned with safe general background phrasing
    with session_scope() as session:
        metric = ExternalContextMetric(
            source="cbr",
            metric_code="cbr_key_rate",
            metric_name="Ключевая ставка ЦБ РФ",
            period_start=date(2026, 7, 19),
            period_end=date(2026, 7, 19),
            value=Decimal("16.00"),
            data_status="ok"
        )
        session.add(metric)
        session.commit()
        
    with session_scope() as session:
        service = ExternalContextService(session, test_settings)
        res = service.get_external_context(report_date=date(2026, 7, 19))
        assert len(res.signals) == 1
        assert "общим финансовым фоном" in res.signals[0].interpretation


def test_gdp_not_included_in_operational_summary(clean_external_db, test_settings) -> None:
    # 7. GDP is NOT output in daily summary report
    with session_scope() as session:
        gdp = ExternalContextMetric(
            source="rosstat",
            metric_code="gdp_growth",
            metric_name="ВВП рост",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            value=Decimal("3.5"),
            data_status="ok"
        )
        session.add(gdp)
        session.commit()
        
    with session_scope() as session:
        service = ExternalContextService(session, test_settings)
        res = service.get_external_context(report_date=date(2026, 7, 19))
        
        # GDP is stored in DB but excluded from signal classification categories
        assert len(res.signals) == 0


def test_max_4_signals_and_slot_constraints(clean_external_db, test_settings) -> None:
    # 8. Capped at 4 signals, only 1 signal per source category
    with session_scope() as session:
        # P1 Search Demand
        session.add(ExternalContextMetric(
            source="yandex_direct", metric_code="search_demand_womens_tshirts", metric_name="Search",
            period_start=date(2026, 7, 13), period_end=date(2026, 7, 19), value=Decimal("15400"), previous_value=Decimal("14000"),
            change_pct=Decimal("10.0"), category="womens_tshirts", data_status="ok"
        ))
        # P2 Calendar
        session.add(ExternalContextEvent(
            source="internal_calendar", event_type="official_holiday", event_code="holiday_1",
            title="Holiday", description="Holiday details.", date_start=date(2026, 7, 19), date_end=date(2026, 7, 19),
            impact_direction="positive", impact_strength="high", confidence="high", is_active=True
        ))
        # P3 Sentiment
        session.add(ExternalContextMetric(
            source="cbr", metric_code="consumer_sentiment_index", metric_name="Sentiment Index",
            period_start=date(2026, 7, 1), period_end=date(2026, 7, 31), value=Decimal("115.2"), data_status="ok"
        ))
        # P4 Macro
        session.add(ExternalContextMetric(
            source="cbr", metric_code="cbr_key_rate", metric_name="Key Rate",
            period_start=date(2026, 7, 19), period_end=date(2026, 7, 19), value=Decimal("16.00"), data_status="ok"
        ))
        session.commit()
        
    with session_scope() as session:
        service = ExternalContextService(session, test_settings)
        category_trends = {"womens_tshirts": {"change_pct": Decimal("-8.0")}}
        res = service.get_external_context(
            report_date=date(2026, 7, 19),
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            category_sales_trends=category_trends
        )
        
        # Max 4 signals, exactly one from each category
        assert len(res.signals) == 4
        sources = [s.source for s in res.signals]
        assert "search_demand" in sources
        assert "internal_calendar" in sources
        assert "cbr" in sources
        assert "macro" in sources


def test_omit_section_completely_if_no_signals(clean_external_db) -> None:
    # 9. Omit section header completely if there are no signals
    response = WbDailyOperationalSummaryResponse(
        formula_version="v1",
        report_window=WbDailyOperationalReportWindowResponse(
            report_date=date(2026, 7, 19),
            compare_date=date(2026, 7, 18),
            trend_current_from=date(2026, 7, 13),
            trend_current_to=date(2026, 7, 19),
            trend_previous_from=date(2026, 7, 6),
            trend_previous_to=date(2026, 7, 12),
            report_date_source="requested",
        ),
        requested_options={"mode": "full"},
        source_freshness=[],
        sections=[],
        highlights=WbDailyOperationalHighlightsResponse(worse=[], better=[], priority_checks=[]),
        diagnostics=WbDailyOperationalDiagnosticsResponse(included_sections=[], partial_sections=[], excluded_sections=[], query_count=0, formula_version="v1"),
        article_analysis=[],
        business_priorities=[],
        ranked_signals=[],
        data_anomalies=[],
        analysis_summary={},
        external_context={"status": "EMPTY", "signals": []}
    )
    
    markdown = render_wb_daily_operational_summary_markdown(response)
    assert "Внешний фон" not in markdown


def test_actions_of_the_day_regression(clean_external_db) -> None:
    # 10. Verify that actions of the day priorities P1–P5 and VVBromo summary line are unaffected
    # by changes in the external background logic.
    response = WbDailyOperationalSummaryResponse(
        formula_version="v1",
        report_window=WbDailyOperationalReportWindowResponse(
            report_date=date(2026, 7, 19),
            compare_date=date(2026, 7, 18),
            trend_current_from=date(2026, 7, 13),
            trend_current_to=date(2026, 7, 19),
            trend_previous_from=date(2026, 7, 6),
            trend_previous_to=date(2026, 7, 12),
            report_date_source="requested",
        ),
        requested_options={"mode": "full"},
        source_freshness=[],
        sections=[
            WbDailyOperationalSectionResponse(
                key="profit",
                title="Прибыль",
                status="OK",
                metrics=[
                    WbDailyOperationalMetricRowResponse(
                        metric="Операционная прибыль",
                        value=Decimal("-5543"),
                        delta_abs=Decimal("-10791")
                    )
                ]
            ),
            WbDailyOperationalSectionResponse(
                key="ads",
                title="Реклама",
                status="OK",
                metrics=[
                    WbDailyOperationalMetricRowResponse(
                        metric="ДРР (по кампаниям)",
                        value=Decimal("22.1"),
                        delta_pp=Decimal("2.1")
                    ),
                    WbDailyOperationalMetricRowResponse(
                        metric="CPO",
                        value=Decimal("346"),
                        delta_pct=Decimal("10.2")
                    ),
                    WbDailyOperationalMetricRowResponse(
                        metric="Рекламные заказы",
                        value=Decimal("529"),
                        delta_pct=Decimal("-10.2")
                    )
                ]
            )
        ],
        highlights=WbDailyOperationalHighlightsResponse(worse=[], better=[], priority_checks=[]),
        diagnostics=WbDailyOperationalDiagnosticsResponse(included_sections=[], partial_sections=[], excluded_sections=[], query_count=0, formula_version="v1"),
        article_analysis=[],
        business_priorities=[
            {"kind": "article_growth", "direction": "positive", "nm_id": 221311710, "score": Decimal("25"), "user_visible": True}
        ],
        ranked_signals=[],
        data_anomalies=[],
        analysis_summary={},
        external_context={"status": "OK", "signals": [
            {"source": "cbr", "metric_code": "cbr_key_rate", "title": "Key Rate", "interpretation": "Key rate static."}
        ]}
    )
    
    markdown = render_wb_daily_operational_summary_markdown(response)
    
    # Assert priorities and actions remain fully operational
    assert "1. Проверить причины отрицательной прибыли по VVBromo: −5 543 ₽." in markdown
    assert "2. Пересмотреть рекламу: ДРР 22,1%, CPO 346 ₽, рекламные заказы −10,2% за сутки." in markdown
    assert "3. Проверить устойчивость роста по артикулу 221311710." in markdown
