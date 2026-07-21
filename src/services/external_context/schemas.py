from __future__ import annotations

from datetime import date
from typing import Any, Literal
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field


class ExternalContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_date: date
    period_start: date | None = None
    period_end: date | None = None
    category: str | None = None
    region: str | None = None
    max_signals: int = Field(default=3, ge=1, le=3)
    diagnostic: bool = False


class ExternalContextSignalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    signal_type: str | None = None
    metric_code: str | None = None
    event_type: str | None = None
    event_code: str | None = None
    title: str
    description: str | None = None
    date_start: date | None = None
    date_end: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    region: str | None = None
    category: str | None = None
    value: Decimal | None = None
    current_value: Decimal | None = None
    previous_value: Decimal | None = None
    change_value: Decimal | None = None
    change_pct: Decimal | None = None
    published_at: date | None = None
    fresh_until: date | None = None
    neutral_level: Decimal | None = None
    impact_direction: Literal["positive", "negative", "mixed", "neutral"] | None = "neutral"
    impact_strength: Literal["low", "medium", "high"] | None = "medium"
    confidence: Literal["low", "medium", "high"] | None = "medium"
    relevance: str | None = None
    confidence_level: Literal["context_only", "insufficient_data"] | None = "context_only"
    interpretation: str | None = None
    source_reference: str | None = None
    data_status: str | None = "ok"


class ExternalContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_date: date
    period_start: date | None = None
    period_end: date | None = None
    status: Literal["OK", "EMPTY", "PARTIAL", "UNAVAILABLE", "DISABLED"]
    signals: list[ExternalContextSignalResponse] = Field(default_factory=list)
    applied_filters: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    sources_status: dict[str, str] = Field(default_factory=dict)
