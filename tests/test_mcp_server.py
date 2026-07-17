from __future__ import annotations

from datetime import date
from typing import Any
from decimal import Decimal

from fastapi.testclient import TestClient

from src.mcp_server.app import (
    WB_DAILY_OPERATIONAL_SUMMARY_CONTENT_HINT,
    _build_tool_result_payload,
    create_app,
)
from src.mcp_server.schemas import (
    ActiveProductsItemResponse,
    ActiveProductsRequest,
    ActiveProductsResponse,
    DashboardSummaryRequest,
    DashboardSummaryResponse,
    DataQualityResponse,
    DbHealthResponse,
    MartSchemaResponse,
    MartSchemaColumnResponse,
    PriceMonitorRequest,
    PriceMonitorResponse,
    PriceMonitorItemResponse,
    ProductDataQualityResponse,
    ProductDailyMetricsResponse,
    ProductMetricsRequest,
    ProductMetricsResponse,
    ProductPeriodMetaResponse,
    ProductSummaryResponse,
)
from src.mcp_server.service import build_price_monitor_response
from src.mcp_server.settings import McpServiceSettings
from src.mcp_server.wb_daily_operational_summary import resolve_report_date
from src.mcp_server.wb_daily_operational_summary_format import render_wb_daily_operational_summary_markdown
from src.mcp_server.schemas import (
    WbDailyOperationalDiagnosticsResponse,
    WbDailyOperationalExcludedSectionResponse,
    WbDailyOperationalHighlightsResponse,
    WbDailyOperationalMetricRowResponse,
    WbDailyOperationalReportWindowResponse,
    WbDailyOperationalSectionResponse,
    WbDailyOperationalSignalResponse,
    WbDailyOperationalSourceFreshnessResponse,
    WbDailyOperationalSummaryRequest,
    WbDailyOperationalSummaryResponse,
    WbDailyOperationalTableResponse,
)


class FakeRepository:
    def get_dashboard_summary(self, payload: DashboardSummaryRequest) -> DashboardSummaryResponse:
        assert payload.only_tracked is True
        assert payload.scope == "core"
        return DashboardSummaryResponse(
            date_from=payload.date_from,
            date_to=payload.date_to,
            rows=12,
            nm_count=3,
            card_clicks=Decimal("77"),
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
        assert payload.scope == "core"
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
                    card_clicks_total=None,
                    cart_count=None,
                    order_count=None,
                    order_sum=None,
                    ad_spend=None,
                    avg_ctr=None,
                    avg_add_to_cart_conversion=None,
                    avg_cart_to_order_conversion=None,
                    order_sum_available_dates_count=0,
                    order_sum_missing_dates_count=0,
                ),
                period_meta=ProductPeriodMetaResponse(rows_count=0, days_requested=12, days_returned=0),
                source_coverage={
                    "funnel": "missing",
                    "price_monitor": "missing",
                    "ad_metrics": "missing",
                    "stock_by_size": "missing",
                    "delivery_time": "missing",
                },
                data_quality=ProductDataQualityResponse(
                    order_sum_available_dates_count=0,
                    order_sum_missing_dates_count=0,
                    order_sum_missing_for_dates=[],
                    wb_buyer_price_missing=True,
                    ad_metrics_missing=True,
                    stock_by_size_missing=True,
                    delivery_time_missing=True,
                    cannot_calculate_period_ctr_without_impressions=True,
                ),
                field_definitions={
                    "ctr": "percent",
                    "add_to_cart_conversion": "percent",
                    "cart_to_order_conversion": "percent",
                    "order_sum_null": "missing_data_not_zero",
                },
                null_semantics={
                    "order_sum": "missing_data_not_zero",
                    "wb_buyer_price": "missing_snapshot_not_zero",
                },
                analysis_status="NO_DATA",
                allowed_inferences=[],
                forbidden_inferences=["price_cause", "stock_cause", "ad_cause", "promo_cause", "delivery_cause"],
                analysis_limits=["rows not found"],
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
                    ctr=Decimal("0"),
                    cart_count=Decimal("0"),
                    add_to_cart_conversion=Decimal("0"),
                    order_count=Decimal("0"),
                    cart_to_order_conversion=Decimal("0"),
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
                card_clicks_total=Decimal("0"),
                cart_count=Decimal("0"),
                order_count=Decimal("0"),
                order_sum=Decimal("0"),
                ad_spend=Decimal("10"),
                avg_ctr=Decimal("0"),
                avg_add_to_cart_conversion=Decimal("0"),
                avg_cart_to_order_conversion=Decimal("0"),
                order_sum_available_dates_count=1,
                order_sum_missing_dates_count=0,
            ),
            period_meta=ProductPeriodMetaResponse(rows_count=1, days_requested=12, days_returned=1),
            source_coverage={
                "funnel": "full",
                "price_monitor": "missing",
                "ad_metrics": "full",
                "stock_by_size": "missing",
                "delivery_time": "missing",
            },
            data_quality=ProductDataQualityResponse(
                order_sum_available_dates_count=1,
                order_sum_missing_dates_count=0,
                order_sum_missing_for_dates=[],
                wb_buyer_price_missing=True,
                ad_metrics_missing=False,
                stock_by_size_missing=True,
                delivery_time_missing=True,
                cannot_calculate_period_ctr_without_impressions=True,
            ),
            field_definitions={
                "ctr": "percent",
                "add_to_cart_conversion": "percent",
                "cart_to_order_conversion": "percent",
                "order_sum_null": "missing_data_not_zero",
            },
            null_semantics={
                "order_sum": "missing_data_not_zero",
                "wb_buyer_price": "missing_snapshot_not_zero",
                "ad_metrics": "missing_metric_not_zero",
                "current_stock_qty": "missing_snapshot_not_zero",
            },
            analysis_status="LIMITED",
            allowed_inferences=["funnel_trend", "conversion_change", "day_to_day_trend"],
            forbidden_inferences=["price_cause", "stock_cause", "promo_cause", "delivery_cause"],
            analysis_limits=[
                "Можно анализировать изменение переходов, корзин, заказов и конверсий.",
                "Если поле отсутствует или равно null, это означает нет данных, а не ноль.",
            ],
        )

    def get_price_monitor(self, payload: PriceMonitorRequest) -> PriceMonitorResponse:
        assert payload.scope == "core"
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

    def get_active_products(self, payload: ActiveProductsRequest) -> ActiveProductsResponse:
        assert payload.scope == "core"
        return ActiveProductsResponse(
            scope="core",
            rows=2,
            items=[
                ActiveProductsItemResponse(
                    nm_id=91470767,
                    supplier_article="avokadogirl",
                    title="Трусы детские",
                    brand="BANDE",
                    category=None,
                    subject="Трусы",
                    analytics_active=True,
                    price_monitor_enabled=True,
                    lifecycle_status="active",
                    reason="price_monitor_seed",
                ),
                ActiveProductsItemResponse(
                    nm_id=197330807,
                    supplier_article="BlackWOM5",
                    title="Набор 5 штук",
                    brand="BANDE",
                    category=None,
                    subject="Трусы",
                    analytics_active=True,
                    price_monitor_enabled=True,
                    lifecycle_status="active",
                    reason="price_monitor_seed",
                ),
            ],
        )

    def get_db_health(self) -> DbHealthResponse:
        return DbHealthResponse(
            ok=True,
            rows=7434,
            min_date=date(2026, 2, 12),
            max_date=date(2026, 6, 19),
        )

    def get_mart_schema(self) -> MartSchemaResponse:
        return MartSchemaResponse(
            table_name="mart_total_report",
            columns=[
                MartSchemaColumnResponse(column_name="report_date", data_type="date"),
                MartSchemaColumnResponse(column_name="nm_id", data_type="bigint"),
            ],
        )

    def get_wb_daily_operational_summary(self, payload: WbDailyOperationalSummaryRequest) -> WbDailyOperationalSummaryResponse:
        assert payload.top_n == 5
        return WbDailyOperationalSummaryResponse(
            formula_version="v1",
            report_window=WbDailyOperationalReportWindowResponse(
                report_date=date(2026, 6, 18),
                compare_date=date(2026, 6, 17),
                trend_current_from=date(2026, 6, 12),
                trend_current_to=date(2026, 6, 18),
                trend_previous_from=date(2026, 6, 5),
                trend_previous_to=date(2026, 6, 11),
                report_date_source="auto",
            ),
            requested_options={
                "mode": payload.mode,
                "include_profit": payload.include_profit,
                "include_partial_sections": payload.include_partial_sections,
                "top_n": payload.top_n,
                "diagnostic": payload.diagnostic,
            },
            source_freshness=[
                WbDailyOperationalSourceFreshnessResponse(
                    source="mart_total_report",
                    max_date=date(2026, 6, 18),
                    status="OK",
                    lag_days=0,
                )
            ],
            sections=[
                WbDailyOperationalSectionResponse(
                    key="overview",
                    title="Краткий итог дня",
                    status="OK",
                    summary=["Заказов стало больше, чем днём ранее."],
                    metrics=[
                        WbDailyOperationalMetricRowResponse(
                            metric="Заказы",
                            value=120,
                            previous_value=100,
                            delta_abs=20,
                            delta_pct=Decimal("20.0"),
                            trend_7d_pct=Decimal("12.5"),
                        )
                    ],
                    tables=[],
                    signals=[],
                ),
                WbDailyOperationalSectionResponse(
                    key="ads",
                    title="Рекламная эффективность",
                    status="OK",
                    summary=["Есть кампании с высоким ДРР."],
                    metrics=[],
                    tables=[
                        WbDailyOperationalTableResponse(
                            title="Проблемные кампании",
                            columns=["advert_id", "drr"],
                            rows=[{"advert_id": 101, "drr": "31.5"}],
                        )
                    ],
                    signals=[],
                ),
                WbDailyOperationalSectionResponse(
                    key="assortment",
                    title="Ассортимент: ТОП роста и падения",
                    status="OK",
                    summary=["Есть товары с разнонаправленной динамикой."],
                    metrics=[],
                    tables=[
                        WbDailyOperationalTableResponse(
                            title="ТОП роста",
                            columns=["nm_id", "orders_delta_pct"],
                            rows=[{"nm_id": 1, "orders_delta_pct": "45.0"}],
                        ),
                        WbDailyOperationalTableResponse(
                            title="ТОП падения",
                            columns=["nm_id", "orders_delta_pct"],
                            rows=[{"nm_id": 2, "orders_delta_pct": "-18.0"}],
                        ),
                    ],
                    signals=[],
                ),
                WbDailyOperationalSectionResponse(
                    key="stock",
                    title="Остатки и складские риски",
                    status="OK",
                    summary=["Есть позиции с низким запасом."],
                    metrics=[],
                    tables=[],
                    signals=[
                        WbDailyOperationalSignalResponse(
                            fact="SKU 1 скоро закончится",
                            interpretation="Запаса меньше трёх дней.",
                            recommended_check="Проверить ближайшую поставку.",
                            confidence="high",
                        )
                    ],
                ),
                WbDailyOperationalSectionResponse(
                    key="search",
                    title="Поиск",
                    status="OK",
                    summary=["Есть запросы с улучшением позиции."],
                    metrics=[
                        WbDailyOperationalMetricRowResponse(
                            metric="Средняя позиция",
                            value=12,
                            previous_value=15,
                            delta_abs=-3,
                            trend_7d_pp=Decimal("-1.5"),
                            note="Меньше - лучше.",
                        )
                    ],
                    tables=[],
                    signals=[],
                ),
                WbDailyOperationalSectionResponse(
                    key="priority_checks",
                    title="Приоритетные проверки",
                    status="OK",
                    summary=["Сначала проверить рекламные кампании и остатки."],
                    metrics=[],
                    tables=[],
                    signals=[],
                ),
                WbDailyOperationalSectionResponse(
                    key="scenario",
                    title="Сценарный итог",
                    status="OK",
                    summary=["Без внешней прибыли оцениваем только подтверждённые факты."],
                    metrics=[],
                    tables=[],
                    signals=[],
                ),
            ],
            highlights=WbDailyOperationalHighlightsResponse(
                worse=["ДРР выше порога по кампании 101."],
                better=["Заказы выросли к предыдущему дню."],
                priority_checks=["Проверить кампанию 101 и остатки SKU 1."],
            ),
            diagnostics=WbDailyOperationalDiagnosticsResponse(
                included_sections=["overview", "ads", "assortment", "stock", "search", "priority_checks", "scenario"],
                partial_sections=[],
                excluded_sections=[
                    WbDailyOperationalExcludedSectionResponse(
                        key="profit",
                        title="Прибыль",
                        reason="include_profit=false",
                        source="fact_vvbromo_product_day",
                    )
                ],
                query_count=9,
                execution_ms=42,
                formula_version="v1",
            ),
        )


class EmptyPriceMonitorRepository(FakeRepository):
    def get_price_monitor(self, payload: PriceMonitorRequest) -> PriceMonitorResponse:
        return PriceMonitorResponse(snapshot_date=payload.snapshot_date, rows=0, alerts=0, items=[])


class ScopeCaptureRepository(FakeRepository):
    def __init__(self) -> None:
        self.dashboard_scope: str | None = None
        self.active_products_scope: str | None = None

    def get_dashboard_summary(self, payload: DashboardSummaryRequest) -> DashboardSummaryResponse:
        self.dashboard_scope = payload.scope
        return DashboardSummaryResponse(
            date_from=payload.date_from,
            date_to=payload.date_to,
            rows=1,
            nm_count=1,
            card_clicks=None,
            cart_count=None,
            order_count=None,
            order_sum=None,
            ad_spend=None,
            ad_atbs=None,
            ad_orders=None,
            cpo_total=None,
            cpo_ad=None,
            cost_per_cart_total=None,
            cost_per_cart_ad=None,
            drr=None,
            data_quality=DataQualityResponse(partial_rows=0, empty_rows=0, notes=[]),
        )

    def get_active_products(self, payload: ActiveProductsRequest) -> ActiveProductsResponse:
        self.active_products_scope = payload.scope
        return ActiveProductsResponse(scope=payload.scope, rows=0, items=[])


def build_test_client(*, mcp_public_mode: bool = False, repository=None) -> TestClient:
    settings = McpServiceSettings(
        database_url="postgresql+psycopg://example",
        auth_token="test-token",
        max_rows=500,
        query_timeout_seconds=20,
        max_date_range_days=60,
        mcp_public_mode=mcp_public_mode,
    )
    app = create_app(repository=repository or FakeRepository(), settings=settings)
    return TestClient(app)


def _build_transport_summary_response(*, diagnostic: bool) -> WbDailyOperationalSummaryResponse:
    base = FakeRepository().get_wb_daily_operational_summary(
        WbDailyOperationalSummaryRequest(mode="full", top_n=5, diagnostic=diagnostic)
    )
    signal = {
        "kind": "large_turnover_loss",
        "signal_key": "large_turnover_loss",
        "direction": "negative",
        "entity_type": "product",
        "entity_id": 1,
        "nm_id": 1,
        "metric": "order_sum",
        "title": "??????? ?????? ???????",
        "summary": "?????? ??: ??????? 1 ??? ?????? ???????.",
        "check": {"text": "???????????? ????????: ????????? ?????? ???????? 1."},
        "impact_rub": Decimal("-1234"),
        "cause_status": "needs_check",
        "supporting_signals": [
            {
                "kind": "traffic",
                "summary": "?????????????: ?????? ???????? 1 ????????.",
                "check": {"text": "????????: ????????? ?????."},
                "recommended_check": "????????? ????? ???????? 1.",
                "evidence": ["clicks_down"],
            }
        ],
        "supported_factors": ["traffic"],
        "evidence": ["clicks_down", "orders_down"],
        "missing_evidence": ["confirmed_primary_cause"],
        "recommended_check": "????????? ????? ? ??????? ???????? 1.",
        "recommended_checks": ["????????? ?????", "????????? ???????"],
        "confidence": "medium",
    }
    anomaly = {
        "kind": "orders_without_carts",
        "nm_id": 1,
        "severity": "high",
        "summary": "?????????????: ? ???????? ???? ?????? ??? ??????? ????????.",
    }
    return base.model_copy(update={
        "article_analysis": [
            {
                "nm_id": 1,
                "sales": {"baseline": {"delta_vs_previous_day": Decimal("-1234")}},
                "traffic": {"card_clicks": Decimal("50")},
                "data_quality": {"entry_partial": False},
            }
        ],
        "business_priorities": [signal],
        "ranked_signals": [signal],
        "data_anomalies": [anomaly],
        "analysis_summary": {
            "section_narratives": {
                "overview": {
                    "comment": "?????? ??: ?????? ??? ?????? ???????.",
                    "action": "????????: ????????? ?????? ? ???????.",
                }
            },
            "priority_narratives": [
                {
                    "nm_id": 1,
                    "text": "???????????? ????????: ??????? 1 ?????? ??????.",
                    "action": "????????: ????????? ???????? ? ???????.",
                }
            ],
            "scenario_narrative": "?????????????: ??????? ?????? ???????? ??????? 1.",
            "action_items": [{"text": "????????? ???????? 101."}],
            "priority_checks": [{"text": "????????? ???????? 101."}],
            "user_worse": ["??????? 1 ?????? ??????."],
            "user_better": ["??????? 2 ??????."],
            "top_anomalies": [anomaly],
            "data_quality_checks": ["????????? anomaly orders_without_carts."],
        },
    })


def _collect_keys(payload: Any) -> set[str]:
    if isinstance(payload, dict):
        keys = set(payload.keys())
        for value in payload.values():
            keys.update(_collect_keys(value))
        return keys
    if isinstance(payload, list):
        keys: set[str] = set()
        for item in payload:
            keys.update(_collect_keys(item))
        return keys
    return set()


def _collect_strings(payload: Any) -> list[str]:
    if isinstance(payload, str):
        return [payload]
    if isinstance(payload, dict):
        values: list[str] = []
        for item in payload.values():
            values.extend(_collect_strings(item))
        return values
    if isinstance(payload, list):
        values: list[str] = []
        for item in payload:
            values.extend(_collect_strings(item))
        return values
    return []


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


def test_dashboard_summary_scope_can_be_overridden_to_all_tracked() -> None:
    repository = ScopeCaptureRepository()
    client = build_test_client(repository=repository)
    response = client.post(
        "/tools/get_dashboard_summary",
        headers={"Authorization": "Bearer test-token"},
        json={"date_from": "2026-06-07", "date_to": "2026-06-18", "scope": "all_tracked"},
    )
    assert response.status_code == 200
    assert repository.dashboard_scope == "all_tracked"


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
        "get_mart_schema",
        "get_dashboard_summary",
        "get_product_metrics",
        "get_price_monitor",
        "get_active_products",
        "get_wb_daily_operational_summary",
    ]
    assert "PostgreSQL" in payload["result"]["tools"][0]["description"]
    assert "реальную схему таблицы mart_total_report" in payload["result"]["tools"][1]["description"]
    assert "витрине mart_total_report" in payload["result"]["tools"][2]["description"]
    assert "одного товара" in payload["result"]["tools"][3]["description"]
    assert "мониторинга цен WB" in payload["result"]["tools"][4]["description"]


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
    text = payload["result"]["content"][0]["text"]
    assert "db_health:" in text
    assert "ok: true" in text
    assert "rows: 7434" in text
    assert "min_date: 2026-02-12" in text


def test_mcp_tools_call_get_mart_schema_returns_schema_content() -> None:
    client = build_test_client()
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {"name": "get_mart_schema", "arguments": {}},
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["structuredContent"]["table_name"] == "mart_total_report"
    assert payload["result"]["structuredContent"]["columns"][0]["column_name"] == "report_date"
    text = payload["result"]["content"][0]["text"]
    assert "mart_schema:" in text
    assert "table_name: mart_total_report" in text
    assert "columns_tsv:" in text
    assert "column_name\tdata_type" in text


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
    text = payload["result"]["content"][0]["text"]
    assert "dashboard_summary:" in text
    assert "date_from: 2026-06-07" in text
    assert "date_to: 2026-06-18" in text
    assert "rows: 12" in text
    assert "nm_count: 3" in text
    assert "card_clicks_total: 77" in text
    assert "notes: tracked scope" in text


def test_mcp_tools_call_product_metrics_returns_human_readable_content() -> None:
    client = build_test_client()
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "get_product_metrics",
                "arguments": {
                    "nm_id": 91470767,
                    "date_from": "2026-06-07",
                    "date_to": "2026-06-18",
                },
            },
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["structuredContent"]["nm_id"] == 91470767
    assert payload["result"]["structuredContent"]["analysis_status"] == "LIMITED"
    assert payload["result"]["structuredContent"]["data_quality"]["wb_buyer_price_missing"] is True
    assert "price_cause" in payload["result"]["structuredContent"]["forbidden_inferences"]
    text = payload["result"]["content"][0]["text"]
    assert "product:" in text
    assert "nm_id: 91470767" in text
    assert "supplier_article: demo-art" in text
    assert "summary:" in text
    assert "DATA_QUALITY:" in text
    assert "SOURCE_COVERAGE:" in text
    assert "ANALYSIS_STATUS:" in text
    assert "ANALYSIS_LIMITS:" in text
    assert "rows_tsv:" in text
    assert "date\tcard_clicks\tctr\tcart_count\tadd_to_cart_conversion\torder_count\tcart_to_order_conversion\torder_sum" in text
    assert "2026-06-18\t0\t0\t0\t0\t0\t0\t0" in text


def test_mcp_tools_call_price_monitor_returns_human_readable_content() -> None:
    client = build_test_client()
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "get_price_monitor",
                "arguments": {
                    "snapshot_date": "2026-06-18",
                    "alerts_only": False,
                },
            },
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["structuredContent"]["rows"] == 2
    text = payload["result"]["content"][0]["text"]
    assert "price_monitor:" in text
    assert "snapshot_date: 2026-06-18" in text
    assert "rows: 2" in text
    assert "alerts: 1" in text
    assert "rows_tsv:" in text
    assert "91470767\tavokadogirl\t799\t799\t0\tsuccess\tfalse\thttps://www.wildberries.ru/catalog/91470767/detail.aspx" in text


def test_get_active_products_default_scope_is_core() -> None:
    client = build_test_client()
    response = client.post(
        "/tools/get_active_products",
        headers={"Authorization": "Bearer test-token"},
        json={},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["scope"] == "core"
    assert payload["rows"] == 2
    assert payload["items"][0]["analytics_active"] is True
    assert payload["items"][0]["price_monitor_enabled"] is True


def test_get_active_products_scope_can_be_overridden_to_price_monitor() -> None:
    repository = ScopeCaptureRepository()
    client = build_test_client(repository=repository)
    response = client.post(
        "/tools/get_active_products",
        headers={"Authorization": "Bearer test-token"},
        json={"scope": "price_monitor"},
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["scope"] == "price_monitor"
    assert repository.active_products_scope == "price_monitor"


def test_mcp_tools_call_get_active_products_returns_human_readable_content() -> None:
    client = build_test_client()
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "get_active_products",
                "arguments": {},
            },
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["structuredContent"]["scope"] == "core"
    assert payload["result"]["structuredContent"]["rows"] == 2
    text = payload["result"]["content"][0]["text"]
    assert "active_products:" in text
    assert "scope: core" in text
    assert "rows: 2" in text
    assert "rows_tsv:" in text
    assert "91470767\tavokadogirl\tТрусы детские\tBANDE\tТрусы\ttrue\ttrue\tactive\tprice_monitor_seed" in text


def test_mcp_tools_call_price_monitor_returns_empty_response_without_500() -> None:
    client = build_test_client(repository=EmptyPriceMonitorRepository())
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "get_price_monitor",
                "arguments": {
                    "snapshot_date": "2026-06-20",
                    "alerts_only": False,
                },
            },
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["structuredContent"]["rows"] == 0
    assert payload["result"]["structuredContent"]["items"] == []
    text = payload["result"]["content"][0]["text"]
    assert "price_monitor:" in text
    assert "rows: 0" in text
    assert "alerts: 0" in text
    assert "rows_tsv:" in text


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


def test_build_price_monitor_response_returns_empty_payload_without_error() -> None:
    payload = PriceMonitorRequest(snapshot_date=date(2026, 6, 20), alerts_only=False)
    response = build_price_monitor_response(payload, [], [])
    assert response.rows == 0
    assert response.alerts == 0
    assert response.items == []


def test_mcp_tools_call_wb_daily_operational_summary_returns_structured_content() -> None:
    client = build_test_client()
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {
                "name": "get_wb_daily_operational_summary",
                "arguments": {
                    "mode": "full",
                    "top_n": 5,
                    "diagnostic": True,
                },
            },
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["isError"] is False
    structured = payload["result"]["structuredContent"]
    assert structured["formula_version"] == "v1"
    assert structured["report_window"]["report_date"] == "2026-06-18"
    assert structured["requested_options"]["mode"] == "full"
    assert structured["diagnostics"]["query_count"] == 9
    assert structured["diagnostics"]["excluded_sections"][0]["key"] == "profit"
    assert structured["article_context"] == []
    assert structured["warehouse_context"] == []
    assert structured["campaign_context"] == []
    assert structured["search_query_context"] == []
    assert structured["entry_point_context"] == []
    assert structured["price_context"] == []
    assert structured["logistics_context"] == []
    assert structured["data_gaps"] == []
    section_keys = [section["key"] for section in structured["sections"]]
    assert "overview" in section_keys
    assert "ads" in section_keys
    body_text = payload["result"]["content"][0]["text"]
    assert body_text == (
        "\u0421\u0444\u043e\u0440\u043c\u0438\u0440\u0443\u0439 \u043f\u043e\u0434\u0440\u043e\u0431\u043d\u0443\u044e \u043e\u043f\u0435\u0440\u0430\u0446\u0438\u043e\u043d\u043d\u0443\u044e \u0441\u0432\u043e\u0434\u043a\u0443 \u043d\u0430 \u0440\u0443\u0441\u0441\u043a\u043e\u043c \u044f\u0437\u044b\u043a\u0435 \u043f\u043e structuredContent.\n"
        "\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 \u0442\u043e\u043b\u044c\u043a\u043e \u043f\u0435\u0440\u0435\u0434\u0430\u043d\u043d\u044b\u0435 \u0434\u0430\u043d\u043d\u044b\u0435. \u041d\u0435 \u0443\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0439 \u043f\u0440\u0438\u0447\u0438\u043d\u043d\u043e\u0441\u0442\u044c \u0431\u0435\u0437 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u044f.\n"
        "\u041d\u0435 \u043a\u043e\u043f\u0438\u0440\u0443\u0439 server-generated narrative \u043c\u0435\u0445\u0430\u043d\u0438\u0447\u0435\u0441\u043a\u0438."
    )
    assert "ЕЖЕДНЕВНАЯ ОПЕРАТИВНАЯ СВОДКА WILDBERRIES" not in body_text
    assert "Проблемные кампании" not in body_text
    expected = render_wb_daily_operational_summary_markdown(
        FakeRepository().get_wb_daily_operational_summary(
            WbDailyOperationalSummaryRequest(mode="full", top_n=5, diagnostic=True)
        )
    )
    assert structured["legacy_markdown"] == expected
    assert structured["legacy_markdown"] != body_text

def test_wb_daily_operational_summary_normal_payload_removes_server_generated_narratives() -> None:
    response = _build_transport_summary_response(diagnostic=False)
    payload = _build_tool_result_payload(response)
    structured = payload["structuredContent"]

    assert payload["content"][0]["text"] == WB_DAILY_OPERATIONAL_SUMMARY_CONTENT_HINT
    assert "legacy_markdown" not in structured
    forbidden_keys = {
        "analysis_summary",
        "check",
        "highlights",
        "legacy_markdown",
        "note",
        "notes",
        "recommended_check",
        "recommended_checks",
        "signals",
        "summary",
    }
    assert forbidden_keys.isdisjoint(_collect_keys(structured))

    strings = _collect_strings(structured)
    for marker_text in (
        "\u041c\u043d\u0435\u043d\u0438\u0435 \u0418\u0418",
        "\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u0435",
        "\u0418\u043d\u0442\u0435\u0440\u043f\u0440\u0435\u0442\u0430\u0446\u0438\u044f",
        "\u041f\u0440\u0438\u043e\u0440\u0438\u0442\u0435\u0442\u043d\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430",
        "<!-- FINAL_USER_REPORT",
    ):
        assert all(marker_text not in item for item in strings)


def test_wb_daily_operational_summary_diagnostic_payload_keeps_legacy_markdown_and_narratives() -> None:
    response = _build_transport_summary_response(diagnostic=True)
    payload = _build_tool_result_payload(response)
    structured = payload["structuredContent"]

    assert payload["content"][0]["text"] == WB_DAILY_OPERATIONAL_SUMMARY_CONTENT_HINT
    assert "legacy_markdown" in structured
    assert "analysis_summary" in structured
    assert "highlights" in structured
    assert "summary" in structured["sections"][0]
    assert any(section.get("signals") for section in structured["sections"])
    assert structured["business_priorities"][0]["summary"]
    assert structured["ranked_signals"][0]["check"]["text"]


def test_wb_daily_operational_summary_normal_payload_preserves_numeric_and_rich_analysis_fields() -> None:
    response = _build_transport_summary_response(diagnostic=False)
    original = response.model_dump(mode="json")
    structured = _build_tool_result_payload(response)["structuredContent"]

    assert structured["sections"][0]["metrics"][0]["value"] == original["sections"][0]["metrics"][0]["value"]
    assert structured["sections"][0]["metrics"][0]["delta_pct"] == original["sections"][0]["metrics"][0]["delta_pct"]
    assert structured["article_analysis"] == original["article_analysis"]
    assert structured["business_priorities"][0]["impact_rub"] == original["business_priorities"][0]["impact_rub"]
    assert structured["business_priorities"][0]["supported_factors"] == original["business_priorities"][0]["supported_factors"]
    assert structured["business_priorities"][0]["evidence"] == original["business_priorities"][0]["evidence"]
    assert structured["business_priorities"][0]["missing_evidence"] == original["business_priorities"][0]["missing_evidence"]
    assert structured["ranked_signals"][0]["supporting_signals"][0]["kind"] == original["ranked_signals"][0]["supporting_signals"][0]["kind"]
    assert "summary" not in structured["ranked_signals"][0]["supporting_signals"][0]


def test_resolve_report_date_chooses_last_full_day() -> None:
    freshness = [
        {"source": "mart_total_report", "max_date": date(2026, 7, 15)},
        {"source": "fact_funnel_day", "max_date": date(2026, 7, 14)},
        {"source": "fact_ad_cost_day", "max_date": date(2026, 7, 15)},
    ]
    report_date, source = resolve_report_date(None, freshness, now_date=date(2026, 7, 16))
    assert report_date == date(2026, 7, 14)
    assert source == "auto_core_min"


def test_resolve_report_date_rejects_current_day() -> None:
    freshness = [
        {"source": "mart_total_report", "max_date": date(2026, 7, 16)},
    ]
    try:
        resolve_report_date(date(2026, 7, 16), freshness, now_date=date(2026, 7, 16))
    except ValueError as exc:
        assert "earlier than current Moscow date" in str(exc)
    else:
        raise AssertionError("Expected ValueError for current-day report request")


def test_mcp_tools_call_wb_daily_operational_summary_defaults_to_full_when_mode_omitted() -> None:
    client = build_test_client()
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {
                "name": "get_wb_daily_operational_summary",
                "arguments": {
                    "top_n": 5,
                    "diagnostic": False,
                },
            },
        },
    )
    payload = response.json()
    assert response.status_code == 200
    assert payload["result"]["structuredContent"]["requested_options"]["mode"] == "full"


def test_wb_daily_operational_summary_brief_and_full_share_same_structured_metrics() -> None:
    repository = FakeRepository()
    full = repository.get_wb_daily_operational_summary(WbDailyOperationalSummaryRequest(mode="full", top_n=5))
    brief = repository.get_wb_daily_operational_summary(WbDailyOperationalSummaryRequest(mode="brief", top_n=5))
    assert full.sections[0].metrics[0].value == brief.sections[0].metrics[0].value
    assert full.sections[0].metrics[0].previous_value == brief.sections[0].metrics[0].previous_value
    assert full.sections[0].metrics[0].delta_pct == brief.sections[0].metrics[0].delta_pct
    assert full.sections[0].metrics[0].trend_7d_pct == brief.sections[0].metrics[0].trend_7d_pct


def test_wb_daily_operational_summary_full_markdown_contains_required_sections() -> None:
    markdown = render_wb_daily_operational_summary_markdown(
        FakeRepository().get_wb_daily_operational_summary(
            WbDailyOperationalSummaryRequest(mode="full", top_n=5, diagnostic=False)
        )
    )
    required_sections = [
        "Главное за день",
        "Трафик и видимость",
        "Воронка и конверсия",
        "Рекламная эффективность",
        "Продажи и оборот",
        "Прибыль и расходы",
        "Остатки и склады",
        "Ассортимент",
        "Поиск и видимость",
        "Приоритетные проверки",
        "Сценарный итог",
    ]
    for section in required_sections:
        assert section in markdown
    assert "Тренд 7 дней" in markdown
    assert "include_profit" in markdown


def test_wb_daily_operational_summary_brief_markdown_is_shorter_than_full() -> None:
    repository = FakeRepository()
    full_markdown = render_wb_daily_operational_summary_markdown(
        repository.get_wb_daily_operational_summary(WbDailyOperationalSummaryRequest(mode="full", top_n=5))
    )
    brief_markdown = render_wb_daily_operational_summary_markdown(
        repository.get_wb_daily_operational_summary(WbDailyOperationalSummaryRequest(mode="brief", top_n=5))
    )
    assert len(brief_markdown) < len(full_markdown)
