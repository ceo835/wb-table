from __future__ import annotations

import os
from dataclasses import dataclass

from src.db.connection import normalize_database_url


DEFAULT_MAX_ROWS = 500
DEFAULT_QUERY_TIMEOUT_SECONDS = 20
DEFAULT_MAX_DATE_RANGE_DAYS = 60


@dataclass(frozen=True)
class McpServiceSettings:
    database_url: str
    auth_token: str
    max_rows: int = DEFAULT_MAX_ROWS
    query_timeout_seconds: int = DEFAULT_QUERY_TIMEOUT_SECONDS
    max_date_range_days: int = DEFAULT_MAX_DATE_RANGE_DAYS


def load_mcp_service_settings() -> McpServiceSettings:
    database_url = normalize_database_url(os.getenv("DATABASE_URL"))
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for MCP service.")

    auth_token = (os.getenv("MCP_AUTH_TOKEN") or "").strip()
    if not auth_token:
        raise RuntimeError("MCP_AUTH_TOKEN is required for MCP service.")

    max_rows = max(1, int(os.getenv("MCP_MAX_ROWS") or DEFAULT_MAX_ROWS))
    query_timeout_seconds = max(1, int(os.getenv("MCP_QUERY_TIMEOUT_SECONDS") or DEFAULT_QUERY_TIMEOUT_SECONDS))

    return McpServiceSettings(
        database_url=database_url,
        auth_token=auth_token,
        max_rows=max_rows,
        query_timeout_seconds=query_timeout_seconds,
        max_date_range_days=DEFAULT_MAX_DATE_RANGE_DAYS,
    )
