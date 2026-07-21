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

        # 1. Day 0 of publication (15.07.2026)
        res_d0 = service.get_external_context(date(2026, 7, 15), diagnostic=True)
        print("=== 1. Дата публикации (15.07.2026) ===")
        print("Сигналы:", [s.interpretation for s in res_d0.signals])

        # 2. Day +1 (16.07.2026)
        res_d1 = service.get_external_context(date(2026, 7, 16))
        print("\n=== 2. Следующий день (16.07.2026) ===")
        print("Сигналы:", [s.interpretation for s in res_d1.signals])

        # 3. Day +7 after publication (22.07.2026)
        res_d7 = service.get_external_context(date(2026, 7, 22))
        print("\n=== 3. 7-й день после публикации (22.07.2026) ===")
        print("Сигналы:", [s.interpretation for s in res_d7.signals])

        # 4. Day +8 after publication (23.07.2026) - window expired
        res_d8 = service.get_external_context(date(2026, 7, 23))
        print("\n=== 4. 8-й день после публикации (23.07.2026) - окно истекло ===")
        print("Сигналы:", [s.interpretation for s in res_d8.signals])
        print("Статус сводки:", res_d8.status)

        # 5. Diagnostic query detail for Sentiment Index 115.2
        print("\n=== 5. Structured Payload & Diagnostic Detail (Индекс 115,2 пункта) ===")
        sig_sentiment = res_d0.signals[0]
        print("Metric Code:", sig_sentiment.metric_code)
        print("Current Value:", sig_sentiment.current_value)
        print("Previous Value:", sig_sentiment.previous_value)
        print("Change Value:", sig_sentiment.change_value)
        print("Published At:", sig_sentiment.published_at)
        print("Fresh Until:", sig_sentiment.fresh_until)
        print("Neutral Level:", sig_sentiment.neutral_level)
        print("Interpretation:", sig_sentiment.interpretation)
        print("Diagnostics:", res_d0.diagnostics)

if __name__ == "__main__":
    run_demo()
