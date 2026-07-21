from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Any


SOURCE_REFERENCE = "internal_calendar:2026"


def _event(
    *,
    event_type: str,
    event_code: str,
    title: str,
    date_start: date,
    date_end: date,
    description: str,
    impact_direction: str,
    impact_strength: str,
    confidence: str = "medium",
    category: str | None = None,
) -> dict[str, Any]:
    return {
        "source": "internal_calendar",
        "event_type": event_type,
        "event_code": event_code,
        "title": title,
        "description": description,
        "date_start": date_start,
        "date_end": date_end,
        "region": None,
        "category": category,
        "impact_direction": impact_direction,
        "impact_strength": impact_strength,
        "confidence": confidence,
        "is_active": True,
        "source_reference": SOURCE_REFERENCE,
        "metadata_json": {"confidence_level": "context_only"},
    }


def calendar_events_for_year(year: int) -> list[dict[str, Any]]:
    if year != 2026:
        return []

    events = [
        _event(
            event_type="official_holiday",
            event_code="new_year_period_2026",
            title="Новогодний период",
            date_start=date(2026, 1, 1),
            date_end=date(2026, 1, 14),
            description="Календарный период новогодних праздников.",
            impact_direction="positive",
            impact_strength="medium",
        ),
        _event(
            event_type="official_holiday",
            event_code="defender_of_fatherland_day_2026",
            title="23 февраля",
            date_start=date(2026, 2, 23),
            date_end=date(2026, 2, 23),
            description="Календарная дата 23 февраля.",
            impact_direction="positive",
            impact_strength="medium",
        ),
        _event(
            event_type="official_holiday",
            event_code="international_womens_day_2026",
            title="8 марта",
            date_start=date(2026, 3, 8),
            date_end=date(2026, 3, 8),
            description="Календарная дата 8 марта.",
            impact_direction="positive",
            impact_strength="medium",
        ),
        _event(
            event_type="official_holiday",
            event_code="may_holidays_2026",
            title="Майские праздники",
            date_start=date(2026, 5, 1),
            date_end=date(2026, 5, 11),
            description="Календарный период майских праздников.",
            impact_direction="mixed",
            impact_strength="medium",
        ),
        _event(
            event_type="seasonal_period",
            event_code="summer_season_2026",
            title="Летний сезон",
            date_start=date(2026, 6, 1),
            date_end=date(2026, 8, 15),
            description="Сезонный период, который следует учитывать как внешний фон.",
            impact_direction="mixed",
            impact_strength="medium",
        ),
        _event(
            event_type="school_season",
            event_code="school_preparation_2026",
            title="Подготовка к школе",
            date_start=date(2026, 8, 1),
            date_end=date(2026, 8, 31),
            description="Период подготовки к школьному сезону.",
            impact_direction="positive",
            impact_strength="medium",
            category="school",
        ),
        _event(
            event_type="school_season",
            event_code="school_season_2026",
            title="Школьный сезон",
            date_start=date(2026, 9, 1),
            date_end=date(2026, 9, 15),
            description="Начало школьного сезона.",
            impact_direction="mixed",
            impact_strength="medium",
            category="school",
        ),
        _event(
            event_type="seasonal_period",
            event_code="summer_season_end_2026",
            title="Окончание летнего сезона",
            date_start=date(2026, 8, 15),
            date_end=date(2026, 9, 15),
            description="Переходный сезонный период после летнего пика.",
            impact_direction="mixed",
            impact_strength="medium",
        ),
        _event(
            event_type="marketplace_period",
            event_code="pre_new_year_demand_2026",
            title="Предновогодний спрос",
            date_start=date(2026, 12, 1),
            date_end=date(2026, 12, 31),
            description="Календарный период предновогоднего спроса.",
            impact_direction="positive",
            impact_strength="high",
        ),
    ]

    day = date(year, 1, 1)
    end = date(year, 12, 31)
    while day <= end:
        if day.weekday() >= 5:
            events.append(
                _event(
                    event_type="weekend",
                    event_code=f"weekend_{day.isoformat()}",
                    title="Выходной день",
                    date_start=day,
                    date_end=day,
                    description="Календарный выходной день без самостоятельной причинной интерпретации.",
                    impact_direction="neutral",
                    impact_strength="low",
                    confidence="low",
                )
            )
        day += timedelta(days=1)

    return events
