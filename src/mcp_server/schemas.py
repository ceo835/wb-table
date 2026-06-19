from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_encoders={Decimal: lambda value: float(value)},
    )


class ToolBaseRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")


class DashboardSummaryRequest(ToolBaseRequest):
    date_from: date
    date_to: date
    only_tracked: bool = True


class ProductMetricsRequest(ToolBaseRequest):
    nm_id: int
    date_from: date
    date_to: date


class PriceMonitorRequest(ToolBaseRequest):
    snapshot_date: date
    alerts_only: bool = False


class HealthResponse(ApiModel):
    ok: bool = True


class DbHealthResponse(ApiModel):
    ok: bool
    rows: int
    min_date: date | None
    max_date: date | None


class DataQualityResponse(ApiModel):
    partial_rows: int
    empty_rows: int
    notes: list[str]


class DashboardSummaryResponse(ApiModel):
    date_from: date
    date_to: date
    rows: int
    nm_count: int
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
    cart_count: Decimal | None
    order_count: Decimal | None
    order_sum: Decimal | None
    ad_spend: Decimal | None
    ad_clicks: Decimal | None
    ad_atbs: Decimal | None
    ad_orders: Decimal | None
    current_stock_qty: Decimal | None
    wb_buyer_price: Decimal | None


class ProductSummaryResponse(ApiModel):
    cart_count: Decimal | None
    order_count: Decimal | None
    order_sum: Decimal | None
    ad_spend: Decimal | None


class ProductMetricsResponse(ApiModel):
    found: bool = True
    nm_id: int
    supplier_article: str | None = None
    product_name: str | None = None
    date_from: date
    date_to: date
    daily: list[ProductDailyMetricsResponse]
    summary: ProductSummaryResponse


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


class ErrorResponse(ApiModel):
    detail: str
    code: str | None = None
    extra: dict[str, Any] | None = Field(default=None)
