from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from scripts.load_external_calendar_events import apply_event_rows
from src.db.models import ExternalContextEvent
from src.mcp_server.app import create_app
from src.mcp_server.schemas import (
    ExternalContextResponse,
    ExternalContextSignalResponse,
    WbDailyOperationalDiagnosticsResponse,
    WbDailyOperationalHighlightsResponse,
    WbDailyOperationalReportWindowResponse,
    WbDailyOperationalSummaryResponse,
)
from src.mcp_server.service import McpRepository
from src.mcp_server.settings import McpServiceSettings
from src.mcp_server.wb_daily_operational_summary_format import render_wb_daily_operational_summary_markdown
from src.services.external_context.calendar_config import calendar_events_for_year
from src.services.external_context.service import ExternalContextService


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kwargs):
    return "JSON"


@compiles(BigInteger, "sqlite")
def _compile_bigint_sqlite(type_, compiler, **kwargs):
    return "INTEGER"


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _ExternalContextSession:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self, statement):
        return _ScalarRows(self.rows)


def _event(
    event_code: str,
    *,
    date_start: date,
    date_end: date,
    category: str | None = None,
    impact_direction: str = "mixed",
    impact_strength: str = "medium",
    confidence: str = "medium",
    event_id: int = 1,
) -> ExternalContextEvent:
    return ExternalContextEvent(
        id=event_id,
        source="test_calendar",
        event_type="seasonal_period",
        event_code=event_code,
        title=event_code,
        description="test context",
        date_start=date_start,
        date_end=date_end,
        category=category,
        impact_direction=impact_direction,
        impact_strength=impact_strength,
        confidence=confidence,
        is_active=True,
        source_reference="test",
        metadata_json={"confidence_level": "context_only"},
    )


def test_calendar_config_has_unique_2026_identities_and_required_event_types() -> None:
    rows = calendar_events_for_year(2026)
    identities = [
        (row["source"], row["event_code"], row["date_start"], row["date_end"], row["region"], row["category"])
        for row in rows
    ]
    assert len(rows) > 20
    assert len(identities) == len(set(identities))
    assert {row["event_type"] for row in rows} >= {
        "official_holiday",
        "weekend",
        "school_season",
        "seasonal_period",
        "marketplace_period",
    }


def test_external_context_service_filters_date_category_and_weak_events() -> None:
    rows = [
        _event("summer", date_start=date(2026, 7, 1), date_end=date(2026, 8, 15), event_id=1),
        _event("school", date_start=date(2026, 8, 1), date_end=date(2026, 8, 31), category="school", event_id=2),
        _event("other-category", date_start=date(2026, 7, 1), date_end=date(2026, 8, 31), category="other", event_id=3),
        _event("old", date_start=date(2026, 1, 1), date_end=date(2026, 1, 2), event_id=4),
        _event("weak", date_start=date(2026, 7, 1), date_end=date(2026, 8, 15), impact_direction="neutral", impact_strength="low", event_id=5),
    ]
    service = ExternalContextService(_ExternalContextSession(rows))

    global_result = service.get_external_context(report_date=date(2026, 7, 17))
    assert [signal.event_code for signal in global_result.signals] == ["summer"]
    assert all(signal.confidence_level == "context_only" for signal in global_result.signals)

    category_result = service.get_external_context(report_date=date(2026, 8, 10), categories=["school"])
    assert {signal.event_code for signal in category_result.signals} == {"summer", "school"}
    assert "other-category" not in {signal.event_code for signal in category_result.signals}
    assert category_result.diagnostics["excluded_weak_or_neutral"] == 1


def test_external_context_service_uses_period_overlap_and_caps_at_three() -> None:
    rows = [
        _event(f"event-{index}", date_start=date(2026, 8, 1), date_end=date(2026, 8, 31), event_id=index)
        for index in range(1, 6)
    ]
    service = ExternalContextService(_ExternalContextSession(rows))
    result = service.get_external_context(
        report_date=date(2026, 7, 15),
        period_start=date(2026, 8, 10),
        period_end=date(2026, 8, 20),
        max_signals=99,
    )
    assert result.status == "OK"
    assert len(result.signals) == 3
    assert result.applied_filters["max_signals"] == 3


def test_external_context_loader_is_idempotent_on_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    ExternalContextEvent.__table__.create(engine)
    row = calendar_events_for_year(2026)[0]
    with Session(engine) as session:
        first = apply_event_rows(session, [row], dry_run=False)
    with Session(engine) as session:
        second = apply_event_rows(session, [row], dry_run=False)
    with Session(engine) as session:
        count = session.query(ExternalContextEvent).count()
    assert first["inserted"] == 1
    assert second["unchanged"] == 1
    assert count == 1


def test_external_context_migration_declares_required_table_and_identity() -> None:
    migration = Path("alembic/versions/20260721_0030_add_external_context_event.py").read_text(encoding="utf-8")
    assert '"external_context_event"' in migration
    assert 'name="uq_external_context_event_identity"' in migration
    assert '"date_start", "date_end"' in migration
    assert '"metadata_json"' in migration


def _summary_with_external_context() -> WbDailyOperationalSummaryResponse:
    signal = ExternalContextSignalResponse(
        source="internal_calendar",
        event_type="seasonal_period",
        event_code="summer_season_2026",
        title="Летний сезон",
        date_start=date(2026, 6, 1),
        date_end=date(2026, 8, 15),
        impact_direction="mixed",
        impact_strength="medium",
        confidence="medium",
        confidence_level="context_only",
        interpretation="context_only",
        source_reference="internal_calendar:2026",
    )
    return WbDailyOperationalSummaryResponse(
        formula_version="v1",
        report_window=WbDailyOperationalReportWindowResponse(
            report_date=date(2026, 7, 17),
            compare_date=date(2026, 7, 16),
            trend_current_from=date(2026, 7, 11),
            trend_current_to=date(2026, 7, 17),
            trend_previous_from=date(2026, 7, 4),
            trend_previous_to=date(2026, 7, 10),
            report_date_source="request",
        ),
        requested_options={"mode": "brief", "diagnostic": False},
        source_freshness=[],
        sections=[],
        highlights=WbDailyOperationalHighlightsResponse(),
        diagnostics=WbDailyOperationalDiagnosticsResponse(),
        external_context={"status": "OK", "signals": [signal.model_dump(mode="json")]},
    )


def test_renderer_emits_only_compact_external_context_when_signals_exist() -> None:
    markdown = render_wb_daily_operational_summary_markdown(_summary_with_external_context())
    assert markdown.count("## Внешний фон") == 1
    assert "Летний сезон" in markdown
    assert "прямое влияние на продажи не подтверждено" in markdown
    assert "из-за" not in markdown
    assert len(markdown.split("## Внешний фон", 1)[1].split("## Действия на день", 1)[0]) < 800


class _ExternalRepository:
    def get_wb_external_context(self, payload):
        return ExternalContextResponse(
            report_date=payload.report_date,
            status="OK",
            signals=[
                ExternalContextSignalResponse(
                    source="internal_calendar",
                    event_type="seasonal_period",
                    event_code="summer_season_2026",
                    title="Летний сезон",
                    date_start=date(2026, 6, 1),
                    date_end=date(2026, 8, 15),
                    impact_direction="mixed",
                    impact_strength="medium",
                    confidence="medium",
                    confidence_level="context_only",
                    interpretation="context_only",
                )
            ],
        )


def test_external_context_mcp_tool_returns_structured_content() -> None:
    app = create_app(
        repository=_ExternalRepository(),
        settings=McpServiceSettings(database_url="sqlite:///:memory:", auth_token="test-token"),
    )
    client = TestClient(app)
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={
            "jsonrpc": "2.0",
            "id": 77,
            "method": "tools/call",
            "params": {"name": "get_wb_external_context", "arguments": {"report_date": "2026-07-17"}},
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["structuredContent"]["status"] == "OK"
    assert payload["result"]["structuredContent"]["signals"][0]["confidence_level"] == "context_only"
    assert payload["result"]["content"][0]["type"] == "text"
