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
    external_search_demand_enabled: bool = True
    external_consumer_sentiment_enabled: bool = True
    external_macro_enabled: bool = True
    external_weather_enabled: bool = False
    external_wb_tariffs_enabled: bool = False
    external_context_max_signals: int = 4
    
    # Thresholds
    search_demand_min_change_pct: float = 8.0
    consumer_sentiment_min_change_pct: float = 3.0
    macro_min_change_pct: float = 2.0
    calendar_transition_window_days: int = 7
    consumer_signal_display_days: int = 7
    macro_signal_display_days: int = 7

    # Credentials
    yandex_direct_token: str | None = None
    yandex_direct_client_login: str | None = None


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
    external_search_demand_enabled = _parse_bool_env(os.getenv("EXTERNAL_SEARCH_DEMAND_ENABLED", "true"))
    external_consumer_sentiment_enabled = _parse_bool_env(os.getenv("EXTERNAL_CONSUMER_SENTIMENT_ENABLED", "true"))
    external_macro_enabled = _parse_bool_env(os.getenv("EXTERNAL_MACRO_ENABLED", "true"))
    external_weather_enabled = _parse_bool_env(os.getenv("EXTERNAL_WEATHER_ENABLED"))
    external_wb_tariffs_enabled = _parse_bool_env(os.getenv("EXTERNAL_WB_TARIFFS_ENABLED"))
    external_context_max_signals = max(1, min(4, int(os.getenv("EXTERNAL_CONTEXT_MAX_SIGNALS") or "4")))

    # Thresholds
    search_demand_min_change_pct = float(os.getenv("SEARCH_DEMAND_MIN_CHANGE_PCT") or "8.0")
    consumer_sentiment_min_change_pct = float(os.getenv("CONSUMER_SENTIMENT_MIN_CHANGE_PCT") or "3.0")
    macro_min_change_pct = float(os.getenv("MACRO_MIN_CHANGE_PCT") or "2.0")
    calendar_transition_window_days = int(os.getenv("CALENDAR_TRANSITION_WINDOW_DAYS") or "7")
    consumer_signal_display_days = int(os.getenv("CONSUMER_SIGNAL_DISPLAY_DAYS") or "7")
    macro_signal_display_days = int(os.getenv("MACRO_SIGNAL_DISPLAY_DAYS") or "7")

    # Credentials
    yandex_direct_token = os.getenv("YANDEX_DIRECT_TOKEN")
    yandex_direct_client_login = os.getenv("YANDEX_DIRECT_CLIENT_LOGIN")

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
        external_consumer_sentiment_enabled=external_consumer_sentiment_enabled,
        external_macro_enabled=external_macro_enabled,
        external_weather_enabled=external_weather_enabled,
        external_wb_tariffs_enabled=external_wb_tariffs_enabled,
        external_context_max_signals=external_context_max_signals,
        search_demand_min_change_pct=search_demand_min_change_pct,
        consumer_sentiment_min_change_pct=consumer_sentiment_min_change_pct,
        macro_min_change_pct=macro_min_change_pct,
        calendar_transition_window_days=calendar_transition_window_days,
        consumer_signal_display_days=consumer_signal_display_days,
        macro_signal_display_days=macro_signal_display_days,
        yandex_direct_token=yandex_direct_token,
        yandex_direct_client_login=yandex_direct_client_login,
    )
