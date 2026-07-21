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
        cat_trends = {"womens_tshirts": {"change_pct": Decimal("-8.0")}}
        res = service.get_external_context(report_date=date(2026, 7, 19), max_signals=2, category_sales_trends=cat_trends)
        assert len(res.signals) == 2
        # Highest priority items only (Category-matched Wordstat & Calendar)
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
        cat_trends = {"womens_tshirts": {"change_pct": Decimal("-8.0")}}
        res = service.get_external_context(report_date=date(2026, 7, 19), max_signals=1, category_sales_trends=cat_trends)
        assert len(res.signals) == 1
        assert res.signals[0].source == "search_demand"


# 9. No significant signals displays neutral line
def test_no_significant_signals_displays_neutral_line(clean_external_db) -> None:
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
        external_context={"status": "EMPTY", "external_context_status": "no_significant_signals", "signals": []}
    )

    markdown = render_wb_daily_operational_summary_markdown(response)
    assert "## Внешний фон" in markdown
    assert "— Значимых новых внешних сигналов на дату отчёта нет." in markdown


def test_sources_unavailable_displays_unavailable_line(clean_external_db) -> None:
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
        external_context={"status": "UNAVAILABLE", "external_context_status": "sources_unavailable", "signals": []}
    )

    markdown = render_wb_daily_operational_summary_markdown(response)
    assert "## Внешний фон" in markdown
    assert "— Внешние данные временно недоступны." in markdown


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


# 15. Wordstat without category matching and <25% change stays in diagnostic, not in top signals
def test_wordstat_unmatched_normal_change_stays_in_diagnostic(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 15, 10, 0)
    with session_scope(shared_engine) as session:
        session.add(ExternalContextMetric(
            source="yandex_direct",
            metric_code="search_demand_womens_tshirts",
            metric_name="Wordstat",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("15000"),
            previous_value=Decimal("13000"),
            change_pct=Decimal("15.0"),
            category="womens_tshirts",
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        # Without category_sales_trends
        res = service.get_external_context(report_date=date(2026, 7, 19), diagnostic=True)
        # Main signals do not include this normal standalone Wordstat change
        assert len(res.signals) == 0
        # But diagnostic details contain it with is_selectable=False
        wordstat_diags = [d for d in res.diagnostics.get("exclusion_reasons", []) if d.get("wordstat_category") == "womens_tshirts"]
        assert len(wordstat_diags) == 1
        assert wordstat_diags[0]["is_selectable"] is False
        assert wordstat_diags[0]["selection_reason"] == "standalone_normal_change_diagnostic_only"


# 16. Wordstat wording contains 'в Яндексе'
def test_wordstat_phrasing_contains_yandex(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 15, 10, 0)
    with session_scope(shared_engine) as session:
        session.add(ExternalContextMetric(
            source="yandex_direct",
            metric_code="search_demand_womens_tshirts",
            metric_name="Wordstat",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("15000"),
            previous_value=Decimal("10000"),
            change_pct=Decimal("50.0"),  # strong change >= 25.0%
            category="womens_tshirts",
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        res = service.get_external_context(report_date=date(2026, 7, 19))
        assert len(res.signals) == 1
        assert "в Яндексе" in res.signals[0].interpretation
        assert "Внешний поисковый интерес в Яндексе к женским футболкам вырос на 50%." == res.signals[0].interpretation


# 17. Category comparison strictly uses same category, not general store turnover
def test_wordstat_category_comparison_strict_same_category(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 15, 10, 0)
    with session_scope(shared_engine) as session:
        session.add(ExternalContextMetric(
            source="yandex_direct",
            metric_code="search_demand_womens_tshirts",
            metric_name="Wordstat",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("15000"),
            previous_value=Decimal("13000"),
            change_pct=Decimal("15.0"),
            category="womens_tshirts",
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        # Passing category_sales_trends for DIFFERENT category ('womens_underwear') or total store
        cat_trends_other = {"womens_underwear": {"change_pct": Decimal("-10.0")}, "total_store": {"change_pct": Decimal("-20.0")}}
        res_other = service.get_external_context(report_date=date(2026, 7, 19), category_sales_trends=cat_trends_other, diagnostic=True)
        # Since 'womens_tshirts' is NOT in cat_trends_other, it is NOT category matched
        assert len(res_other.signals) == 0

        # Now pass matching category 'womens_tshirts'
        cat_trends_matched = {"womens_tshirts": {"change_pct": Decimal("-8.0")}}
        res_matched = service.get_external_context(report_date=date(2026, 7, 19), category_sales_trends=cat_trends_matched, diagnostic=True)
        assert len(res_matched.signals) == 1
        assert "при этом поисковые заказы категории на WB снизились на 8%." in res_matched.signals[0].interpretation


# 18. Future published_at handling (exclusion reason published_after_report_date, status unaffected)
def test_future_published_at_not_selected(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 31, 10, 0)  # Future publication relative to report_date 2026-07-19
    with session_scope(shared_engine) as session:
        session.add(ExternalContextMetric(
            source="cbr",
            metric_code="consumer_sentiment_index",
            metric_name="Sentiment",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            published_at=pub_dt,
            value=Decimal("115.2"),
            previous_value=Decimal("110.0"),
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        # Report date on 2026-07-19 -> publication is in the future (2026-07-31)
        res = service.get_external_context(report_date=date(2026, 7, 19), diagnostic=True)
        assert len(res.signals) == 0
        assert res.external_context_status == "no_significant_signals"
        
        ex_reasons = res.diagnostics.get("exclusion_reasons", [])
        cbr_ex = [x for x in ex_reasons if x.get("metric_code") == "consumer_sentiment_index"]
        assert len(cbr_ex) == 1
        assert cbr_ex[0]["excluded_reason"] == "published_after_report_date"

        # On publication date (2026-07-31), standard 7-day window applies and signal IS selected
        res_pub_day = service.get_external_context(report_date=date(2026, 7, 31), diagnostic=True)
        assert len(res_pub_day.signals) == 1
        assert res_pub_day.external_context_status == "signals_available"


# 19. Detailed Wordstat comparison formulation and direction tests
def test_wordstat_formulation_matrix_and_directions(clean_external_db, test_settings, shared_engine) -> None:
    with session_scope(shared_engine) as session:
        # Metric with +33.2% change (growth)
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_womens_tshirts",
            metric_name="Wordstat",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            value=Decimal("3985"),
            previous_value=Decimal("2992"),
            change_pct=Decimal("33.2"),
            category="womens_tshirts",
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)

        # Test A: +33.2% external and near-zero WB (+0.4% WB)
        cat_trends_stable = {"womens_tshirts": {"change_pct": Decimal("0.4")}}
        res_stable = service.get_external_context(report_date=date(2026, 7, 19), category_sales_trends=cat_trends_stable, diagnostic=True)
        assert len(res_stable.signals) == 1
        interp_stable = res_stable.signals[0].interpretation
        assert "вырос на 33%" in interp_stable
        assert "растут на 0%" not in interp_stable
        assert "снижение" not in interp_stable
        assert "продажи категории на WB практически не изменились" in interp_stable

        # Test B: +33.2% external and None WB change -> standalone
        res_none = service.get_external_context(report_date=date(2026, 7, 19), category_sales_trends=None, diagnostic=True)
        assert len(res_none.signals) == 1
        assert res_none.signals[0].interpretation == "Внешний поисковый интерес в Яндексе к женским футболкам вырос на 33%."

        # Test C: Negative external (-33.2%) and positive WB (+10.0%) -> divergent
        with session_scope(shared_engine) as session_neg:
            m = session_neg.query(ExternalContextMetric).filter_by(metric_code="search_demand_womens_tshirts").first()
            m.change_pct = Decimal("-33.2")
            session_neg.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        cat_trends_div = {"womens_tshirts": {"change_pct": Decimal("10.0")}}
        res_div = service.get_external_context(report_date=date(2026, 7, 19), category_sales_trends=cat_trends_div, diagnostic=True)
        assert len(res_div.signals) == 1
        interp_div = res_div.signals[0].interpretation
        assert "вопреки снижению внешнего поискового интереса в Яндексе на 33%" in interp_div
        assert "вырос на" not in interp_div


# 20. Strict 1-to-1 mapping verification between category_code and subject
def test_category_code_strict_1to1_subject_mapping(clean_external_db, test_settings, shared_engine) -> None:
    with session_scope(shared_engine) as session:
        # Metric for womens_tshirts
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_womens_tshirts",
            metric_name="Wordstat",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            value=Decimal("3985"),
            previous_value=Decimal("2992"),
            change_pct=Decimal("33.2"),
            category="womens_tshirts",
            data_status="ok"
        ))
        # Metric for womens_underwear
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_womens_underwear",
            metric_name="Wordstat",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            value=Decimal("5000"),
            previous_value=Decimal("4000"),
            change_pct=Decimal("25.0"),
            category="womens_underwear",
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)

        # Strict trends dictionary: womens_tshirts trend != womens_underwear trend
        cat_trends = {
            "womens_tshirts": {"change_pct": Decimal("-26.59"), "orders": 2796},
            "womens_underwear": {"change_pct": Decimal("-12.41"), "orders": 2965},
            "childrens_underwear": {"change_pct": Decimal("0.0"), "orders": 0},
            "childrens_tshirts": {"change_pct": Decimal("0.0"), "orders": 0},
        }

        res = service.get_external_context(report_date=date(2026, 7, 19), category_sales_trends=cat_trends, diagnostic=True)
        assert len(res.signals) == 2

        tshirt_sig = next(s for s in res.signals if s.category == "womens_tshirts")
        underwear_sig = next(s for s in res.signals if s.category == "womens_underwear")

        # Verify tshirt_sig matches ONLY womens_tshirts trend (-26.59% -> 27%)
        assert "поисковые заказы категории на WB снизились на 27%" in tshirt_sig.interpretation
        assert "12%" not in tshirt_sig.interpretation

        # Verify underwear_sig matches ONLY womens_underwear trend (-12.41% -> 12%)
        assert "поисковые заказы категории на WB снизились на 12%" in underwear_sig.interpretation
        assert "27%" not in underwear_sig.interpretation


# 20. Four fixed categories, Wordstat loader requirements & signal prioritization
def test_four_fixed_categories_wordstat_loader_and_signals(clean_external_db, test_settings, shared_engine) -> None:
    from src.services.external_context.category_config import CATEGORIES_CONFIG, get_active_categories

    active_cats = get_active_categories()
    assert len(active_cats) == 4
    cat_codes = [c["category_code"] for c in active_cats]
    assert set(cat_codes) == {"womens_tshirts", "childrens_tshirts", "womens_underwear", "childrens_underwear"}

    # Check search queries map to single required query per category
    query_map = {c["category_code"]: c["search_queries"] for c in active_cats}
    assert query_map["womens_tshirts"] == ["женские футболки"]
    assert query_map["childrens_tshirts"] == ["детские футболки"]
    assert query_map["womens_underwear"] == ["женские трусы"]
    assert query_map["childrens_underwear"] == ["детские трусы"]

    pub_dt = datetime(2026, 7, 15, 10, 0)
    with session_scope(shared_engine) as session:
        # womens_tshirts: divergent (Yandex +30%, WB -15%) -> Priority 1 (Discrepancy)
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_womens_tshirts",
            metric_name="Поисковый спрос: Женские футболки",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("13000"),
            previous_value=Decimal("10000"),
            change_pct=Decimal("30.0"),
            category="womens_tshirts",
            data_status="ok"
        ))
        # childrens_tshirts: matching growth (Yandex +20%, WB +20%)
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_childrens_tshirts",
            metric_name="Поисковый спрос: Детские футболки",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("12000"),
            previous_value=Decimal("10000"),
            change_pct=Decimal("20.0"),
            category="childrens_tshirts",
            data_status="ok"
        ))
        # womens_underwear: matching growth (Yandex +15%, WB +15%)
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_womens_underwear",
            metric_name="Поисковый спрос: Женское белье",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("11500"),
            previous_value=Decimal("10000"),
            change_pct=Decimal("15.0"),
            category="womens_underwear",
            data_status="ok"
        ))
        # childrens_underwear: weak change (Yandex +5% < min threshold 8%)
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_childrens_underwear",
            metric_name="Поисковый спрос: Детское белье",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("10500"),
            previous_value=Decimal("10000"),
            change_pct=Decimal("5.0"),
            category="childrens_underwear",
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        cat_trends = {
            "womens_tshirts": {"change_pct": Decimal("-15.0")},
            "childrens_tshirts": {"change_pct": Decimal("20.0")},
            "womens_underwear": {"change_pct": Decimal("15.0")},
            "childrens_underwear": {"change_pct": Decimal("5.0")},
        }

        res = service.get_external_context(report_date=date(2026, 7, 19), category_sales_trends=cat_trends, max_signals=2, diagnostic=True)

        # Max 2 signals returned
        assert len(res.signals) <= 2

        # Discrepancy signal (womens_tshirts) MUST be first due to priority
        assert res.signals[0].category == "womens_tshirts"
        assert "вырос на 30%" in res.signals[0].interpretation
        assert "снизились на 15%" in res.signals[0].interpretation

        # All signals must contain 'в Яндексе'
        for sig in res.signals:
            assert "в Яндексе" in sig.interpretation

        # Weak change (childrens_underwear 5%) must be excluded
        assert not any(s.category == "childrens_underwear" for s in res.signals)


# 21. Category with previous_orders = 0 and change_pct = None test for comparison_available = False
def test_category_with_none_change_pct_diagnostic_flag(clean_external_db, test_settings, shared_engine) -> None:
    pub_dt = datetime(2026, 7, 15, 10, 0)
    with session_scope(shared_engine) as session:
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_childrens_tshirts",
            metric_name="Поисковый спрос: Детские футболки",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("8537"),
            previous_value=Decimal("6292"),
            change_pct=Decimal("35.7"),
            category="childrens_tshirts",
            data_status="ok"
        ))
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_womens_tshirts",
            metric_name="Поисковый спрос: Женские футболки",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("59069"),
            previous_value=Decimal("42759"),
            change_pct=Decimal("38.1"),
            category="womens_tshirts",
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        # childrens_tshirts has previous_orders = 0 and change_pct = None
        # womens_tshirts has previous_orders = 3809 and change_pct = -26.59
        cat_trends = {
            "childrens_tshirts": {"subject": "Футболки детские", "current_orders": Decimal("0"), "previous_orders": Decimal("0"), "change_pct": None},
            "womens_tshirts": {"subject": "Футболки", "current_orders": Decimal("2796"), "previous_orders": Decimal("3809"), "change_pct": Decimal("-26.59")},
        }

        res = service.get_external_context(report_date=date(2026, 7, 19), category_sales_trends=cat_trends, diagnostic=True)

        diags = {d["wordstat_category"]: d for d in res.diagnostics.get("candidate_evaluations", []) if "wordstat_category" in d}

        # childrens_tshirts: wb_change_pct is None -> comparison_available = False, comparison_direction = "standalone"
        child_diag = diags["childrens_tshirts"]
        assert child_diag["wb_change_pct"] is None
        assert child_diag["comparison_available"] is False
        assert child_diag["comparison_direction"] == "standalone"

        # womens_tshirts: wb_change_pct is numeric -> comparison_available = True
        women_diag = diags["womens_tshirts"]
        assert women_diag["wb_change_pct"] == -26.59
        assert women_diag["comparison_available"] is True
        assert women_diag["comparison_direction"] == "divergent"


# 22. Limit 6 signals and multi-source coexistence (Wordstat + Calendar + Sentiment + Inflation)
def test_max_signals_limit_six_and_multi_source_coexistence(clean_external_db, test_settings, shared_engine) -> None:
    report_dt = date(2026, 7, 19)
    pub_dt = datetime(2026, 7, 15, 10, 0)
    with session_scope(shared_engine) as session:
        # Wordstat signal 1
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_womens_underwear",
            metric_name="Поисковый спрос: Женское белье",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("55439"),
            previous_value=Decimal("38481"),
            change_pct=Decimal("44.1"),
            category="womens_underwear",
            data_status="ok"
        ))
        # Wordstat signal 2
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_womens_tshirts",
            metric_name="Поисковый спрос: Женские футболки",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("59069"),
            previous_value=Decimal("42759"),
            change_pct=Decimal("38.1"),
            category="womens_tshirts",
            data_status="ok"
        ))
        # Calendar Event (active window)
        session.add(ExternalContextEvent(
            source="internal_calendar",
            event_code="summer_sale_2026",
            event_type="sale",
            title="Летняя распродажа",
            description="Большая летняя распродажа на маркетплейсах",
            date_start=date(2026, 7, 18),
            date_end=date(2026, 7, 21),
            is_active=True
        ))
        # Sentiment Index (fresh: published 2026-07-15 <= 7 days from 2026-07-19)
        session.add(ExternalContextMetric(
            source="cbr",
            metric_code="consumer_sentiment_index",
            metric_name="Индекс потребительских настроений",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 15),
            published_at=pub_dt,
            value=Decimal("108.5"),
            previous_value=Decimal("105.0"),
            change_pct=Decimal("3.3"),
            data_status="ok"
        ))
        # Inflation rate (fresh: published 2026-07-15 <= 7 days from 2026-07-19)
        session.add(ExternalContextMetric(
            source="rosstat",
            metric_code="inflation_rate",
            metric_name="Годовая инфляция",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 15),
            published_at=pub_dt,
            value=Decimal("8.2"),
            previous_value=Decimal("8.5"),
            change_pct=Decimal("-3.5"),
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        cat_trends = {
            "womens_underwear": {"subject": "Трусы", "current_orders": Decimal("2965"), "previous_orders": Decimal("3385"), "change_pct": Decimal("-12.41")},
            "womens_tshirts": {"subject": "Футболки", "current_orders": Decimal("2796"), "previous_orders": Decimal("3809"), "change_pct": Decimal("-26.59")},
        }

        res = service.get_external_context(report_date=report_dt, category_sales_trends=cat_trends, max_signals=6)

        # All 5 available signals (2 Wordstat + 1 Calendar + 1 Sentiment + 1 Inflation) must coexist without displacement
        assert len(res.signals) == 5
        sources = {s.source for s in res.signals}
        assert sources == {"search_demand", "internal_calendar", "cbr", "rosstat"}


# 23. Stale sentiment and inflation metrics (>7 days) drop off
def test_stale_macro_metrics_outside_seven_day_window_excluded(clean_external_db, test_settings, shared_engine) -> None:
    report_dt = date(2026, 7, 25)  # 10 days after published_at 2026-07-15
    pub_dt = datetime(2026, 7, 15, 10, 0)
    with session_scope(shared_engine) as session:
        session.add(ExternalContextMetric(
            source="cbr",
            metric_code="consumer_sentiment_index",
            metric_name="Индекс потребительских настроений",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 15),
            published_at=pub_dt,
            value=Decimal("108.5"),
            previous_value=Decimal("105.0"),
            change_pct=Decimal("3.3"),
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        res = service.get_external_context(report_date=report_dt, max_signals=6, diagnostic=True)

        assert len(res.signals) == 0
        assert res.external_context_status == "no_significant_signals"
        excluded = [d for d in res.diagnostics.get("candidate_evaluations", []) if d.get("metric_code") == "consumer_sentiment_index"]
        assert len(excluded) == 1
        assert excluded[0]["excluded_reason"] == "outside_7day_freshness_window"


# 24. 4 active Wordstat candidates + calendar + sentiment + inflation -> 2 Wordstat and all 3 other sources selected
def test_four_wordstat_candidates_plus_other_sources_outputs_two_wordstat_and_all_others(clean_external_db, test_settings, shared_engine) -> None:
    report_dt = date(2026, 7, 19)
    pub_dt = datetime(2026, 7, 15, 10, 0)
    with session_scope(shared_engine) as session:
        # Wordstat candidate 1 (divergent)
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_womens_underwear",
            metric_name="Поисковый спрос: Женские трусы",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("55439"),
            previous_value=Decimal("38481"),
            change_pct=Decimal("44.1"),
            category="womens_underwear",
            data_status="ok"
        ))
        # Wordstat candidate 2 (divergent)
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_womens_tshirts",
            metric_name="Поисковый спрос: Женские футболки",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("59069"),
            previous_value=Decimal("42759"),
            change_pct=Decimal("38.1"),
            category="womens_tshirts",
            data_status="ok"
        ))
        # Wordstat candidate 3 (standalone strong)
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_childrens_underwear",
            metric_name="Поисковый спрос: Детские трусы",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("15200"),
            previous_value=Decimal("11030"),
            change_pct=Decimal("37.8"),
            category="childrens_underwear",
            data_status="ok"
        ))
        # Wordstat candidate 4 (standalone strong)
        session.add(ExternalContextMetric(
            source="yandex_cloud_wordstat",
            metric_code="search_demand_childrens_tshirts",
            metric_name="Поисковый спрос: Детские футболки",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_dt,
            value=Decimal("25800"),
            previous_value=Decimal("19020"),
            change_pct=Decimal("35.7"),
            category="childrens_tshirts",
            data_status="ok"
        ))
        # Calendar Event
        session.add(ExternalContextEvent(
            source="internal_calendar",
            event_code="summer_sale_2026",
            event_type="sale",
            title="Летняя распродажа",
            description="Большая летняя распродажа на маркетплейсах",
            date_start=date(2026, 7, 18),
            date_end=date(2026, 7, 21),
            is_active=True
        ))
        # Sentiment Index
        session.add(ExternalContextMetric(
            source="cbr",
            metric_code="consumer_sentiment_index",
            metric_name="Индекс потребительских настроений",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 15),
            published_at=pub_dt,
            value=Decimal("108.5"),
            previous_value=Decimal("105.0"),
            change_pct=Decimal("3.3"),
            data_status="ok"
        ))
        # Inflation rate
        session.add(ExternalContextMetric(
            source="rosstat",
            metric_code="inflation_rate",
            metric_name="Годовая инфляция",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 15),
            published_at=pub_dt,
            value=Decimal("8.2"),
            previous_value=Decimal("8.5"),
            change_pct=Decimal("-3.5"),
            data_status="ok"
        ))
        session.commit()

    with session_scope(shared_engine) as session:
        service = ExternalContextService(session, test_settings)
        cat_trends = {
            "womens_underwear": {"subject": "Трусы", "current_orders": Decimal("2965"), "previous_orders": Decimal("3385"), "change_pct": Decimal("-12.41")},
            "womens_tshirts": {"subject": "Футболки", "current_orders": Decimal("2796"), "previous_orders": Decimal("3809"), "change_pct": Decimal("-26.59")},
            "childrens_underwear": {"subject": "Трусы детские", "current_orders": Decimal("0"), "previous_orders": Decimal("0"), "change_pct": None},
            "childrens_tshirts": {"subject": "Футболки детские", "current_orders": Decimal("0"), "previous_orders": Decimal("0"), "change_pct": None},
        }

        res = service.get_external_context(report_date=report_dt, category_sales_trends=cat_trends, max_signals=6, diagnostic=True)

        # Total selected signals: 2 Wordstat + 1 Calendar + 1 Sentiment + 1 Inflation = 5 signals
        assert len(res.signals) == 5

        wordstat_signals = [s for s in res.signals if s.source == "search_demand"]
        calendar_signals = [s for s in res.signals if s.source == "internal_calendar"]
        sentiment_signals = [s for s in res.signals if s.source == "cbr"]
        inflation_signals = [s for s in res.signals if s.source == "rosstat"]

        assert len(wordstat_signals) == 2
        assert len(calendar_signals) == 1
        assert len(sentiment_signals) == 1
        assert len(inflation_signals) == 1

        selected_wordstat_cats = {s.category for s in wordstat_signals}
        assert selected_wordstat_cats == {"womens_underwear", "womens_tshirts"}

        # Non-selected Wordstat candidates are retained in diagnostics
        diag_evals = res.diagnostics.get("candidate_evaluations", [])
        evaluated_wordstat_cats = {d.get("wordstat_category") for d in diag_evals if "wordstat_category" in d}
        assert evaluated_wordstat_cats == {"womens_underwear", "womens_tshirts", "childrens_underwear", "childrens_tshirts"}




