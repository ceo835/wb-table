import os
import sys
from pathlib import Path
from datetime import date, datetime
from decimal import Decimal

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["TEST_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["MCP_AUTH_TOKEN"] = "test"

from src.db.connection import create_db_engine
from src.db.session import session_scope
from src.db.models import Base, ExternalContextMetric, ExternalContextEvent
from src.services.external_context.service import ExternalContextService
from src.mcp_server.wb_daily_operational_summary_format import _build_external_context_lines
from src.mcp_server.schemas import WbDailyOperationalSummaryResponse

def run_demo():
    engine = create_db_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)

    pub_date = datetime(2026, 7, 15, 10, 0)

    with session_scope(engine) as session:
        # Wordstat
        session.add(ExternalContextMetric(
            source="yandex_direct",
            metric_code="search_demand_womens_tshirts",
            metric_name="Wordstat",
            period_start=date(2026, 7, 13),
            period_end=date(2026, 7, 19),
            published_at=pub_date,
            value=Decimal("15000"),
            previous_value=Decimal("13000"),
            change_pct=Decimal("15.0"),
            category="womens_tshirts",
            data_status="ok"
        ))
        # Calendar Event
        session.add(ExternalContextEvent(
            source="internal_calendar",
            event_type="sale",
            event_code="summer_sale",
            title="Летняя распродажа",
            description="Старт летней распродажи одежды",
            date_start=date(2026, 7, 18),
            date_end=date(2026, 7, 20),
            is_active=True
        ))
        # Consumer Sentiment Index
        session.add(ExternalContextMetric(
            source="cbr",
            metric_code="consumer_sentiment_index",
            metric_name="Индекс настроений",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 15),
            published_at=pub_date,
            value=Decimal("115.2"),
            previous_value=Decimal("112.0"),
            change_value=Decimal("3.2"),
            data_status="ok"
        ))
        # Inflation Rate
        session.add(ExternalContextMetric(
            source="rosstat",
            metric_code="inflation_rate",
            metric_name="Инфляция",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 15),
            published_at=pub_date,
            value=Decimal("8.6"),
            previous_value=Decimal("8.1"),
            data_status="ok"
        ))
        session.commit()

    with session_scope(engine) as session:
        service = ExternalContextService(session)

        # 1. Signals available with category-matched Wordstat
        cat_trends = {"womens_tshirts": {"change_pct": Decimal("-8.0")}}
        res_d0 = service.get_external_context(date(2026, 7, 15), category_sales_trends=cat_trends, diagnostic=True)
        print("=== 1. Сигналы есть (signals_available) ===")
        print("External Context Status:", res_d0.external_context_status)
        print("Сигналы:", [s.interpretation for s in res_d0.signals])

        # 2. No significant signals
        res_d8 = service.get_external_context(date(2026, 7, 23), diagnostic=True)
        print("\n=== 2. Новых значимых сигналов нет (no_significant_signals) ===")
        print("External Context Status:", res_d8.external_context_status)
        print("Сигналы:", [s.interpretation for s in res_d8.signals])
        from src.mcp_server.schemas import WbDailyOperationalReportWindowResponse, WbDailyOperationalHighlightsResponse, WbDailyOperationalDiagnosticsResponse
        resp_obj = WbDailyOperationalSummaryResponse(
            formula_version="v1",
            report_window=WbDailyOperationalReportWindowResponse(
                report_date=date(2026, 7, 23),
                compare_date=date(2026, 7, 22),
                trend_current_from=date(2026, 7, 17),
                trend_current_to=date(2026, 7, 23),
                trend_previous_from=date(2026, 7, 10),
                trend_previous_to=date(2026, 7, 16),
                report_date_source="requested"
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
            external_context=res_d8.model_dump()
        )
        print("Строки отчёта:", _build_external_context_lines(resp_obj))

        # 3. Diagnostic Detail
        print("\n=== 3. Structured Diagnostics ===")
        print("Sources Checked:", res_d0.diagnostics.get("sources_checked"))
        print("Candidate Count:", res_d0.diagnostics.get("candidate_count"))
        print("Excluded Count:", res_d0.diagnostics.get("excluded_count"))

if __name__ == "__main__":
    run_demo()
