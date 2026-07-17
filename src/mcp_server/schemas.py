from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_encoders={Decimal: lambda value: float(value)},
    )


class ToolBaseRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")


ProductScope = Literal["core", "all_tracked", "price_monitor"]


class DashboardSummaryRequest(ToolBaseRequest):
    date_from: date
    date_to: date
    only_tracked: bool = True
    scope: ProductScope = "core"


class ProductMetricsRequest(ToolBaseRequest):
    nm_id: int
    date_from: date
    date_to: date
    scope: ProductScope = "core"


class PriceMonitorRequest(ToolBaseRequest):
    snapshot_date: date
    alerts_only: bool = False
    scope: ProductScope = "core"


class ActiveProductsRequest(ToolBaseRequest):
    scope: ProductScope = "core"


class HealthResponse(ApiModel):
    ok: bool = True


class DbHealthResponse(ApiModel):
    ok: bool
    rows: int
    min_date: date | None
    max_date: date | None


class MartSchemaColumnResponse(ApiModel):
    column_name: str
    data_type: str


class MartSchemaResponse(ApiModel):
    table_name: str
    columns: list[MartSchemaColumnResponse]


class DataQualityResponse(ApiModel):
    partial_rows: int
    empty_rows: int
    notes: list[str]


class DashboardSummaryResponse(ApiModel):
    date_from: date
    date_to: date
    rows: int
    nm_count: int
    card_clicks: Decimal | None
    cart_count: Decimal | None
    order_count: Decimal | None
    order_sum: Decimal | None
    ad_spend: Decimal | None
    ad_atbs: Decimal | None
    ad_orders: Decimal | None
    cpo_total: Decimal | None
    cpo_ad: Decimal | None
    cost_per_cart_total: Decimal | None
    cost_per_cart_ad: Decimal | None
    drr: Decimal | None
    data_quality: DataQualityResponse


class ProductDailyMetricsResponse(ApiModel):
    date: date
    card_clicks: Decimal | None
    ctr: Decimal | None
    cart_count: Decimal | None
    add_to_cart_conversion: Decimal | None
    order_count: Decimal | None
    cart_to_order_conversion: Decimal | None
    order_sum: Decimal | None
    ad_spend: Decimal | None
    ad_clicks: Decimal | None
    ad_atbs: Decimal | None
    ad_orders: Decimal | None
    current_stock_qty: Decimal | None
    wb_buyer_price: Decimal | None


class ProductSummaryResponse(ApiModel):
    card_clicks_total: Decimal | None = None
    cart_count: Decimal | None
    order_count: Decimal | None
    order_sum: Decimal | None
    ad_spend: Decimal | None
    avg_ctr: Decimal | None = None
    avg_add_to_cart_conversion: Decimal | None = None
    avg_cart_to_order_conversion: Decimal | None = None
    order_sum_available_dates_count: int = 0
    order_sum_missing_dates_count: int = 0


class ProductPeriodMetaResponse(ApiModel):
    rows_count: int
    days_requested: int
    days_returned: int


class ProductDataQualityResponse(ApiModel):
    order_sum_available_dates_count: int
    order_sum_missing_dates_count: int
    order_sum_missing_for_dates: list[date]
    wb_buyer_price_missing: bool
    ad_metrics_missing: bool
    stock_by_size_missing: bool
    delivery_time_missing: bool
    cannot_calculate_period_ctr_without_impressions: bool


class ProductMetricsResponse(ApiModel):
    found: bool = True
    nm_id: int
    supplier_article: str | None = None
    product_name: str | None = None
    date_from: date
    date_to: date
    daily: list[ProductDailyMetricsResponse]
    summary: ProductSummaryResponse
    period_meta: ProductPeriodMetaResponse
    source_coverage: dict[str, str]
    data_quality: ProductDataQualityResponse
    field_definitions: dict[str, str]
    null_semantics: dict[str, str]
    analysis_status: str
    allowed_inferences: list[str]
    forbidden_inferences: list[str]
    analysis_limits: list[str]


class PriceMonitorItemResponse(ApiModel):
    nm_id: int
    supplier_article: str | None = None
    product_name: str | None = None
    snapshot_date: date
    buyer_visible_price: Decimal | None
    previous_price: Decimal | None
    price_delta: Decimal | None
    is_alert: bool
    alert_reason: str | None
    fetch_status: str
    product_url: str | None = None


class PriceMonitorResponse(ApiModel):
    snapshot_date: date
    rows: int
    alerts: int
    items: list[PriceMonitorItemResponse]


class ActiveProductsItemResponse(ApiModel):
    nm_id: int
    supplier_article: str | None = None
    title: str | None = None
    brand: str | None = None
    category: str | None = None
    subject: str | None = None
    analytics_active: bool
    price_monitor_enabled: bool
    lifecycle_status: str | None = None
    reason: str | None = None


class ActiveProductsResponse(ApiModel):
    scope: ProductScope
    rows: int
    items: list[ActiveProductsItemResponse]


SummaryMode = Literal["full", "brief"]


class WbDailyOperationalSummaryRequest(ToolBaseRequest):
    report_date: date | None = None
    mode: SummaryMode = "full"
    include_profit: bool = False
    include_partial_sections: bool = False
    top_n: int = Field(default=5, ge=1, le=7)
    diagnostic: bool = False


class WbDailyOperationalReportWindowResponse(ApiModel):
    report_date: date
    compare_date: date
    trend_current_from: date
    trend_current_to: date
    trend_previous_from: date
    trend_previous_to: date
    report_date_source: str


class WbDailyOperationalSourceFreshnessResponse(ApiModel):
    source: str
    max_date: date | None
    status: str
    lag_days: int | None = None


class WbDailyOperationalMetricRowResponse(ApiModel):
    metric: str
    value: Any = None
    previous_value: Any = None
    delta_abs: Any = None
    delta_pct: Decimal | None = None
    delta_pp: Decimal | None = None
    trend_7d_pct: Decimal | None = None
    trend_7d_pp: Decimal | None = None
    note: str | None = None


class WbDailyOperationalTableResponse(ApiModel):
    title: str
    columns: list[str]
    rows: list[dict[str, Any]]
    note: str | None = None


class WbDailyOperationalSignalResponse(ApiModel):
    fact: str
    interpretation: str | None = None
    recommended_check: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"


class WbDailyOperationalSectionResponse(ApiModel):
    key: str
    title: str
    status: Literal["OK", "PARTIAL", "STALE", "EXCLUDED"]
    summary: list[str] = Field(default_factory=list)
    metrics: list[WbDailyOperationalMetricRowResponse] = Field(default_factory=list)
    tables: list[WbDailyOperationalTableResponse] = Field(default_factory=list)
    signals: list[WbDailyOperationalSignalResponse] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    excluded_reason: str | None = None


class WbDailyOperationalExcludedSectionResponse(ApiModel):
    key: str
    title: str
    reason: str
    source: str | None = None


class WbDailyOperationalHighlightsResponse(ApiModel):
    worse: list[str] = Field(default_factory=list)
    better: list[str] = Field(default_factory=list)
    priority_checks: list[str] = Field(default_factory=list)


class WbDailyOperationalDiagnosticsResponse(ApiModel):
    included_sections: list[str] = Field(default_factory=list)
    partial_sections: list[str] = Field(default_factory=list)
    excluded_sections: list[WbDailyOperationalExcludedSectionResponse] = Field(default_factory=list)
    query_count: int = 0
    execution_ms: int | None = None
    query_timings: list[dict[str, Any]] = Field(default_factory=list)
    formula_version: str = "v1"


class WbDailyOperationalSummaryResponse(ApiModel):
    formula_version: str
    report_window: WbDailyOperationalReportWindowResponse
    requested_options: dict[str, Any]
    source_freshness: list[WbDailyOperationalSourceFreshnessResponse]
    sections: list[WbDailyOperationalSectionResponse]
    highlights: WbDailyOperationalHighlightsResponse
    diagnostics: WbDailyOperationalDiagnosticsResponse
    article_context: list[dict[str, Any]] = Field(default_factory=list)
    warehouse_context: list[dict[str, Any]] = Field(default_factory=list)
    campaign_context: list[dict[str, Any]] = Field(default_factory=list)
    search_query_context: list[dict[str, Any]] = Field(default_factory=list)
    entry_point_context: list[dict[str, Any]] = Field(default_factory=list)
    price_context: list[dict[str, Any]] = Field(default_factory=list)
    logistics_context: list[dict[str, Any]] = Field(default_factory=list)
    data_gaps: list[dict[str, Any]] = Field(default_factory=list)


class ErrorResponse(ApiModel):
    detail: str
    code: str | None = None
    extra: dict[str, Any] | None = Field(default=None)

