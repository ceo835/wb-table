from __future__ import annotations

import json
import logging
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.mcp_server.schemas import (
    DashboardSummaryRequest,
    DashboardSummaryResponse,
    DbHealthResponse,
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
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_SERVER_NAME = "wb-dashboard-mcp"
MCP_SERVER_VERSION = "0.1.0"


def _tool_schema(model) -> dict:
    schema = model.model_json_schema()
    schema.pop("$defs", None)
    return schema


def build_mcp_tools_catalog() -> list[dict]:
    return [
        {
            "name": "db_health",
            "description": "Read-only DB smoke test over mart_total_report.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "get_dashboard_summary",
            "description": "Aggregate dashboard metrics for a date window from mart_total_report.",
            "inputSchema": _tool_schema(DashboardSummaryRequest),
        },
        {
            "name": "get_product_metrics",
            "description": "Daily metrics for one nm_id, including WB price snapshot if present.",
            "inputSchema": _tool_schema(ProductMetricsRequest),
        },
        {
            "name": "get_price_monitor",
            "description": "WB site price monitoring snapshot for the selected date.",
            "inputSchema": _tool_schema(PriceMonitorRequest),
        },
    ]


def build_mcp_success_response(request_id, result: dict) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def build_mcp_error_response(request_id, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=200,
    )


def _build_tool_result_payload(tool_result) -> dict:
    structured = tool_result.model_dump(mode="json")
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(structured, ensure_ascii=False),
            }
        ],
        "structuredContent": structured,
        "isError": False,
    }


def _execute_mcp_tool(name: str, arguments: dict, repository: McpRepository) -> dict:
    if name == "db_health":
        result = repository.get_db_health()
    elif name == "get_dashboard_summary":
        result = repository.get_dashboard_summary(DashboardSummaryRequest.model_validate(arguments))
    elif name == "get_product_metrics":
        result = repository.get_product_metrics(ProductMetricsRequest.model_validate(arguments))
    elif name == "get_price_monitor":
        result = repository.get_price_monitor(PriceMonitorRequest.model_validate(arguments))
    else:
        raise KeyError(name)
    return _build_tool_result_payload(result)


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

    @app.post("/mcp")
    async def mcp_endpoint(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ) -> Response:
        if not resolved_settings.mcp_public_mode:
            require_auth(credentials)

        payload = await request.json()
        messages = payload if isinstance(payload, list) else [payload]
        responses: list[dict] = []

        for message in messages:
            request_id = message.get("id")
            method = message.get("method")
            params = message.get("params") or {}

            if method == "notifications/initialized":
                continue

            if method == "initialize":
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "protocolVersion": MCP_PROTOCOL_VERSION,
                            "capabilities": {
                                "tools": {"listChanged": False},
                            },
                            "serverInfo": {
                                "name": MCP_SERVER_NAME,
                                "version": MCP_SERVER_VERSION,
                            },
                        },
                    }
                )
                continue

            if method == "ping":
                responses.append({"jsonrpc": "2.0", "id": request_id, "result": {}})
                continue

            if method == "tools/list":
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"tools": build_mcp_tools_catalog()},
                    }
                )
                continue

            if method == "tools/call":
                tool_name = str(params.get("name") or "")
                arguments = params.get("arguments") or {}
                try:
                    tool_result = _execute_mcp_tool(tool_name, arguments, resolved_repository)
                except KeyError:
                    responses.append(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                        }
                    )
                except ValueError as exc:
                    responses.append(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32602, "message": str(exc)},
                        }
                    )
                except Exception:
                    logger.exception("MCP transport tool call failed: %s", tool_name)
                    responses.append(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": "Internal server error."},
                        }
                    )
                else:
                    responses.append({"jsonrpc": "2.0", "id": request_id, "result": tool_result})
                continue

            responses.append(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )

        if not responses:
            return Response(status_code=202)
        if isinstance(payload, list):
            return JSONResponse(responses)
        return JSONResponse(responses[0])

    @app.post(
        "/tools/db_health",
        response_model=DbHealthResponse,
        dependencies=[Depends(require_auth)],
    )
    async def db_health() -> DbHealthResponse:
        try:
            return resolved_repository.get_db_health()
        except Exception:
            logger.exception("MCP tool failed: db_health")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

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
            logger.exception("MCP tool failed: get_dashboard_summary")
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
            logger.exception("MCP tool failed: get_product_metrics")
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
            logger.exception("MCP tool failed: get_price_monitor")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    return app
