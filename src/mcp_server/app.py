from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.mcp_server.schemas import (
    DashboardSummaryRequest,
    DashboardSummaryResponse,
    ErrorResponse,
    HealthResponse,
    PriceMonitorRequest,
    PriceMonitorResponse,
    ProductMetricsRequest,
    ProductMetricsResponse,
)
from src.mcp_server.service import McpRepository, PostgresMcpRepository
from src.mcp_server.settings import McpServiceSettings, load_mcp_service_settings


logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


def create_auth_dependency(settings: McpServiceSettings):
    def verify_token(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ) -> None:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
        if not secrets.compare_digest(credentials.credentials, settings.auth_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.")

    return verify_token


def create_app(
    repository: McpRepository | None = None,
    settings: McpServiceSettings | None = None,
) -> FastAPI:
    resolved_settings = settings or load_mcp_service_settings()
    resolved_repository = repository or PostgresMcpRepository(resolved_settings)
    require_auth = create_auth_dependency(resolved_settings)

    app = FastAPI(
        title="WB Dashboard MCP Service",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(ValueError)
    async def handle_value_error(_request, exc: ValueError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(detail=str(exc), code="INVALID_REQUEST").model_dump(mode="json"),
        )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(ok=True)

    @app.post(
        "/tools/get_dashboard_summary",
        response_model=DashboardSummaryResponse,
        dependencies=[Depends(require_auth)],
    )
    async def get_dashboard_summary(payload: DashboardSummaryRequest) -> DashboardSummaryResponse:
        try:
            return resolved_repository.get_dashboard_summary(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except Exception:
            logger.exception("MCP get_dashboard_summary failed")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    @app.post(
        "/tools/get_product_metrics",
        response_model=ProductMetricsResponse,
        dependencies=[Depends(require_auth)],
    )
    async def get_product_metrics(payload: ProductMetricsRequest) -> ProductMetricsResponse:
        try:
            return resolved_repository.get_product_metrics(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except Exception:
            logger.exception("MCP get_product_metrics failed")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    @app.post(
        "/tools/get_price_monitor",
        response_model=PriceMonitorResponse,
        dependencies=[Depends(require_auth)],
    )
    async def get_price_monitor(payload: PriceMonitorRequest) -> PriceMonitorResponse:
        try:
            return resolved_repository.get_price_monitor(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except Exception:
            logger.exception("MCP get_price_monitor failed")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    return app
