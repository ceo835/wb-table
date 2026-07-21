from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.db.models import ExternalContextEvent
from src.services.external_context.schemas import ExternalContextResponse, ExternalContextSignalResponse


_STRENGTH_RANK = {"high": 3, "medium": 2, "low": 1}
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


def _event_matches_filters(
    event: ExternalContextEvent,
    *,
    report_date: date,
    period_start: date,
    period_end: date,
    categories: list[str],
    region: str | None,
) -> bool:
    report_match = event.date_start <= report_date <= event.date_end
    period_match = event.date_start <= period_end and event.date_end >= period_start
    if not (report_match or period_match):
        return False
    if event.category is not None and event.category not in categories:
        return False
    if event.region is not None and event.region != region:
        return False
    return True


class ExternalContextService:
    def __init__(self, session: Session):
        self.session = session

    def get_external_context(
        self,
        report_date: date,
        period_start: date | None = None,
        period_end: date | None = None,
        categories: Iterable[str] | None = None,
        region: str | None = None,
        max_signals: int = 3,
    ) -> ExternalContextResponse:
        max_signals = max(1, min(int(max_signals), 3))
        categories_list = sorted({str(item).strip() for item in (categories or []) if str(item).strip()})
        resolved_period_start = period_start if period_start is not None else report_date
        resolved_period_end = period_end if period_end is not None else report_date
        if resolved_period_start > resolved_period_end:
            resolved_period_start, resolved_period_end = resolved_period_end, resolved_period_start

        applied_filters = {
            "report_date": report_date.isoformat(),
            "period_start": resolved_period_start.isoformat(),
            "period_end": resolved_period_end.isoformat(),
            "categories": categories_list,
            "region": region,
            "max_signals": max_signals,
            "confidence_policy": "calendar signals are context_only; direct causality is not confirmed",
        }

        try:
            date_match = or_(
                and_(ExternalContextEvent.date_start <= report_date, ExternalContextEvent.date_end >= report_date),
                and_(ExternalContextEvent.date_start <= resolved_period_end, ExternalContextEvent.date_end >= resolved_period_start),
            )
            category_match = (
                ExternalContextEvent.category.is_(None)
                if not categories_list
                else or_(ExternalContextEvent.category.is_(None), ExternalContextEvent.category.in_(categories_list))
            )
            region_match = (
                ExternalContextEvent.region.is_(None)
                if not region
                else or_(ExternalContextEvent.region.is_(None), ExternalContextEvent.region == region)
            )
            events = [
                event
                for event in self.session.scalars(
                    select(ExternalContextEvent)
                    .where(ExternalContextEvent.is_active.is_(True), date_match, category_match, region_match)
                    .order_by(ExternalContextEvent.date_start.desc(), ExternalContextEvent.event_code.asc())
                ).all()
                if _event_matches_filters(
                    event,
                    report_date=report_date,
                    period_start=resolved_period_start,
                    period_end=resolved_period_end,
                    categories=categories_list,
                    region=region,
                )
            ]
        except SQLAlchemyError as exc:
            return ExternalContextResponse(
                report_date=report_date,
                period_start=period_start,
                period_end=period_end,
                status="UNAVAILABLE",
                applied_filters=applied_filters,
                diagnostics={"source_table": "external_context_event", "error_type": type(exc).__name__, "message": str(exc)},
            )

        selected: list[ExternalContextEvent] = []
        excluded_weak = 0
        for event in events:
            if event.impact_direction == "neutral" or event.impact_strength == "low":
                excluded_weak += 1
                continue
            selected.append(event)

        selected.sort(
            key=lambda event: (
                -_STRENGTH_RANK.get(event.impact_strength, 0),
                -_CONFIDENCE_RANK.get(event.confidence, 0),
                -(event.date_start.toordinal()),
                event.event_code,
            )
        )
        selected = selected[:max_signals]
        signals: list[ExternalContextSignalResponse] = []
        conversion_errors = 0
        for event in selected:
            try:
                signals.append(
                    ExternalContextSignalResponse(
                        source=event.source,
                        event_type=event.event_type,
                        event_code=event.event_code,
                        title=event.title,
                        description=event.description,
                        date_start=event.date_start,
                        date_end=event.date_end,
                        region=event.region,
                        category=event.category,
                        impact_direction=event.impact_direction,
                        impact_strength=event.impact_strength,
                        confidence=event.confidence,
                        confidence_level="context_only",
                        interpretation="context_only",
                        source_reference=event.source_reference,
                    )
                )
            except (TypeError, ValueError):
                conversion_errors += 1

        diagnostics: dict[str, Any] = {
            "candidate_count": len(events),
            "selected_count": len(signals),
            "excluded_weak_or_neutral": excluded_weak,
            "selection_rule": "active events intersecting report_date or requested period, capped at max_signals",
        }
        if conversion_errors:
            diagnostics["conversion_errors"] = conversion_errors
        status = "PARTIAL" if conversion_errors else ("OK" if signals else "EMPTY")
        return ExternalContextResponse(
            report_date=report_date,
            period_start=period_start,
            period_end=period_end,
            status=status,
            signals=signals,
            applied_filters=applied_filters,
            diagnostics=diagnostics,
        )
