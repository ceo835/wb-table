from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from src.mcp_server.app import create_app
from src.mcp_server.schemas import (
    DashboardSummaryRequest,
    DashboardSummaryResponse,
    DataQualityResponse,
    DbHealthResponse,
    PriceMonitorRequest,
    PriceMonitorResponse,
    PriceMonitorItemResponse,
    ProductDailyMetricsResponse,
    ProductMetricsRequest,
    ProductMetricsResponse,
    ProductSummaryResponse,
)
from src.mcp_server.service import build_price_monitor_response
from src.mcp_server.settings import McpServiceSettings


class FakeRepository:
    def get_dashboard_summary(self, payload: DashboardSummaryRequest) -> DashboardSummaryResponse:
        assert payload.only_tracked is True
        return DashboardSummaryResponse(
            date_from=payload.date_from,
            date_to=payload.date_to,
            rows=12,
            nm_count=3,
            cart_count=Decimal("44"),
            order_count=Decimal("11"),
            order_sum=Decimal("12345.67"),
            ad_spend=Decimal("1500"),
            ad_atbs=Decimal("9"),
            ad_orders=Decimal("4"),
            cpo_total=Decimal("136.36"),
            cpo_ad=Decimal("375"),
            cost_per_cart_total=Decimal("34.09"),
            cost_per_cart_ad=Decimal("166.67"),
            drr=Decimal("12.15"),
            data_quality=DataQualityResponse(partial_rows=2, empty_rows=1, notes=["tracked scope"]),
        )

    def get_product_metrics(self, payload: ProductMetricsRequest) -> ProductMetricsResponse:
        if payload.nm_id == 999:
            return ProductMetricsResponse(
                found=False,
                nm_id=payload.nm_id,
                supplier_article=None,
                product_name=None,
                date_from=payload.date_from,
                date_to=payload.date_to,
                daily=[],
                summary=ProductSummaryResponse(
                    cart_count=None,
                    order_count=None,
                    order_sum=None,
                    ad_spend=None,
                ),
            )
        return ProductMetricsResponse(
            found=True,
            nm_id=payload.nm_id,
            supplier_article="demo-art",
            product_name="Demo Product",
            date_from=payload.date_from,
            date_to=payload.date_to,
            daily=[
                ProductDailyMetricsResponse(
                    date=payload.date_to,
                    card_clicks=Decimal("0"),
                    cart_count=Decimal("0"),
                    order_count=Decimal("0"),
                    order_sum=Decimal("0"),
                    ad_spend=Decimal("10"),
                    ad_clicks=Decimal("1"),
                    ad_atbs=None,
                    ad_orders=None,
                    current_stock_qty=None,
                    wb_buyer_price=None,
                )
            ],
            summary=ProductSummaryResponse(
                cart_count=Decimal("0"),
                order_count=Decimal("0"),
                order_sum=Decimal("0"),
                ad_spend=Decimal("10"),
            ),
        )

    def get_price_monitor(self, payload: PriceMonitorRequest) -> PriceMonitorResponse:
        items = [
            PriceMonitorItemResponse(
                nm_id=91470767,
                supplier_article="avokadogirl",
                product_name="Трусы детские",
                snapshot_date=payload.snapshot_date,
                buyer_visible_price=Decimal("799"),
                previous_price=Decimal("799"),
                price_delta=Decimal("0"),
                is_alert=False,
                alert_reason=None,
                fetch_status="success",
                product_url="https://www.wildberries.ru/catalog/91470767/detail.aspx",
            ),
            PriceMonitorItemResponse(
                nm_id=197330807,
                supplier_article="BlackWOM5",
                product_name="Набор 5 штук",
                snapshot_date=payload.snapshot_date,
                buyer_visible_price=Decimal("1299"),
                previous_price=Decimal("1190"),
                price_delta=Decimal("109"),
                is_alert=True,
                alert_reason="PRICE_CHANGED_50",
                fetch_status="success",
                product_url="https://www.wildberries.ru/catalog/197330807/detail.aspx",
            ),
        ]
        if payload.alerts_only:
            items = [item for item in items if item.is_alert]
        return PriceMonitorResponse(
            snapshot_date=payload.snapshot_date,
            rows=2,
            alerts=1,
            items=items,
        )

    def get_db_health(self) -> DbHealthResponse:
        return DbHealthResponse(
            ok=True,
            rows=7434,
            min_date=date(2026, 2, 12),
            max_date=date(2026, 6, 19),
        )


def build_test_client(*, mcp_public_mode: bool = False) -> TestClient:
    settings = McpServiceSettings(
        database_url="postgresql+psycopg://example",
        auth_token="test-token",
        max_rows=500,
        query_timeout_seconds=20,
        max_date_range_days=60,
        mcp_public_mode=mcp_public_mode,
    )
    app = create_app(repository=FakeRepository(), settings=settings)
    return TestClient(app)


def test_health_responds() -> None:
    client = build_test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_tools_require_token() -> None:
    client = build_test_client()
    response = client.post(
        "/tools/get_dashboard_summary",
        json={"date_from": "2026-06-07", "date_to": "2026-06-18", "only_tracked": True},
    )
    assert response.status_code == 401


def test_tools_work_with_token() -> None:
    client = build_test_client()
    response = client.post(
        "/tools/get_dashboard_summary",
        headers={"Authorization": "Bearer test-token"},
        json={"date_from": "2026-06-07", "date_to": "2026-06-18", "only_tracked": True},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["rows"] == 12
    assert payload["nm_count"] == 3
    assert payload["data_quality"]["partial_rows"] == 2


def test_get_product_metrics_handles_unknown_nm_id() -> None:
    client = build_test_client()
    response = client.post(
        "/tools/get_product_metrics",
        headers={"Authorization": "Bearer test-token"},
        json={"nm_id": 999, "date_from": "2026-06-07", "date_to": "2026-06-18"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["found"] is False
    assert payload["daily"] == []


def test_get_price_monitor_uses_snapshot_as_base_and_alert_as_flag() -> None:
    client = build_test_client()
    response = client.post(
        "/tools/get_price_monitor",
        headers={"Authorization": "Bearer test-token"},
        json={"snapshot_date": "2026-06-18", "alerts_only": False},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["rows"] == 2
    assert payload["alerts"] == 1
    assert len(payload["items"]) == 2
    assert payload["items"][0]["buyer_visible_price"] == 799
    assert payload["items"][0]["is_alert"] is False
    assert payload["items"][1]["is_alert"] is True


def test_get_price_monitor_alerts_only_filters_to_alerts() -> None:
    client = build_test_client()
    response = client.post(
        "/tools/get_price_monitor",
        headers={"Authorization": "Bearer test-token"},
        json={"snapshot_date": "2026-06-18", "alerts_only": True},
    )
    payload = response.json()
    assert response.status_code == 200
    assert len(payload["items"]) == 1
    assert payload["items"][0]["is_alert"] is True


def test_get_db_health_works_with_token() -> None:
    client = build_test_client()
    response = client.post(
        "/tools/db_health",
        headers={"Authorization": "Bearer test-token"},
        json={},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["rows"] == 7434
    assert payload["min_date"] == "2026-02-12"
    assert payload["max_date"] == "2026-06-19"


def test_get_db_health_requires_token() -> None:
    client = build_test_client()
    response = client.post("/tools/db_health", json={})
    assert response.status_code == 401


def test_mcp_initialize_returns_streamable_http_server_info() -> None:
    client = build_test_client()
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["protocolVersion"] == "2025-06-18"
    assert payload["result"]["serverInfo"]["name"] == "wb-dashboard-mcp"
    assert "tools" in payload["result"]["capabilities"]


def test_mcp_tools_list_exposes_registered_tools() -> None:
    client = build_test_client()
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    payload = response.json()
    tool_names = [tool["name"] for tool in payload["result"]["tools"]]
    assert response.status_code == 200
    assert tool_names == [
        "db_health",
        "get_dashboard_summary",
        "get_product_metrics",
        "get_price_monitor",
    ]


def test_mcp_tools_call_db_health_returns_structured_content() -> None:
    client = build_test_client()
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "db_health", "arguments": {}},
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["isError"] is False
    assert payload["result"]["structuredContent"]["rows"] == 7434
    assert payload["result"]["structuredContent"]["min_date"] == "2026-02-12"


def test_mcp_tools_call_dashboard_summary_returns_structured_content() -> None:
    client = build_test_client()
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "get_dashboard_summary",
                "arguments": {
                    "date_from": "2026-06-07",
                    "date_to": "2026-06-18",
                    "only_tracked": True,
                },
            },
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["structuredContent"]["rows"] == 12
    assert payload["result"]["structuredContent"]["nm_count"] == 3


def test_mcp_notifications_initialized_returns_accepted_without_body() -> None:
    client = build_test_client()
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    )
    assert response.status_code == 202
    assert response.text == ""


def test_mcp_public_mode_allows_initialize_without_bearer_token() -> None:
    client = build_test_client(mcp_public_mode=True)
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "public-test", "version": "1.0"},
            },
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["protocolVersion"] == "2025-06-18"


def test_mcp_public_mode_allows_tools_list_without_bearer_token() -> None:
    client = build_test_client(mcp_public_mode=True)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 11, "method": "tools/list", "params": {}},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["tools"][0]["name"] == "db_health"


def test_mcp_public_mode_does_not_open_legacy_tools_without_auth() -> None:
    client = build_test_client(mcp_public_mode=True)
    response = client.post("/tools/db_health", json={})
    assert response.status_code == 401


def test_none_values_remain_null_in_product_metrics() -> None:
    client = build_test_client()
    response = client.post(
        "/tools/get_product_metrics",
        headers={"Authorization": "Bearer test-token"},
        json={"nm_id": 91470767, "date_from": "2026-06-07", "date_to": "2026-06-18"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["daily"][0]["ad_atbs"] is None
    assert payload["daily"][0]["current_stock_qty"] is None
    assert payload["daily"][0]["wb_buyer_price"] is None


def test_build_price_monitor_response_ignores_suppressed_alerts() -> None:
    payload = PriceMonitorRequest(snapshot_date=date(2026, 6, 18), alerts_only=False)
    snapshot_rows = [
        {
            "snapshot_date": date(2026, 6, 17),
            "snapshot_at": None,
            "nm_id": 26033523,
            "supplier_article": "demo",
            "product_name": "Demo",
            "product_url": "https://example.test/product",
            "buyer_visible_price": Decimal("630"),
            "fetch_status": "success",
        },
        {
            "snapshot_date": date(2026, 6, 18),
            "snapshot_at": None,
            "nm_id": 26033523,
            "supplier_article": "demo",
            "product_name": "Demo",
            "product_url": "https://example.test/product",
            "buyer_visible_price": Decimal("1180"),
            "fetch_status": "success",
        },
    ]
    alert_rows = [
        {
            "snapshot_date": date(2026, 6, 18),
            "nm_id": 26033523,
            "current_price": Decimal("1180"),
            "previous_success_price": Decimal("630"),
            "price_delta": Decimal("550"),
            "alert_status": "MANUAL_SUPPRESSED_FALSE_PREVIOUS_PRICE",
        }
    ]

    response = build_price_monitor_response(payload, snapshot_rows, alert_rows)

    assert response.rows == 1
    assert response.alerts == 0
    assert response.items[0].is_alert is False
    assert response.items[0].buyer_visible_price == Decimal("1180")
    assert response.items[0].previous_price == Decimal("630")
