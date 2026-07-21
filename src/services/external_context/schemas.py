from __future__ import annotations

from datetime import date
from typing import Any, Literal
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
    event_type: str
    event_code: str
    title: str
    description: str | None = None
    date_start: date
    date_end: date
    region: str | None = None
    category: str | None = None
    impact_direction: Literal["positive", "negative", "mixed", "neutral"]
    impact_strength: Literal["low", "medium", "high"]
    confidence: Literal["low", "medium", "high"]
    confidence_level: Literal["context_only", "insufficient_data"]
    interpretation: str | None = None
    source_reference: str | None = None


class ExternalContextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_date: date
    period_start: date | None = None
    period_end: date | None = None
    status: Literal["OK", "EMPTY", "PARTIAL", "UNAVAILABLE", "DISABLED"]
    signals: list[ExternalContextSignalResponse] = Field(default_factory=list)
    applied_filters: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
