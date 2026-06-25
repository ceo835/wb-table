from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class TimestampMixin:
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class StatusMixin(TimestampMixin):
    data_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_status: Mapped[str | None] = mapped_column(String(128), nullable=True)


class RawApiResponse(Base, TimestampMixin):
    __tablename__ = "raw_api_response"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "endpoint_name",
            "request_hash",
            "response_received_at",
            name="uq_raw_api_response_request",
        ),
        Index("idx_raw_api_response_source_time", "source_system", "endpoint_name", "response_received_at"),
        Index("idx_raw_api_response_request_hash", "request_hash"),
        Index("idx_raw_api_response_batch_id", "load_batch_id"),
    )

    raw_response_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    load_batch_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid4)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint_name: Mapped[str] = mapped_column(String(128), nullable=False)
    http_method: Mapped[str | None] = mapped_column(String(16), nullable=True)
    request_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    request_params_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    response_body_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    rows_detected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parse_status: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApiLoadLog(Base, TimestampMixin):
    __tablename__ = "api_load_log"
    __table_args__ = (
        UniqueConstraint(
            "load_batch_id",
            "target_table",
            "endpoint_name",
            "window_start",
            "window_end",
            name="uq_api_load_log_batch_target_window",
        ),
        Index("idx_api_load_log_target_time", "target_table", "started_at"),
        Index("idx_api_load_log_batch", "load_batch_id"),
        Index("idx_api_load_log_status", "status"),
    )

    api_load_log_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    load_batch_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid4)
    target_table: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    objects_read: Mapped[int | None] = mapped_column(Integer, nullable=True)
    objects_written: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warning_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_short: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_status: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ValidationWarning(Base):
    __tablename__ = "validation_warning"
    __table_args__ = (
        UniqueConstraint("warning_rule", "sheet_name", "business_key_hash", name="uq_validation_warning_business_key"),
        Index("idx_validation_warning_rule_time", "warning_rule", "created_at"),
        Index("idx_validation_warning_sheet_date", "sheet_name", "date"),
        Index("idx_validation_warning_nm_id", "nm_id"),
    )

    validation_warning_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    warning_rule: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="warn")
    sheet_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_table: Mapped[str] = mapped_column(String(128), nullable=False)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    advert_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    business_key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    source_status: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DimProduct(Base, StatusMixin):
    __tablename__ = "dim_product"
    __table_args__ = (
        Index("idx_dim_product_supplier_article", "supplier_article"),
        Index("idx_dim_product_brand_subject", "brand", "subject"),
    )

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    supplier_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    card_rating: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    reviews_rating: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    reviews_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_deleted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class DimCampaign(Base, TimestampMixin):
    __tablename__ = "dim_campaign"
    __table_args__ = (
        Index("idx_dim_campaign_type_status", "campaign_type", "status"),
        Index("idx_dim_campaign_name", "campaign_name"),
    )

    advert_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    campaign_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    campaign_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    section_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section_display: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    nm_id_parse_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_status: Mapped[str | None] = mapped_column(String(128), nullable=True)


class DimDate(Base):
    __tablename__ = "dim_date"

    calendar_date: Mapped[date] = mapped_column(Date, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    month_name: Mapped[str] = mapped_column(String(32), nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    day_name: Mapped[str] = mapped_column(String(32), nullable=False)
    is_weekend: Mapped[bool] = mapped_column(Boolean, nullable=False)


class SettingsProducts(Base, TimestampMixin):
    __tablename__ = "settings_products"
    __table_args__ = (
        Index("idx_settings_products_active", "active"),
        Index("idx_settings_products_group_name", "group_name"),
        Index("idx_settings_products_report_mode", "report_mode"),
    )

    nm_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    supplier_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    group_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    query_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_new: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    report_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="main")
    source_list: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class SettingsReportColumns(Base, TimestampMixin):
    __tablename__ = "settings_report_columns"
    __table_args__ = (
        UniqueConstraint("report_name", "export_column_key", name="uq_settings_report_columns_report_key"),
        Index("idx_settings_report_columns_report_order", "report_name", "display_order"),
        Index("idx_settings_report_columns_active", "is_active"),
    )

    report_column_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_name: Mapped[str] = mapped_column(String(128), nullable=False)
    export_column_key: Mapped[str] = mapped_column(String(255), nullable=False)
    export_column_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_table: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pivot_dimension: Mapped[str | None] = mapped_column(String(128), nullable=True)
    calculation_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class SettingsLostProfitMarketArea(Base):
    __tablename__ = "settings_lost_profit_market_areas"

    market_area_code: Mapped[str] = mapped_column(Text, primary_key=True)
    market_area_name: Mapped[str] = mapped_column(Text, nullable=False)
    population_people: Mapped[int] = mapped_column(Integer, nullable=False)
    population_share_pct: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="pending_ivan_review",
        server_default="pending_ivan_review",
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SettingsLostProfitWarehouseArea(Base):
    __tablename__ = "settings_lost_profit_warehouse_areas"
    __table_args__ = (
        Index("idx_settings_lost_profit_warehouse_areas_market_area_code", "market_area_code"),
    )

    warehouse_name: Mapped[str] = mapped_column(Text, primary_key=True)
    market_area_code: Mapped[str] = mapped_column(
        Text,
        ForeignKey("settings_lost_profit_market_areas.market_area_code"),
        nullable=False,
    )
    approval_status: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="pending_ivan_review",
        server_default="pending_ivan_review",
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class FactFunnelDay(Base, StatusMixin):
    __tablename__ = "fact_funnel_day"
    __table_args__ = (
        UniqueConstraint("date", "nm_id", name="uq_fact_funnel_day_date_nm_id"),
        Index("idx_fact_funnel_day_date_nm", "date", "nm_id"),
        Index("idx_fact_funnel_day_nm_date", "nm_id", "date"),
        Index("idx_fact_funnel_day_status", "source_status"),
    )

    fact_funnel_day_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    impressions: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    impressions_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    card_clicks: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    card_clicks_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ctr_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    revenue_share_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    revenue_share_percent_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cart_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    cart_count_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    wishlist_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    wishlist_count_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    order_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    order_count_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    buyout_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    buyout_count_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    cancel_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    cancel_count_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    add_to_cart_conversion: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    add_to_cart_conversion_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cart_to_order_conversion: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cart_to_order_conversion_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    buyout_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    buyout_percent_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    order_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    order_sum_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    buyout_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    buyout_sum_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cancel_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cancel_sum_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    avg_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    avg_price_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    avg_orders_per_day: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    avg_orders_per_day_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    avg_delivery_time: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    avg_delivery_time_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    local_orders_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    local_orders_percent_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


class FactAdCostEvent(Base, StatusMixin):
    __tablename__ = "fact_ad_cost_event"
    __table_args__ = (
        UniqueConstraint(
            "date",
            "advert_id",
            "document_number",
            "writeoff_datetime",
            "spend",
            name="uq_fact_ad_cost_event_natural_key",
        ),
        Index("idx_fact_ad_cost_event_date_advert", "date", "advert_id"),
        Index("idx_fact_ad_cost_event_nm_date", "nm_id", "date"),
        Index("idx_fact_ad_cost_event_document", "document_number"),
    )

    fact_ad_cost_event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    writeoff_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    advert_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    writeoff_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    spend: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    section_display: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nm_id_from_section: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    nm_id_from_campaign_name: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    nm_id_parse_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    campaign_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)


class FactAdCostDay(Base, StatusMixin):
    __tablename__ = "fact_ad_cost_day"
    __table_args__ = (
        UniqueConstraint("date", "advert_id", "nm_id", name="uq_fact_ad_cost_day_date_advert_nm_id"),
        Index("idx_fact_ad_cost_day_date_nm", "date", "nm_id"),
        Index("idx_fact_ad_cost_day_advert_date", "advert_id", "date"),
    )

    fact_ad_cost_day_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    advert_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    campaign_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_spend: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    events_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allocation_status: Mapped[str | None] = mapped_column(String(64), nullable=True)


class FactAdCampaignDay(Base, StatusMixin):
    __tablename__ = "fact_ad_campaign_day"
    __table_args__ = (
        UniqueConstraint("date", "advert_id", "row_type", name="uq_fact_ad_campaign_day_date_advert_row_type"),
        Index("idx_fact_ad_campaign_day_date_advert", "date", "advert_id"),
        Index("idx_fact_ad_campaign_day_row_type", "row_type"),
    )

    fact_ad_campaign_day_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    advert_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ad_views: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_clicks: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_atbs: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_orders: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ordered_items_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_cancels: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_spend: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ad_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    avg_position: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_ctr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cpc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cpm: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_roi: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)


class FactAdCampaignNmDay(Base, StatusMixin):
    __tablename__ = "fact_ad_campaign_nm_day"
    __table_args__ = (
        UniqueConstraint(
            "date",
            "advert_id",
            "row_type",
            "conversion_type_raw",
            "nm_id",
            name="uq_fact_ad_campaign_nm_day_natural_key",
        ),
        Index("idx_fact_ad_campaign_nm_day_date_nm", "date", "nm_id"),
        Index("idx_fact_ad_campaign_nm_day_advert", "advert_id", "date"),
        Index("idx_fact_ad_campaign_nm_day_conversion", "conversion_type", "row_type"),
    )

    fact_ad_campaign_nm_day_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    advert_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_type: Mapped[str] = mapped_column(String(64), nullable=False)
    conversion_type_raw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversion_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversion_type_display: Mapped[str | None] = mapped_column(String(128), nullable=True)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    product_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    ad_views: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_clicks: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_atbs: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_orders: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ordered_items_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_cancels: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_spend: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ad_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    avg_position: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_ctr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cpc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cpm: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_roi: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)


class FactAdvertMetadata(Base, TimestampMixin):
    __tablename__ = "fact_advert_metadata"
    __table_args__ = (
        UniqueConstraint("advert_id", name="uq_fact_advert_metadata_advert_id"),
        Index("idx_fact_advert_metadata_advert_id", "advert_id"),
        Index("idx_fact_advert_metadata_status", "status"),
        Index("idx_fact_advert_metadata_primary_nm_id", "primary_nm_id"),
    )

    fact_advert_metadata_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    advert_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    campaign_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary_nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    linked_nm_ids_json: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    placements_json: Mapped[list[str] | dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_payload_json: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    source_status: Mapped[str | None] = mapped_column(String(128), nullable=True)


class AdFullstatsFailedGroup(Base):
    __tablename__ = "ad_fullstats_failed_group"
    __table_args__ = (
        UniqueConstraint(
            "date_from",
            "date_to",
            "advert_id",
            "group_key",
            name="uq_ad_fullstats_failed_group_scope",
        ),
        Index("idx_ad_fullstats_failed_group_advert_id", "advert_id"),
        Index("idx_ad_fullstats_failed_group_date_range", "date_from", "date_to"),
        Index("idx_ad_fullstats_failed_group_status", "status"),
        Index("idx_ad_fullstats_failed_group_next_retry_at", "next_retry_at"),
    )

    ad_fullstats_failed_group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    advert_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_key: Mapped[str] = mapped_column(String(255), nullable=False)
    campaign_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    nm_ids_json: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class FactSearchQueryMetric(Base, StatusMixin):
    __tablename__ = "fact_search_query_metric"
    __table_args__ = (
        UniqueConstraint(
            "period_start",
            "period_end",
            "nm_id",
            "search_query",
            name="uq_fact_search_query_metric_period_nm_query",
        ),
        Index("idx_fact_search_query_metric_period_nm", "period_start", "period_end", "nm_id"),
        Index("idx_fact_search_query_metric_query", "search_query"),
        Index("idx_fact_search_query_metric_nm_query", "nm_id", "search_query"),
    )

    fact_search_query_metric_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    card_rating: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    reviews_rating: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    search_query: Mapped[str] = mapped_column(Text, nullable=False)
    query_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    query_count_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    visibility: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    avg_position: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    median_position: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    visibility_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    avg_position_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    median_position_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    search_clicks: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    search_clicks_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    search_clicks_competitor_percentile: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    search_cart: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    search_cart_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    search_cart_competitor_percentile: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cart_conversion: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cart_conversion_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cart_conversion_competitor_percentile: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    search_orders: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    search_orders_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    search_orders_competitor_percentile: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    order_conversion: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    order_conversion_prev: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    order_conversion_competitor_percentile: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    competitor_metrics_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    min_discount_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    max_discount_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)


class FactWbSearchQueryTextDay(Base, TimestampMixin):
    __tablename__ = "fact_wb_search_query_text_day"
    __table_args__ = (
        UniqueConstraint("day", "nm_id", "query_text", name="uq_fact_wb_search_query_text_day_day_nm_query_text"),
        Index("idx_fact_wb_search_query_text_day_day_nm", "day", "nm_id"),
        Index("idx_fact_wb_search_query_text_day_query_group", "query_group", "day"),
        Index("idx_fact_wb_search_query_text_day_source", "source", "day"),
    )

    fact_wb_search_query_text_day_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    frequency_current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    week_frequency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    orders_current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visibility_current: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    avg_position_current: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    open_card_current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    add_to_cart_current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="wb_search_texts_api",
        server_default="wb_search_texts_api",
    )
    raw_payload: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)


class FactStockSnapshot(Base, StatusMixin):
    __tablename__ = "fact_stock_snapshot"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "nm_id", name="uq_fact_stock_snapshot_date_nm_id"),
        Index("idx_fact_stock_snapshot_snapshot_nm", "snapshot_date", "nm_id"),
        Index("idx_fact_stock_snapshot_nm_snapshot", "nm_id", "snapshot_date"),
    )

    fact_stock_snapshot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wb_stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    mp_stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    stock_total_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    stock_total_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    sale_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    to_client_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    from_client_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    availability: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    warehouse_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    warehouse_type: Mapped[str | None] = mapped_column(String(64), nullable=True)


class FactStockWarehouseSnapshot(Base, TimestampMixin):
    __tablename__ = "fact_stock_warehouse_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date",
            "nm_id",
            "chrt_id",
            "warehouse_id",
            name="uq_fact_stock_warehouse_snapshot_natural_key",
        ),
        Index("idx_fact_stock_warehouse_snapshot_date_nm", "snapshot_date", "nm_id"),
        Index("idx_fact_stock_warehouse_snapshot_nm_warehouse", "nm_id", "warehouse_id"),
        Index("idx_fact_stock_warehouse_snapshot_warehouse", "warehouse_name", "snapshot_date"),
    )

    fact_stock_warehouse_snapshot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chrt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    warehouse_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    warehouse_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stock_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    in_way_to_client: Mapped[int | None] = mapped_column(Integer, nullable=True)
    in_way_from_client: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(128), nullable=False)


class FactLocalizationRegionDay(Base, StatusMixin):
    __tablename__ = "fact_localization_region_day"
    __table_args__ = (
        UniqueConstraint("period_start", "period_end", "nm_id", "region", name="uq_fact_localization_region_day_natural_key"),
        Index("idx_fact_localization_region_day_period_nm_region", "period_start", "period_end", "nm_id", "region"),
        Index("idx_fact_localization_region_day_region_period", "region", "period_start", "period_end"),
    )

    fact_localization_region_day_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)
    region: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    orders_total_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    orders_local_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    orders_nonlocal_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    orders_nonlocal_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    wb_stock_orders_local_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    wb_stock_orders_nonlocal_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    wb_stock_orders_nonlocal_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    mp_orders_local_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    mp_orders_nonlocal_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    mp_orders_nonlocal_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    sale_item_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    sale_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    wb_stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    mp_stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    delivery_time: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    delivery_time_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    local_orders_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    nonlocal_orders_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)


class FactEntryPointDay(Base, StatusMixin):
    __tablename__ = "fact_entry_point_day"
    __table_args__ = (
        UniqueConstraint("date", "nm_id", "section", "entry_point", name="uq_fact_entry_point_day_natural_key"),
        Index("idx_fact_entry_point_day_nm_date", "nm_id", "date"),
        Index("idx_fact_entry_point_day_section_entry", "section", "entry_point"),
    )

    fact_entry_point_day_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    section: Mapped[str] = mapped_column(String(255), nullable=False)
    entry_point: Mapped[str] = mapped_column(String(255), nullable=False)
    supplier_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    impressions: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    card_clicks: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cart_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    add_to_cart_conversion: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    order_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    order_conversion: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    metric_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metric_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    orders_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    source_file_name: Mapped[str | None] = mapped_column(Text, nullable=True)


class FactVbroManual(Base, StatusMixin):
    __tablename__ = "fact_vbro_manual"
    __table_args__ = (
        UniqueConstraint("date", "nm_id", name="uq_fact_vbro_manual_date_nm_id"),
        Index("idx_fact_vbro_manual_date_nm", "date", "nm_id"),
        Index("idx_fact_vbro_manual_nm_date", "nm_id", "date"),
    )

    fact_vbro_manual_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    organic_sales_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    net_sales_payout: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ad_spend: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    logistics: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    storage: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    penalties: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    deductions: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    acceptance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    operating_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    operating_profit_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    manual_file_name: Mapped[str | None] = mapped_column(Text, nullable=True)


class FactIvanAdsWideDay(Base, StatusMixin):
    __tablename__ = "fact_ivan_ads_wide_day"
    __table_args__ = (
        UniqueConstraint("date", "nm_id", "campaign_ref", name="uq_fact_ivan_ads_wide_day_date_nm_campaign"),
        Index("idx_fact_ivan_ads_wide_day_date_nm", "date", "nm_id"),
        Index("idx_fact_ivan_ads_wide_day_campaign", "campaign_ref", "date"),
        Index("idx_fact_ivan_ads_wide_day_status", "source_status"),
    )

    fact_ivan_ads_wide_day_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    campaign_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    campaign_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    ad_spend: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ad_atbs: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_cart_ctr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cost_per_cart: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_views: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_cpm: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    source_file_name: Mapped[str | None] = mapped_column(Text, nullable=True)


class FactCardComparisonMetric(Base, StatusMixin):
    __tablename__ = "fact_card_comparison_metric"
    __table_args__ = (
        UniqueConstraint(
            "period_start",
            "period_end",
            "base_nm_id",
            "compared_nm_id",
            "metric_name",
            name="uq_fact_card_comparison_metric_natural_key",
        ),
        Index("idx_fact_card_comparison_metric_base_period", "base_nm_id", "period_start", "period_end"),
        Index("idx_fact_card_comparison_metric_metric_name", "metric_name"),
    )

    fact_card_comparison_metric_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    base_nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    compared_nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    metric_text_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    rank_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_system: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AppJobRun(Base):
    __tablename__ = "app_job_runs"
    __table_args__ = (
        UniqueConstraint("job_name", "run_date", name="uq_app_job_runs_job_name_run_date"),
        Index("idx_app_job_runs_job_date", "job_name", "run_date"),
        Index("idx_app_job_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(128), nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class FactWbSitePriceSnapshot(Base):
    __tablename__ = "fact_wb_site_price_snapshot"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "nm_id", name="uq_fact_wb_site_price_snapshot_date_nm_id"),
        Index("idx_fact_wb_site_price_snapshot_date_nm", "snapshot_date", "nm_id"),
        Index("idx_fact_wb_site_price_snapshot_fetch_status", "fetch_status", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    item_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lifecycle_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    product_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    buyer_visible_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    price_text_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    availability_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fetch_status: Mapped[str] = mapped_column(String(64), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    proxy_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_payload: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FactWbSitePriceAlert(Base):
    __tablename__ = "fact_wb_site_price_alert"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "nm_id", name="uq_fact_wb_site_price_alert_date_nm_id"),
        Index("idx_fact_wb_site_price_alert_date_nm", "snapshot_date", "nm_id"),
        Index("idx_fact_wb_site_price_alert_status", "alert_status", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    previous_success_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    price_delta: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    alert_status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MartTotalReport(Base, StatusMixin):
    __tablename__ = "mart_total_report"
    __table_args__ = (
        UniqueConstraint("report_date", "nm_id", name="uq_mart_total_report_natural_key"),
        Index("idx_mart_total_report_date_nm", "report_date", "nm_id"),
        Index("idx_mart_total_report_nm_date", "nm_id", "report_date"),
        Index("idx_mart_total_report_supplier_article", "supplier_article"),
    )

    mart_total_report_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    nm_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supplier_article: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    impressions: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    card_clicks: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ctr: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cart_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    order_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    order_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    buyout_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    buyout_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    buyout_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    add_to_cart_conversion: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cart_to_order_conversion: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    add_to_wishlist_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    avg_delivery_time: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    local_orders_percent: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    current_stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    current_stock_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    stock_snapshot_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    entry_impressions_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    entry_card_clicks_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    entry_cart_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    entry_orders_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    entry_ctr_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    entry_cart_conversion_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    entry_order_conversion_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cost_spend: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ad_views: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_clicks: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_atbs: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_orders: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_revenue: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ad_spend: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ad_cost_writeoff_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ad_campaign_spend_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ad_spend_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    ad_views_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_clicks_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_atbs_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_orders_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ad_avg_position: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    direct_ad_atbs: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    associated_ad_atbs: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    multicard_ad_atbs: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    unknown_ad_atbs: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    search_queries_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    search_avg_position: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    search_visibility: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    search_clicks: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    search_cart: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    search_orders: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    localization_regions_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    localization_orders_total_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    localization_sale_item_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    localization_sale_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    current_mp_stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ctr_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    add_to_cart_conversion_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    cart_to_order_conversion_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cpc_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cpm_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cost_per_cart_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cpo_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_share_of_revenue_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    associated_atbs_percent_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    organic_cart_count: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    organic_cart_share_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    ad_cost_per_all_carts_calc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    vbro_organic_sales_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    vbro_operating_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    has_funnel: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_stock: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_ad_cost: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_ad_campaign: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_search: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_localization: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_localization_partial: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_vbro: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_entry_points: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    has_card_comparison: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    manual_vbro_status: Mapped[str | None] = mapped_column(String(128), nullable=True)
    entry_point_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    orders_geography_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vbro_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    card_comparison_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    organic_cart_share_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    export_context_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
