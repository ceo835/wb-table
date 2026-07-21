from __future__ import annotations

import os
import pytest

# Safety check and environment routing at the very top
test_db_url = os.getenv("TEST_DATABASE_URL")
if not test_db_url:
    raise RuntimeError("Safety Block: TEST_DATABASE_URL environment variable is not configured. Run blocked.")

if "rlwy.net" in test_db_url or "railway" in test_db_url:
    raise RuntimeError("Safety Block: TEST_DATABASE_URL contains Railway production database host! Run blocked to protect production data.")

os.environ["DATABASE_URL"] = test_db_url
os.environ["MCP_AUTH_TOKEN"] = "test"

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.db.models import ExternalContextEvent, ExternalContextMetric
from src.db.session import session_scope
from src.mcp_server.settings import McpServiceSettings
from src.services.external_context.service import ExternalContextService
from src.services.external_context.schemas import ExternalContextRequest
from src.mcp_server.wb_daily_operational_summary_format import render_wb_daily_operational_summary_markdown
from src.mcp_server.schemas import (
    WbDailyOperationalSummaryResponse,
    WbDailyOperationalReportWindowResponse,
    WbDailyOperationalHighlightsResponse,
    WbDailyOperationalDiagnosticsResponse,
    WbDailyOperationalSectionResponse,
    WbDailyOperationalMetricRowResponse,
)


@pytest.fixture(scope="session")
def shared_engine():
    from src.db.connection import create_db_engine
    from src.db.models import Base
    engine = create_db_engine(os.environ["DATABASE_URL"])
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def clean_external_db(shared_engine):
    with session_scope(shared_engine) as session:
        session.query(ExternalContextEvent).delete()
        session.query(ExternalContextMetric).delete()
        session.commit()
    yield
    with session_scope(shared_engine) as session:
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


# 1. Consumer Sentiment displayed within 7 days of published_at
def test_consumer_sentiment_displayed_within_freshness_window(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 15, 10, 0)
    with session_scope(shared_engine) as session:
        session.add(ExternalContextMetric(
            source="cbr",
            metric_code="consumer_sentiment_index",
            metric_name="Индекс потребительских настроений",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 15),
            published_at=pub_dt,
            value=Decimal("115.2"),
            previous_value=Decimal("112.0"),
            change_value=Decimal("3.2"),
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        # Report date on Day 4 after publication (July 19)
        res = service.get_external_context(report_date=date(2026, 7, 19))
        assert len(res.signals) == 1
        assert res.signals[0].interpretation == "Индекс потребительских настроений вырос до 115,2 пункта."


# 2. Consumer Sentiment NOT displayed after 7 days (Day 8+)
def test_consumer_sentiment_not_displayed_after_freshness_window_expires(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 10, 10, 0)
    with session_scope(shared_engine) as session:
        session.add(ExternalContextMetric(
            source="cbr",
            metric_code="consumer_sentiment_index",
            metric_name="Индекс потребительских настроений",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 10),
            published_at=pub_dt,
            value=Decimal("115.2"),
            previous_value=Decimal("112.0"),
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        # Report date on Day 9 after publication (July 19) -> expired!
        res = service.get_external_context(report_date=date(2026, 7, 19))
        assert len(res.signals) == 0


# 3. Inflation displayed within 7 days of published_at
def test_inflation_displayed_within_freshness_window(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 17, 12, 0)
    with session_scope(shared_engine) as session:
        session.add(ExternalContextMetric(
            source="rosstat",
            metric_code="inflation_rate",
            metric_name="Инфляция (годовая)",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 17),
            published_at=pub_dt,
            value=Decimal("8.6"),
            previous_value=Decimal("8.1"),
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        # Day 2 after publication
        res = service.get_external_context(report_date=date(2026, 7, 19))
        assert len(res.signals) == 1
        assert res.signals[0].interpretation == "Годовая инфляция ускорилась до 8,6%."


# 4. Inflation NOT repeated indefinitely (after Day 7)
def test_inflation_not_repeated_indefinitely(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 1, 12, 0)
    with session_scope(shared_engine) as session:
        session.add(ExternalContextMetric(
            source="rosstat",
            metric_code="inflation_rate",
            metric_name="Инфляция (годовая)",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            published_at=pub_dt,
            value=Decimal("8.6"),
            previous_value=Decimal("8.1"),
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        # Day 18 after publication -> expired!
        res = service.get_external_context(report_date=date(2026, 7, 19))
        assert len(res.signals) == 0


# 5. Wording with previous value (вырос / снизился / ускорилась / замедлилась)
def test_wording_with_previous_value(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 18, 10, 0)
    with session_scope(shared_engine) as session:
        # Sentiment drop
        session.add(ExternalContextMetric(
            source="cbr", metric_code="consumer_sentiment_index", metric_name="Sentiment",
            period_start=date(2026, 7, 1), period_end=date(2026, 7, 18), published_at=pub_dt,
            value=Decimal("98.4"), previous_value=Decimal("102.1"), data_status="ok"
        ))
        # Inflation slowdown
        session.add(ExternalContextMetric(
            source="rosstat", metric_code="inflation_rate", metric_name="Inflation",
            period_start=date(2026, 7, 1), period_end=date(2026, 7, 18), published_at=pub_dt,
            value=Decimal("8.1"), previous_value=Decimal("8.6"), data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        res = service.get_external_context(report_date=date(2026, 7, 19))
        assert len(res.signals) == 2
        text_sentiment = res.signals[0].interpretation
        text_inflation = res.signals[1].interpretation
        assert " снизился до 98,4 пункта." in text_sentiment
        assert " замедлилась до 8,1%." in text_inflation


# 6. Wording WITHOUT previous value (neutral: составил / составила)
def test_wording_without_previous_value(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 18, 10, 0)
    with session_scope(shared_engine) as session:
        # Sentiment no previous value
        session.add(ExternalContextMetric(
            source="cbr", metric_code="consumer_sentiment_index", metric_name="Sentiment",
            period_start=date(2026, 7, 1), period_end=date(2026, 7, 18), published_at=pub_dt,
            value=Decimal("115.2"), previous_value=None, data_status="ok"
        ))
        # Inflation no previous value
        session.add(ExternalContextMetric(
            source="rosstat", metric_code="inflation_rate", metric_name="Inflation",
            period_start=date(2026, 7, 1), period_end=date(2026, 7, 18), published_at=pub_dt,
            value=Decimal("8.6"), previous_value=None, data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        res = service.get_external_context(report_date=date(2026, 7, 19))
        assert len(res.signals) == 2
        text_sentiment = res.signals[0].interpretation
        text_inflation = res.signals[1].interpretation
        assert " составил 115,2 пункта." in text_sentiment
        assert "не увеличился" not in text_sentiment and "вырос" not in text_sentiment
        assert " составила 8,6%." in text_inflation


# 7. Maximum 2 lines in "Внешний фон"
def test_max_two_external_context_lines(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 18, 10, 0)
    with session_scope(shared_engine) as session:
        # P1 Wordstat
        session.add(ExternalContextMetric(
            source="yandex_direct", metric_code="search_demand_womens_tshirts", metric_name="Wordstat",
            period_start=date(2026, 7, 13), period_end=date(2026, 7, 19), value=Decimal("15000"), previous_value=Decimal("13000"),
            change_pct=Decimal("15.0"), category="womens_tshirts", data_status="ok"
        ))
        # P2 Calendar
        session.add(ExternalContextEvent(
            source="internal_calendar", event_type="sale", event_code="summer_sale", title="Распродажа",
            description="Летняя распродажа одежды", date_start=date(2026, 7, 18), date_end=date(2026, 7, 20), is_active=True
        ))
        # P3 Sentiment
        session.add(ExternalContextMetric(
            source="cbr", metric_code="consumer_sentiment_index", metric_name="Sentiment",
            period_start=date(2026, 7, 1), period_end=date(2026, 7, 18), published_at=pub_dt,
            value=Decimal("115.2"), previous_value=Decimal("110.0"), data_status="ok"
        ))
        # P4 Inflation
        session.add(ExternalContextMetric(
            source="rosstat", metric_code="inflation_rate", metric_name="Inflation",
            period_start=date(2026, 7, 1), period_end=date(2026, 7, 18), published_at=pub_dt,
            value=Decimal("8.6"), previous_value=Decimal("8.1"), data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        res = service.get_external_context(report_date=date(2026, 7, 19), max_signals=2)
        assert len(res.signals) == 2
        # Highest priority items only (Wordstat & Calendar)
        assert res.signals[0].source == "search_demand"
        assert res.signals[1].source == "internal_calendar"


# 8. Wordstat priority higher than Inflation
def test_wordstat_priority_over_inflation(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 18, 10, 0)
    with session_scope(shared_engine) as session:
        # Wordstat (P1)
        session.add(ExternalContextMetric(
            source="yandex_direct", metric_code="search_demand_womens_tshirts", metric_name="Wordstat",
            period_start=date(2026, 7, 13), period_end=date(2026, 7, 19), value=Decimal("15000"), previous_value=Decimal("13000"),
            change_pct=Decimal("15.0"), category="womens_tshirts", data_status="ok"
        ))
        # Inflation (P4)
        session.add(ExternalContextMetric(
            source="rosstat", metric_code="inflation_rate", metric_name="Inflation",
            period_start=date(2026, 7, 1), period_end=date(2026, 7, 18), published_at=pub_dt,
            value=Decimal("8.6"), previous_value=Decimal("8.1"), data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        res = service.get_external_context(report_date=date(2026, 7, 19), max_signals=1)
        assert len(res.signals) == 1
        assert res.signals[0].source == "search_demand"


# 9. Hide section when no active signals exist
def test_section_hidden_when_no_active_signals(clean_external_db) -> None:
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


# 10. Idempotent load preserves published_at
def test_idempotent_load_does_not_update_published_at(clean_external_db, shared_engine, monkeypatch) -> None:
    pub_dt = datetime(2026, 7, 10, 10, 0)
    with session_scope(shared_engine) as session:
        metric = ExternalContextMetric(
            source="rosstat",
            metric_code="inflation_rate",
            metric_name="Инфляция (годовая)",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            published_at=pub_dt,
            value=Decimal("8.57"),
            previous_value=Decimal("8.30"),
            change_pct=Decimal("3.25"),
            data_status="ok"
        )
        session.add(metric)
        session.commit()

    from scripts import load_external_macro_metrics
    monkeypatch.setattr(load_external_macro_metrics.CbrMacroAdapter, "fetch_key_rate", lambda self, s, e: [])

    # Run macro loader to attempt re-inserting identical data
    class Args:
        dry_run = False
    import argparse
    orig_parse = argparse.ArgumentParser.parse_args
    argparse.ArgumentParser.parse_args = lambda self: Args()

    try:
        load_external_macro_metrics.main()
    finally:
        argparse.ArgumentParser.parse_args = orig_parse

    with session_scope(shared_engine) as session:
        metric = session.query(ExternalContextMetric).filter_by(metric_code="inflation_rate").one()
        assert metric.published_at == pub_dt


# 11. Other report sections remain unaffected
def test_other_report_sections_unaffected(clean_external_db) -> None:
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
            )
        ],
        highlights=WbDailyOperationalHighlightsResponse(worse=[], better=[], priority_checks=[]),
        diagnostics=WbDailyOperationalDiagnosticsResponse(included_sections=[], partial_sections=[], excluded_sections=[], query_count=0, formula_version="v1"),
        article_analysis=[],
        business_priorities=[],
        ranked_signals=[],
        data_anomalies=[],
        analysis_summary={},
        external_context={"status": "OK", "signals": []}
    )

    markdown = render_wb_daily_operational_summary_markdown(response)
    assert "Проверить причины отрицательной прибыли" in markdown


# 12. Recently loaded OLD calendar event is NOT displayed
def test_recently_loaded_old_calendar_event_not_displayed(clean_external_db, test_settings, shared_engine) -> None:
    # Event happened in June, but created_at / updated_at in DB is today (July 19)
    with session_scope(shared_engine) as session:
        session.add(ExternalContextEvent(
            source="internal_calendar",
            event_type="holiday",
            event_code="june_holiday",
            title="Прошедший праздник июня",
            description="Описание июньского праздника",
            date_start=date(2026, 6, 12),
            date_end=date(2026, 6, 12),
            is_active=True,
            created_at=datetime(2026, 7, 19, 10, 0),
            updated_at=datetime(2026, 7, 19, 10, 0),
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        res = service.get_external_context(report_date=date(2026, 7, 19))
        assert len(res.signals) == 0


# 13. Recently refetched OLD Wordstat period does NOT become active
def test_recently_refetched_old_wordstat_period_not_displayed(clean_external_db, test_settings, shared_engine) -> None:
    # Wordstat period ended in June, but retrieved_at is today
    with session_scope(shared_engine) as session:
        session.add(ExternalContextMetric(
            source="yandex_direct",
            metric_code="search_demand_womens_tshirts",
            metric_name="Поисковый спрос",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 15),
            retrieved_at=datetime(2026, 7, 19, 10, 0),
            value=Decimal("15000"),
            previous_value=Decimal("12000"),
            change_pct=Decimal("25.0"),
            category="womens_tshirts",
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        res = service.get_external_context(report_date=date(2026, 7, 19))
        assert len(res.signals) == 0


# 14. fresh_until calculated per signal source type
def test_fresh_until_calculated_per_signal_type(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 15, 10, 0)
    with session_scope(shared_engine) as session:
        # Sentiment
        session.add(ExternalContextMetric(
            source="cbr", metric_code="consumer_sentiment_index", metric_name="Sentiment",
            period_start=date(2026, 7, 1), period_end=date(2026, 7, 15), published_at=pub_dt,
            value=Decimal("115.2"), previous_value=Decimal("110.0"), data_status="ok"
        ))
        # Calendar event (Jul 18 to Jul 19)
        session.add(ExternalContextEvent(
            source="internal_calendar", event_type="sale", event_code="sale_jul", title="Sale",
            description="July Sale", date_start=date(2026, 7, 18), date_end=date(2026, 7, 19), is_active=True
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        res = service.get_external_context(report_date=date(2026, 7, 19), max_signals=2)
        assert len(res.signals) == 2
        sig_calendar = res.signals[0]
        sig_sentiment = res.signals[1]

        # Calendar fresh_until = date_end + 2d = 2026-07-21
        assert sig_calendar.fresh_until == date(2026, 7, 21)
        # Sentiment fresh_until = pub_date + 7d = 2026-07-22
        assert sig_sentiment.fresh_until == date(2026, 7, 22)
