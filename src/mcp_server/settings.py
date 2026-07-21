from __future__ import annotations

import os
from dataclasses import dataclass

from src.db.connection import normalize_database_url


DEFAULT_MAX_ROWS = 500
DEFAULT_QUERY_TIMEOUT_SECONDS = 20
DEFAULT_MAX_DATE_RANGE_DAYS = 60


def _parse_bool_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class McpServiceSettings:
    database_url: str
    auth_token: str
    max_rows: int = DEFAULT_MAX_ROWS
    query_timeout_seconds: int = DEFAULT_QUERY_TIMEOUT_SECONDS
    max_date_range_days: int = DEFAULT_MAX_DATE_RANGE_DAYS
    mcp_public_mode: bool = False
    external_context_enabled: bool = True
    external_calendar_enabled: bool = True
    external_search_demand_enabled: bool = False
    external_wb_tariffs_enabled: bool = False
    external_weather_enabled: bool = False
    external_macro_enabled: bool = False
    external_context_max_signals: int = 3


def load_mcp_service_settings() -> McpServiceSettings:
    database_url = normalize_database_url(os.getenv("DATABASE_URL"))
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for MCP service.")

    auth_token = (os.getenv("MCP_AUTH_TOKEN") or "").strip()
    if not auth_token:
        raise RuntimeError("MCP_AUTH_TOKEN is required for MCP service.")

    max_rows = max(1, int(os.getenv("MCP_MAX_ROWS") or DEFAULT_MAX_ROWS))
    query_timeout_seconds = max(1, int(os.getenv("MCP_QUERY_TIMEOUT_SECONDS") or DEFAULT_QUERY_TIMEOUT_SECONDS))
    mcp_public_mode = _parse_bool_env(os.getenv("MCP_PUBLIC_MODE"))
    external_context_enabled = _parse_bool_env(os.getenv("EXTERNAL_CONTEXT_ENABLED", "true"))
    external_calendar_enabled = _parse_bool_env(os.getenv("EXTERNAL_CALENDAR_ENABLED", "true"))
    external_search_demand_enabled = _parse_bool_env(os.getenv("EXTERNAL_SEARCH_DEMAND_ENABLED"))
    external_wb_tariffs_enabled = _parse_bool_env(os.getenv("EXTERNAL_WB_TARIFFS_ENABLED"))
    external_weather_enabled = _parse_bool_env(os.getenv("EXTERNAL_WEATHER_ENABLED"))
    external_macro_enabled = _parse_bool_env(os.getenv("EXTERNAL_MACRO_ENABLED"))
    external_context_max_signals = max(1, min(3, int(os.getenv("EXTERNAL_CONTEXT_MAX_SIGNALS") or "3")))

    return McpServiceSettings(
        database_url=database_url,
        auth_token=auth_token,
        max_rows=max_rows,
        query_timeout_seconds=query_timeout_seconds,
        max_date_range_days=DEFAULT_MAX_DATE_RANGE_DAYS,
        mcp_public_mode=mcp_public_mode,
        external_context_enabled=external_context_enabled,
        external_calendar_enabled=external_calendar_enabled,
        external_search_demand_enabled=external_search_demand_enabled,
        external_wb_tariffs_enabled=external_wb_tariffs_enabled,
        external_weather_enabled=external_weather_enabled,
        external_macro_enabled=external_macro_enabled,
        external_context_max_signals=external_context_max_signals,
    )
