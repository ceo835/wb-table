from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import logging
from typing import Any, Iterable, Iterator, Protocol

from sqlalchemy import and_, case, distinct, func, select, text
from sqlalchemy.engine import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.models import DimProduct, FactWbSitePriceAlert, FactWbSitePriceSnapshot, MartTotalReport, SettingsProducts
from src.mcp_server.schemas import (
    ActiveProductsItemResponse,
    ActiveProductsRequest,
    ActiveProductsResponse,
    DashboardSummaryRequest,
    DashboardSummaryResponse,
    DataQualityResponse,
    DbHealthResponse,
    MartSchemaColumnResponse,
    MartSchemaResponse,
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
from src.mcp_server.settings import McpServiceSettings
from src.tracked_products import load_tracked_products


ACTIVE_ALERT_STATUS = "PRICE_CHANGED_50"
SUPPRESSED_ALERT_PREFIX = "MANUAL_SUPPRESSED_"
logger = logging.getLogger(__name__)
MART_TABLE_NAME = "mart_total_report"
SETTINGS_PRODUCTS_TABLE_NAME = "settings_products"
DIM_PRODUCT_TABLE_NAME = "dim_product"
PRICE_SNAPSHOT_TABLE_NAME = "fact_wb_site_price_snapshot"
PRICE_ALERT_TABLE_NAME = "fact_wb_site_price_alert"
CORE_SCOPE = "core"
ALL_TRACKED_SCOPE = "all_tracked"
PRICE_MONITOR_SCOPE = "price_monitor"
SUPPORTED_PRODUCT_SCOPES = {CORE_SCOPE, ALL_TRACKED_SCOPE, PRICE_MONITOR_SCOPE}

MART_REQUIRED_ALIASES: dict[str, tuple[str, ...]] = {
    "report_date": ("report_date", "date"),
    "nm_id": ("nm_id",),
    "supplier_article": ("supplier_article",),
    "title": ("title", "product_name", "item_label"),
    "card_clicks": ("card_clicks",),
    "cart_count": ("cart_count", "cartCount"),
    "order_count": ("order_count", "orderCount"),
    "order_sum": ("order_sum", "orderSum"),
    "ctr": ("ctr", "ctr_calc"),
    "add_to_cart_conversion": ("add_to_cart_conversion", "addToCartConversion", "add_to_cart_conversion_calc"),
    "cart_to_order_conversion": ("cart_to_order_conversion", "cartToOrderConversion", "cart_to_order_conversion_calc"),
    "ad_spend": ("ad_campaign_spend_total", "ad_spend_total", "ad_spend"),
    "ad_atbs": ("ad_atbs_total", "ad_atbs"),
    "ad_orders": ("ad_orders_total", "ad_orders"),
    "ad_campaign_spend_total": ("ad_campaign_spend_total", "ad_spend_total", "ad_spend"),
    "ad_clicks_total": ("ad_clicks_total", "ad_clicks"),
    "ad_atbs_total": ("ad_atbs_total", "ad_atbs"),
    "ad_orders_total": ("ad_orders_total", "ad_orders"),
    "current_stock_qty": ("current_stock_qty",),
    "data_status": ("data_status",),
    "source_status": ("source_status",),
}

PRICE_SNAPSHOT_ALIASES: dict[str, tuple[str, ...]] = {
    "snapshot_date": ("snapshot_date",),
    "snapshot_at": ("snapshot_at", "created_at"),
    "nm_id": ("nm_id",),
    "item_label": ("item_label", "title"),
    "product_url": ("product_url",),
    "buyer_visible_price": ("buyer_visible_price",),
    "fetch_status": ("fetch_status",),
}

PRICE_ALERT_ALIASES: dict[str, tuple[str, ...]] = {
    "snapshot_date": ("snapshot_date",),
    "nm_id": ("nm_id",),
    "current_price": ("current_price",),
    "previous_success_price": ("previous_success_price",),
    "price_delta": ("price_delta",),
    "alert_status": ("alert_status",),
}

PRODUCT_LOOKUP_ALIASES: dict[str, tuple[str, ...]] = {
    "nm_id": ("nm_id",),
    "supplier_article": ("supplier_article",),
    "title": ("title", "item_label", "product_name"),
}

ACTIVE_PRODUCTS_SETTINGS_ALIASES: dict[str, tuple[str, ...]] = {
    "nm_id": ("nm_id",),
    "supplier_article": ("supplier_article",),
    "title": ("title",),
    "brand": ("brand",),
    "subject": ("subject",),
    "active": ("active",),
    "analytics_active": ("analytics_active",),
}

ACTIVE_PRODUCTS_DIM_ALIASES: dict[str, tuple[str, ...]] = {
    "nm_id": ("nm_id",),
    "supplier_article": ("supplier_article",),
    "title": ("title",),
    "brand": ("brand",),
    "subject": ("subject",),
    "category": ("category",),
}


class McpRepository(Protocol):
    def get_db_health(self) -> DbHealthResponse: ...
    def get_mart_schema(self) -> MartSchemaResponse: ...
    def get_dashboard_summary(self, payload: DashboardSummaryRequest) -> DashboardSummaryResponse: ...
    def get_product_metrics(self, payload: ProductMetricsRequest) -> ProductMetricsResponse: ...
    def get_price_monitor(self, payload: PriceMonitorRequest) -> PriceMonitorResponse: ...
    def get_active_products(self, payload: ActiveProductsRequest) -> ActiveProductsResponse: ...


def _safe_divide(numerator: Decimal | None, denominator: Decimal | None, multiplier: Decimal | None = None) -> Decimal | None:
    if numerator is None or denominator in (None, Decimal("0")):
        return None
    result = numerator / denominator
    if multiplier is not None:
        result *= multiplier
    return result


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _normalize_dt(value: datetime | None) -> datetime:
    return value or datetime.min


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    getter = getattr(row, key, None)
    if getter is not None:
        return getter
    if hasattr(row, "_mapping"):
        return row._mapping.get(key)
    return None


def _coverage_status(values: list[Any]) -> str:
    if not values:
        return "missing"
    non_null = sum(value is not None for value in values)
    if non_null == 0:
        return "missing"
    if non_null == len(values):
        return "full"
    return "partial"


def validate_date_window(
    start: date,
    end: date,
    *,
    max_days: int,
) -> None:
    if end < start:
        raise ValueError("date_to must be greater than or equal to date_from.")
    if (end - start).days + 1 > max_days:
        raise ValueError(f"Date range must not exceed {max_days} days.")


def normalize_product_scope(
    scope: str | None,
    *,
    only_tracked: bool = True,
    scope_was_explicit: bool = True,
) -> str | None:
    normalized = (scope or "").strip().lower() or None
    if normalized is not None and normalized not in SUPPORTED_PRODUCT_SCOPES:
        raise ValueError(
            "scope must be one of: core, all_tracked, price_monitor."
        )
    if not scope_was_explicit and not only_tracked:
        return None
    return normalized or CORE_SCOPE


def resolve_column_aliases(
    available_columns: set[str],
    alias_map: dict[str, tuple[str, ...]],
) -> tuple[dict[str, str], list[str]]:
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for logical_name, aliases in alias_map.items():
        selected = next((alias for alias in aliases if alias in available_columns), None)
        if selected is None:
            missing.append(logical_name)
        else:
            resolved[logical_name] = selected
    return resolved, missing


def _quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _select_expr(resolved: dict[str, str], logical_name: str, *, cast_type: str = "TEXT", table_alias: str = "m") -> str:
    actual_name = resolved.get(logical_name)
    if actual_name is None:
        return f"CAST(NULL AS {cast_type}) AS {_quote_ident(logical_name)}"
    return f"{table_alias}.{_quote_ident(actual_name)} AS {_quote_ident(logical_name)}"


def _sum_expr(resolved: dict[str, str], logical_name: str, *, table_alias: str = "m") -> str:
    actual_name = resolved.get(logical_name)
    if actual_name is None:
        return f"CAST(NULL AS NUMERIC) AS {_quote_ident(logical_name)}"
    return f"SUM({table_alias}.{_quote_ident(actual_name)}) AS {_quote_ident(logical_name)}"


def build_dashboard_summary_response(
    payload: DashboardSummaryRequest,
    aggregate_row: Any,
    partial_rows: int,
    empty_rows: int,
    notes: list[str],
) -> DashboardSummaryResponse:
    card_clicks = _as_decimal(_row_value(aggregate_row, "card_clicks"))
    cart_count = _as_decimal(_row_value(aggregate_row, "cart_count"))
    order_count = _as_decimal(_row_value(aggregate_row, "order_count"))
    order_sum = _as_decimal(_row_value(aggregate_row, "order_sum"))
    ad_spend = _as_decimal(_row_value(aggregate_row, "ad_spend"))
    ad_atbs = _as_decimal(_row_value(aggregate_row, "ad_atbs"))
    ad_orders = _as_decimal(_row_value(aggregate_row, "ad_orders"))
    return DashboardSummaryResponse(
        date_from=payload.date_from,
        date_to=payload.date_to,
        rows=int(_row_value(aggregate_row, "rows") or 0),
        nm_count=int(_row_value(aggregate_row, "nm_count") or 0),
        card_clicks=card_clicks,
        cart_count=cart_count,
        order_count=order_count,
        order_sum=order_sum,
        ad_spend=ad_spend,
        ad_atbs=ad_atbs,
        ad_orders=ad_orders,
        cpo_total=_safe_divide(ad_spend, order_count),
        cpo_ad=_safe_divide(ad_spend, ad_orders),
        cost_per_cart_total=_safe_divide(ad_spend, cart_count),
        cost_per_cart_ad=_safe_divide(ad_spend, ad_atbs),
        drr=_safe_divide(ad_spend, order_sum, Decimal("100")),
        data_quality=DataQualityResponse(
            partial_rows=partial_rows,
            empty_rows=empty_rows,
            notes=notes,
        ),
    )


def build_product_metrics_response(
    payload: ProductMetricsRequest,
    mart_rows: list[dict[str, Any]],
    price_rows: list[dict[str, Any]],
) -> ProductMetricsResponse:
    price_by_date = {
        (row["snapshot_date"], int(row["nm_id"])): _as_decimal(row.get("buyer_visible_price"))
        for row in price_rows
    }
    if not mart_rows:
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
            period_meta=ProductPeriodMetaResponse(
                rows_count=0,
                days_requested=(payload.date_to - payload.date_from).days + 1,
                days_returned=0,
            ),
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
                "ad_metrics": "missing_metric_not_zero",
                "current_stock_qty": "missing_snapshot_not_zero",
            },
            analysis_status="NO_DATA",
            allowed_inferences=[],
            forbidden_inferences=[
                "price_cause",
                "stock_cause",
                "ad_cause",
                "promo_cause",
                "delivery_cause",
            ],
            analysis_limits=[
                "По выбранному nm_id и периоду строки в mart_total_report не найдены.",
                "Причину просадки или роста по цене, остаткам, рекламе и доставке утверждать нельзя.",
            ],
        )

    daily: list[ProductDailyMetricsResponse] = []
    card_clicks_total = Decimal("0")
    cart_total = Decimal("0")
    order_total = Decimal("0")
    order_sum_total = Decimal("0")
    ad_spend_total = Decimal("0")
    ctr_values: list[Decimal] = []
    atc_values: list[Decimal] = []
    cto_values: list[Decimal] = []
    order_sum_missing_for_dates: list[date] = []
    ad_presence_markers: list[bool] = []
    stock_presence_markers: list[bool] = []
    price_presence_markers: list[bool] = []
    has_cart = False
    has_card_clicks = False
    has_orders = False
    has_order_sum = False
    has_ad_spend = False

    for row in mart_rows:
        report_date = row["report_date"]
        card_clicks = _as_decimal(row.get("card_clicks"))
        ctr = _as_decimal(row.get("ctr"))
        cart_count = _as_decimal(row.get("cart_count"))
        add_to_cart_conversion = _as_decimal(row.get("add_to_cart_conversion"))
        order_count = _as_decimal(row.get("order_count"))
        cart_to_order_conversion = _as_decimal(row.get("cart_to_order_conversion"))
        order_sum = _as_decimal(row.get("order_sum"))
        ad_spend = _as_decimal(row.get("ad_campaign_spend_total"))
        ad_clicks = _as_decimal(row.get("ad_clicks_total"))
        ad_atbs = _as_decimal(row.get("ad_atbs_total"))
        ad_orders = _as_decimal(row.get("ad_orders_total"))
        current_stock_qty = _as_decimal(row.get("current_stock_qty"))
        wb_buyer_price = price_by_date.get((report_date, payload.nm_id))

        if card_clicks is not None:
            card_clicks_total += card_clicks
            has_card_clicks = True
        if ctr is not None:
            ctr_values.append(ctr)
        if cart_count is not None:
            cart_total += cart_count
            has_cart = True
        if add_to_cart_conversion is not None:
            atc_values.append(add_to_cart_conversion)
        if order_count is not None:
            order_total += order_count
            has_orders = True
        if cart_to_order_conversion is not None:
            cto_values.append(cart_to_order_conversion)
        if order_sum is not None:
            order_sum_total += order_sum
            has_order_sum = True
        else:
            order_sum_missing_for_dates.append(report_date)
        if ad_spend is not None:
            ad_spend_total += ad_spend
            has_ad_spend = True
        ad_presence_markers.append(any(value is not None for value in (ad_spend, ad_clicks, ad_atbs, ad_orders)))
        stock_presence_markers.append(current_stock_qty is not None)
        price_presence_markers.append(wb_buyer_price is not None)

        daily.append(
            ProductDailyMetricsResponse(
                date=report_date,
                card_clicks=card_clicks,
                ctr=ctr,
                cart_count=cart_count,
                add_to_cart_conversion=add_to_cart_conversion,
                order_count=order_count,
                cart_to_order_conversion=cart_to_order_conversion,
                order_sum=order_sum,
                ad_spend=ad_spend,
                ad_clicks=ad_clicks,
                ad_atbs=ad_atbs,
                ad_orders=ad_orders,
                current_stock_qty=current_stock_qty,
                wb_buyer_price=wb_buyer_price,
            )
        )

    first_row = mart_rows[0]
    avg_ctr = (sum(ctr_values, Decimal("0")) / len(ctr_values)) if ctr_values else None
    avg_atc = (sum(atc_values, Decimal("0")) / len(atc_values)) if atc_values else None
    avg_cto = (sum(cto_values, Decimal("0")) / len(cto_values)) if cto_values else None
    order_sum_available_dates_count = len(daily) - len(order_sum_missing_for_dates)
    source_coverage = {
        "funnel": "full",
        "price_monitor": _coverage_status(price_presence_markers),
        "ad_metrics": _coverage_status(ad_presence_markers),
        "stock_by_size": _coverage_status(stock_presence_markers),
        "delivery_time": "missing",
    }
    wb_buyer_price_missing = source_coverage["price_monitor"] == "missing"
    ad_metrics_missing = source_coverage["ad_metrics"] == "missing"
    stock_by_size_missing = source_coverage["stock_by_size"] == "missing"
    delivery_time_missing = True
    forbidden_inferences = ["promo_cause"]
    if wb_buyer_price_missing:
        forbidden_inferences.append("price_cause")
    if stock_by_size_missing:
        forbidden_inferences.append("stock_cause")
    if ad_metrics_missing:
        forbidden_inferences.append("ad_cause")
    if delivery_time_missing:
        forbidden_inferences.append("delivery_cause")
    analysis_limits = [
        "Можно анализировать изменение переходов, корзин, заказов и конверсий.",
        "Если поле отсутствует или равно null, это означает нет данных, а не ноль.",
        "Нельзя утверждать причину в цене, остатках, рекламе, промо или доставке без соответствующих полей.",
    ]
    if order_sum_missing_for_dates:
        analysis_limits.append("Если order_sum заполнен частично, выручку анализировать осторожно.")
    if wb_buyer_price_missing:
        analysis_limits.append("Для проверки гипотезы о цене нужен wb_buyer_price по дням.")
    if stock_by_size_missing:
        analysis_limits.append("Для проверки гипотезы об остатках нужны подтверждённые stock-поля по дням.")
    if ad_metrics_missing:
        analysis_limits.append("Для проверки гипотезы о рекламе нужны ad-метрики по дням.")
    analysis_status = (
        "LIMITED"
        if (
            order_sum_missing_for_dates
            or wb_buyer_price_missing
            or ad_metrics_missing
            or stock_by_size_missing
            or delivery_time_missing
        )
        else "OK"
    )
    return ProductMetricsResponse(
        found=True,
        nm_id=payload.nm_id,
        supplier_article=first_row.get("supplier_article"),
        product_name=first_row.get("title"),
        date_from=payload.date_from,
        date_to=payload.date_to,
        daily=daily,
        summary=ProductSummaryResponse(
            card_clicks_total=card_clicks_total if has_card_clicks else None,
            cart_count=cart_total if has_cart else None,
            order_count=order_total if has_orders else None,
            order_sum=order_sum_total if has_order_sum else None,
            ad_spend=ad_spend_total if has_ad_spend else None,
            avg_ctr=avg_ctr,
            avg_add_to_cart_conversion=avg_atc,
            avg_cart_to_order_conversion=avg_cto,
            order_sum_available_dates_count=order_sum_available_dates_count,
            order_sum_missing_dates_count=len(order_sum_missing_for_dates),
        ),
        period_meta=ProductPeriodMetaResponse(
            rows_count=len(daily),
            days_requested=(payload.date_to - payload.date_from).days + 1,
            days_returned=len(daily),
        ),
        source_coverage=source_coverage,
        data_quality=ProductDataQualityResponse(
            order_sum_available_dates_count=order_sum_available_dates_count,
            order_sum_missing_dates_count=len(order_sum_missing_for_dates),
            order_sum_missing_for_dates=order_sum_missing_for_dates,
            wb_buyer_price_missing=wb_buyer_price_missing,
            ad_metrics_missing=ad_metrics_missing,
            stock_by_size_missing=stock_by_size_missing,
            delivery_time_missing=delivery_time_missing,
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
        analysis_status=analysis_status,
        allowed_inferences=[
            "funnel_trend",
            "conversion_change",
            "day_to_day_trend",
        ],
        forbidden_inferences=forbidden_inferences,
        analysis_limits=analysis_limits,
    )


def build_price_monitor_response(
    payload: PriceMonitorRequest,
    snapshot_rows: list[dict[str, Any]],
    alert_rows: list[dict[str, Any]],
) -> PriceMonitorResponse:
    selected_date = payload.snapshot_date
    current_rows = [row for row in snapshot_rows if row["snapshot_date"] == selected_date]
    current_rows.sort(key=lambda row: (str(row.get("supplier_article") or ""), int(row["nm_id"])))

    previous_success_by_nm: dict[int, Decimal] = {}
    normalized_rows = sorted(
        snapshot_rows,
        key=lambda row: (int(row["nm_id"]), row["snapshot_date"], _normalize_dt(row.get("snapshot_at"))),
    )
    for row in normalized_rows:
        if row["snapshot_date"] >= selected_date:
            continue
        price = _as_decimal(row.get("buyer_visible_price"))
        if row.get("fetch_status") == "success" and price is not None:
            previous_success_by_nm[int(row["nm_id"])] = price

    active_alerts: dict[tuple[date, int], dict[str, Any]] = {}
    for alert_row in alert_rows:
        if alert_row["snapshot_date"] != selected_date:
            continue
        status = str(alert_row.get("alert_status") or "")
        if status != ACTIVE_ALERT_STATUS:
            continue
        active_alerts[(selected_date, int(alert_row["nm_id"]))] = alert_row

    items: list[PriceMonitorItemResponse] = []
    for row in current_rows:
        nm_id = int(row["nm_id"])
        current_price = _as_decimal(row.get("buyer_visible_price"))
        previous_price = previous_success_by_nm.get(nm_id)
        active_alert = active_alerts.get((selected_date, nm_id))
        price_delta = _as_decimal(active_alert.get("price_delta")) if active_alert else None
        if price_delta is None and current_price is not None and previous_price is not None:
            price_delta = current_price - previous_price
        items.append(
            PriceMonitorItemResponse(
                nm_id=nm_id,
                supplier_article=row.get("supplier_article"),
                product_name=row.get("product_name") or row.get("item_label"),
                snapshot_date=selected_date,
                buyer_visible_price=current_price,
                previous_price=_as_decimal(active_alert.get("previous_success_price")) if active_alert else previous_price,
                price_delta=price_delta,
                is_alert=active_alert is not None,
                alert_reason=str(active_alert.get("alert_status")) if active_alert else None,
                fetch_status=str(row.get("fetch_status") or ""),
                product_url=row.get("product_url"),
            )
        )

    if payload.alerts_only:
        items = [item for item in items if item.is_alert]

    return PriceMonitorResponse(
        snapshot_date=selected_date,
        rows=len(current_rows),
        alerts=len([item for item in items if item.is_alert]),
        items=items,
    )


@dataclass
class PostgresMcpRepository:
    settings: McpServiceSettings

    def __post_init__(self) -> None:
        self.engine: Engine = create_engine(
            self.settings.database_url,
            future=True,
            pool_pre_ping=True,
        )
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        self.timeout_ms = max(1000, int(self.settings.query_timeout_seconds * 1000))
        self._table_schema_cache: dict[str, list[tuple[str, str]]] = {}

    @contextmanager
    def readonly_session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text(f"SET LOCAL statement_timeout = {self.timeout_ms}"))
            yield session
            session.rollback()
        except Exception:
            logger.exception("MCP repository DB session failed")
            session.rollback()
            raise
        finally:
            session.close()

    def _load_table_schema(self, session: Session, table_name: str) -> list[tuple[str, str]]:
        cached = self._table_schema_cache.get(table_name)
        if cached is not None:
            return cached
        stmt = text(
            """
            select column_name, data_type
            from information_schema.columns
            where table_schema = current_schema()
              and table_name = :table_name
            order by ordinal_position
            """
        )
        rows = session.execute(stmt, {"table_name": table_name}).mappings().all()
        schema = [(str(row["column_name"]), str(row["data_type"])) for row in rows]
        self._table_schema_cache[table_name] = schema
        return schema

    def _get_table_columns(self, session: Session, table_name: str) -> set[str]:
        return {column_name for column_name, _ in self._load_table_schema(session, table_name)}

    def _resolve_table_aliases(
        self,
        session: Session,
        table_name: str,
        alias_map: dict[str, tuple[str, ...]],
    ) -> tuple[dict[str, str], list[str]]:
        return resolve_column_aliases(self._get_table_columns(session, table_name), alias_map)

    def _apply_tracked_filter(self, stmt, only_tracked: bool):
        if not only_tracked:
            return stmt
        return stmt.join(
            SettingsProducts,
            and_(
                SettingsProducts.nm_id == MartTotalReport.nm_id,
                SettingsProducts.active.is_(True),
            ),
        )

    def _load_price_monitor_metadata(self) -> dict[int, dict[str, Any]]:
        tracked_df = load_tracked_products()
        if tracked_df.empty or "nm_id" not in tracked_df.columns:
            return {}
        if "is_tracked" in tracked_df.columns:
            tracked_df = tracked_df.loc[tracked_df["is_tracked"]].copy()
        result: dict[int, dict[str, Any]] = {}
        for _, row in tracked_df.iterrows():
            try:
                nm_id = int(row["nm_id"])
            except (TypeError, ValueError):
                continue
            result[nm_id] = {
                "tracked_label": row.get("tracked_label") or row.get("item_label") or None,
                "lifecycle_status": row.get("lifecycle_status") or None,
                "source": row.get("source") or None,
            }
        return result

    def _load_scope_nm_ids(
        self,
        session: Session,
        scope_name: str | None,
    ) -> tuple[list[int] | None, bool]:
        if scope_name is None:
            return None, False

        price_monitor_metadata = self._load_price_monitor_metadata()
        price_monitor_nm_ids = set(price_monitor_metadata.keys())

        if scope_name == PRICE_MONITOR_SCOPE:
            return sorted(price_monitor_nm_ids), False

        settings_active_nm_ids = set(
            int(nm_id)
            for nm_id in session.execute(
                select(SettingsProducts.nm_id).where(SettingsProducts.active.is_(True))
            ).scalars()
            if nm_id is not None
        )
        if scope_name == ALL_TRACKED_SCOPE:
            return sorted(settings_active_nm_ids | price_monitor_nm_ids), False

        analytics_active_available = "analytics_active" in self._get_table_columns(session, SETTINGS_PRODUCTS_TABLE_NAME)
        if analytics_active_available:
            analytics_active_nm_ids = set(
                int(nm_id)
                for nm_id in session.execute(
                    select(SettingsProducts.nm_id).where(SettingsProducts.analytics_active.is_(True))
                ).scalars()
                if nm_id is not None
            )
            if analytics_active_nm_ids:
                return sorted(analytics_active_nm_ids), False

        return sorted(price_monitor_nm_ids), True

    def get_db_health(self) -> DbHealthResponse:
        with self.readonly_session() as session:
            stmt = select(
                func.count().label("rows"),
                func.min(MartTotalReport.report_date).label("min_date"),
                func.max(MartTotalReport.report_date).label("max_date"),
            )
            row = session.execute(stmt).one()

        return DbHealthResponse(
            ok=True,
            rows=int(row.rows or 0),
            min_date=row.min_date,
            max_date=row.max_date,
        )

    def get_mart_schema(self) -> MartSchemaResponse:
        with self.readonly_session() as session:
            schema = self._load_table_schema(session, MART_TABLE_NAME)
        return MartSchemaResponse(
            table_name=MART_TABLE_NAME,
            columns=[
                MartSchemaColumnResponse(column_name=column_name, data_type=data_type)
                for column_name, data_type in schema
            ],
        )

    def get_dashboard_summary(self, payload: DashboardSummaryRequest) -> DashboardSummaryResponse:
        validate_date_window(payload.date_from, payload.date_to, max_days=self.settings.max_date_range_days)
        with self.readonly_session() as session:
            resolved, missing = self._resolve_table_aliases(session, MART_TABLE_NAME, MART_REQUIRED_ALIASES)
            date_column = resolved.get("report_date")
            nm_id_column = resolved.get("nm_id")
            if date_column is None or nm_id_column is None:
                missing_keys = ", ".join(sorted({"report_date", "nm_id"} - resolved.keys()))
                raise ValueError(f"mart_total_report schema is missing required columns: {missing_keys}")

            join_sql = ""
            notes: list[str] = []
            scope_name = normalize_product_scope(
                payload.scope,
                only_tracked=payload.only_tracked,
                scope_was_explicit="scope" in payload.model_fields_set,
            )
            scope_nm_ids, scope_used_price_monitor_fallback = self._load_scope_nm_ids(session, scope_name)
            if scope_name is not None:
                notes.append(f"Product scope applied: {scope_name}.")
                if scope_used_price_monitor_fallback and scope_name == CORE_SCOPE:
                    notes.append("Core scope fallback used tracked price-monitor list because analytics_active is not seeded yet.")
            elif payload.only_tracked:
                settings_columns = self._get_table_columns(session, SETTINGS_PRODUCTS_TABLE_NAME)
                if {"nm_id", "active"}.issubset(settings_columns):
                    join_sql = (
                        f" join {SETTINGS_PRODUCTS_TABLE_NAME} sp"
                        f" on sp.{_quote_ident('nm_id')} = m.{_quote_ident(nm_id_column)}"
                        f" and sp.{_quote_ident('active')} = true"
                    )
                    notes.append("Tracked scope filtered via settings_products.active = true.")
                elif "nm_id" in settings_columns:
                    join_sql = (
                        f" join {SETTINGS_PRODUCTS_TABLE_NAME} sp"
                        f" on sp.{_quote_ident('nm_id')} = m.{_quote_ident(nm_id_column)}"
                    )
                    notes.append("Tracked scope filtered via settings_products.nm_id without active flag.")
                else:
                    notes.append("Tracked filter not applied: settings_products schema is incomplete.")

            scope_where_sql = ""
            params: dict[str, Any] = {"date_from": payload.date_from, "date_to": payload.date_to}
            if scope_nm_ids is not None:
                if not scope_nm_ids:
                    return build_dashboard_summary_response(
                        payload=payload,
                        aggregate_row={
                            "rows": 0,
                            "nm_count": 0,
                            "card_clicks": None,
                            "cart_count": None,
                            "order_count": None,
                            "order_sum": None,
                            "ad_spend": None,
                            "ad_atbs": None,
                            "ad_orders": None,
                        },
                        partial_rows=0,
                        empty_rows=0,
                        notes=notes,
                    )
                scope_where_sql = f" and m.{_quote_ident(nm_id_column)} = any(:scope_nm_ids)"
                params["scope_nm_ids"] = scope_nm_ids

            aggregate_sql = f"""
                select
                    count(*) as rows,
                    count(distinct m.{_quote_ident(nm_id_column)}) as nm_count,
                    {_sum_expr(resolved, "card_clicks")},
                    {_sum_expr(resolved, "cart_count")},
                    {_sum_expr(resolved, "order_count")},
                    {_sum_expr(resolved, "order_sum")},
                    {_sum_expr(resolved, "ad_spend")},
                    {_sum_expr(resolved, "ad_atbs")},
                    {_sum_expr(resolved, "ad_orders")}
                from {MART_TABLE_NAME} m
                {join_sql}
                where m.{_quote_ident(date_column)} >= :date_from
                  and m.{_quote_ident(date_column)} <= :date_to
                  {scope_where_sql}
            """
            aggregate_row = session.execute(
                text(aggregate_sql),
                params,
            ).mappings().one()

            data_status_column = resolved.get("data_status")
            if data_status_column is not None:
                status_sql = f"""
                    select
                        sum(case when m.{_quote_ident(data_status_column)} ilike '%PARTIAL%' then 1 else 0 end) as partial_rows,
                        sum(case when m.{_quote_ident(data_status_column)} = 'NO_DATA' then 1 else 0 end) as empty_rows
                    from {MART_TABLE_NAME} m
                    {join_sql}
                    where m.{_quote_ident(date_column)} >= :date_from
                      and m.{_quote_ident(date_column)} <= :date_to
                      {scope_where_sql}
                """
                status_row = session.execute(
                    text(status_sql),
                    params,
                ).mappings().one()
            else:
                status_row = {"partial_rows": 0, "empty_rows": 0}
                notes.append("data_status column is not available in mart_total_report.")

        if missing:
            notes.append("Missing mart columns: " + ", ".join(sorted(missing)))
        return build_dashboard_summary_response(
            payload=payload,
            aggregate_row=aggregate_row,
            partial_rows=int(status_row["partial_rows"] or 0),
            empty_rows=int(status_row["empty_rows"] or 0),
            notes=notes,
        )

    def get_product_metrics(self, payload: ProductMetricsRequest) -> ProductMetricsResponse:
        validate_date_window(payload.date_from, payload.date_to, max_days=self.settings.max_date_range_days)
        with self.readonly_session() as session:
            scope_name = normalize_product_scope(payload.scope)
            scope_nm_ids, _ = self._load_scope_nm_ids(session, scope_name)
            if scope_nm_ids is not None and int(payload.nm_id) not in set(scope_nm_ids):
                return build_product_metrics_response(payload, [], [])

            mart_resolved, _missing = self._resolve_table_aliases(session, MART_TABLE_NAME, MART_REQUIRED_ALIASES)
            date_column = mart_resolved.get("report_date")
            nm_id_column = mart_resolved.get("nm_id")
            if date_column is None or nm_id_column is None:
                missing_keys = ", ".join(sorted({"report_date", "nm_id"} - mart_resolved.keys()))
                raise ValueError(f"mart_total_report schema is missing required columns: {missing_keys}")

            mart_sql = f"""
                select
                    {_select_expr(mart_resolved, "report_date", cast_type="DATE")},
                    {_select_expr(mart_resolved, "supplier_article")},
                    {_select_expr(mart_resolved, "title")},
                    {_select_expr(mart_resolved, "card_clicks", cast_type="NUMERIC")},
                    {_select_expr(mart_resolved, "cart_count", cast_type="NUMERIC")},
                    {_select_expr(mart_resolved, "order_count", cast_type="NUMERIC")},
                    {_select_expr(mart_resolved, "order_sum", cast_type="NUMERIC")},
                    {_select_expr(mart_resolved, "ctr", cast_type="NUMERIC")},
                    {_select_expr(mart_resolved, "add_to_cart_conversion", cast_type="NUMERIC")},
                    {_select_expr(mart_resolved, "cart_to_order_conversion", cast_type="NUMERIC")},
                    {_select_expr(mart_resolved, "ad_campaign_spend_total", cast_type="NUMERIC")},
                    {_select_expr(mart_resolved, "ad_clicks_total", cast_type="NUMERIC")},
                    {_select_expr(mart_resolved, "ad_atbs_total", cast_type="NUMERIC")},
                    {_select_expr(mart_resolved, "ad_orders_total", cast_type="NUMERIC")},
                    {_select_expr(mart_resolved, "current_stock_qty", cast_type="NUMERIC")}
                from {MART_TABLE_NAME} m
                where m.{_quote_ident(nm_id_column)} = :nm_id
                  and m.{_quote_ident(date_column)} >= :date_from
                  and m.{_quote_ident(date_column)} <= :date_to
                order by m.{_quote_ident(date_column)} asc
            """
            mart_rows = session.execute(
                text(mart_sql),
                {"nm_id": payload.nm_id, "date_from": payload.date_from, "date_to": payload.date_to},
            ).mappings().all()
            if len(mart_rows) > self.settings.max_rows:
                raise ValueError(f"Result exceeds MCP_MAX_ROWS={self.settings.max_rows}.")

            snapshot_resolved, _ = self._resolve_table_aliases(session, PRICE_SNAPSHOT_TABLE_NAME, PRICE_SNAPSHOT_ALIASES)
            snapshot_date_column = snapshot_resolved.get("snapshot_date")
            snapshot_nm_column = snapshot_resolved.get("nm_id")
            if snapshot_date_column is not None and snapshot_nm_column is not None:
                price_sql = f"""
                    select
                        {_select_expr(snapshot_resolved, "snapshot_date", cast_type="DATE", table_alias="p")},
                        {_select_expr(snapshot_resolved, "snapshot_at", cast_type="TIMESTAMP", table_alias="p")},
                        {_select_expr(snapshot_resolved, "nm_id", cast_type="BIGINT", table_alias="p")},
                        {_select_expr(snapshot_resolved, "buyer_visible_price", cast_type="NUMERIC", table_alias="p")}
                    from {PRICE_SNAPSHOT_TABLE_NAME} p
                    where p.{_quote_ident(snapshot_nm_column)} = :nm_id
                      and p.{_quote_ident(snapshot_date_column)} >= :date_from
                      and p.{_quote_ident(snapshot_date_column)} <= :date_to
                    order by p.{_quote_ident(snapshot_date_column)} asc
                """
                price_rows = session.execute(
                    text(price_sql),
                    {"nm_id": payload.nm_id, "date_from": payload.date_from, "date_to": payload.date_to},
                ).mappings().all()
            else:
                price_rows = []

        mart_payload_rows = [dict(row) for row in mart_rows]
        price_payload_rows = [dict(row) for row in price_rows]
        return build_product_metrics_response(payload, mart_payload_rows, price_payload_rows)

    def get_active_products(self, payload: ActiveProductsRequest) -> ActiveProductsResponse:
        scope_name = normalize_product_scope(payload.scope)
        with self.readonly_session() as session:
            scope_nm_ids, core_fallback_used = self._load_scope_nm_ids(session, scope_name)
            if not scope_nm_ids:
                return ActiveProductsResponse(scope=scope_name or CORE_SCOPE, rows=0, items=[])

            settings_resolved, _ = self._resolve_table_aliases(
                session,
                SETTINGS_PRODUCTS_TABLE_NAME,
                ACTIVE_PRODUCTS_SETTINGS_ALIASES,
            )
            settings_nm_column = settings_resolved.get("nm_id")
            if settings_nm_column is not None:
                settings_sql = f"""
                    select
                        {_select_expr(settings_resolved, "nm_id", cast_type="BIGINT", table_alias="s")},
                        {_select_expr(settings_resolved, "supplier_article", table_alias="s")},
                        {_select_expr(settings_resolved, "title", table_alias="s")},
                        {_select_expr(settings_resolved, "brand", table_alias="s")},
                        {_select_expr(settings_resolved, "subject", table_alias="s")},
                        {_select_expr(settings_resolved, "active", cast_type="BOOLEAN", table_alias="s")},
                        {_select_expr(settings_resolved, "analytics_active", cast_type="BOOLEAN", table_alias="s")}
                    from {SETTINGS_PRODUCTS_TABLE_NAME} s
                    where s.{_quote_ident(settings_nm_column)} = any(:nm_ids)
                    order by s.{_quote_ident(settings_nm_column)} asc
                """
                settings_rows = session.execute(text(settings_sql), {"nm_ids": scope_nm_ids}).mappings().all()
            else:
                settings_rows = []

            dim_resolved, _ = self._resolve_table_aliases(
                session,
                DIM_PRODUCT_TABLE_NAME,
                ACTIVE_PRODUCTS_DIM_ALIASES,
            )
            dim_nm_column = dim_resolved.get("nm_id")
            if dim_nm_column is not None:
                dim_sql = f"""
                    select
                        {_select_expr(dim_resolved, "nm_id", cast_type="BIGINT", table_alias="d")},
                        {_select_expr(dim_resolved, "supplier_article", table_alias="d")},
                        {_select_expr(dim_resolved, "title", table_alias="d")},
                        {_select_expr(dim_resolved, "brand", table_alias="d")},
                        {_select_expr(dim_resolved, "subject", table_alias="d")},
                        {_select_expr(dim_resolved, "category", table_alias="d")}
                    from {DIM_PRODUCT_TABLE_NAME} d
                    where d.{_quote_ident(dim_nm_column)} = any(:nm_ids)
                    order by d.{_quote_ident(dim_nm_column)} asc
                """
                dim_rows = session.execute(text(dim_sql), {"nm_ids": scope_nm_ids}).mappings().all()
            else:
                dim_rows = []

        settings_by_nm = {int(row["nm_id"]): dict(row) for row in settings_rows if row.get("nm_id") is not None}
        dim_by_nm = {int(row["nm_id"]): dict(row) for row in dim_rows if row.get("nm_id") is not None}
        price_monitor_metadata = self._load_price_monitor_metadata()

        items: list[ActiveProductsItemResponse] = []
        for nm_id in scope_nm_ids:
            settings_row = settings_by_nm.get(int(nm_id))
            dim_row = dim_by_nm.get(int(nm_id))
            tracked_meta = price_monitor_metadata.get(int(nm_id), {})
            analytics_active = bool(settings_row.get("analytics_active")) if settings_row is not None else False
            price_monitor_enabled = int(nm_id) in price_monitor_metadata
            if analytics_active and price_monitor_enabled:
                reason = "price_monitor_seed"
            elif analytics_active:
                reason = "analytics_active_flag"
            elif core_fallback_used and scope_name == CORE_SCOPE and price_monitor_enabled:
                reason = "price_monitor_seed_pending_backfill"
            elif price_monitor_enabled:
                reason = "price_monitor_list"
            elif settings_row is not None and bool(settings_row.get("active")):
                reason = "settings_products_active"
            else:
                reason = None

            items.append(
                ActiveProductsItemResponse(
                    nm_id=int(nm_id),
                    supplier_article=(
                        (settings_row.get("supplier_article") if settings_row is not None else None)
                        or (dim_row.get("supplier_article") if dim_row is not None else None)
                    ),
                    title=(
                        (settings_row.get("title") if settings_row is not None else None)
                        or (dim_row.get("title") if dim_row is not None else None)
                        or tracked_meta.get("tracked_label")
                    ),
                    brand=(
                        (settings_row.get("brand") if settings_row is not None else None)
                        or (dim_row.get("brand") if dim_row is not None else None)
                    ),
                    category=dim_row.get("category") if dim_row is not None else None,
                    subject=(
                        (settings_row.get("subject") if settings_row is not None else None)
                        or (dim_row.get("subject") if dim_row is not None else None)
                    ),
                    analytics_active=analytics_active,
                    price_monitor_enabled=price_monitor_enabled,
                    lifecycle_status=tracked_meta.get("lifecycle_status"),
                    reason=reason,
                )
            )

        return ActiveProductsResponse(scope=scope_name or CORE_SCOPE, rows=len(items), items=items)

    def get_price_monitor(self, payload: PriceMonitorRequest) -> PriceMonitorResponse:
        with self.readonly_session() as session:
            scope_name = normalize_product_scope(payload.scope)
            scope_nm_ids, _ = self._load_scope_nm_ids(session, scope_name)
            snapshot_resolved, _ = self._resolve_table_aliases(session, PRICE_SNAPSHOT_TABLE_NAME, PRICE_SNAPSHOT_ALIASES)
            snapshot_date_column = snapshot_resolved.get("snapshot_date")
            snapshot_nm_column = snapshot_resolved.get("nm_id")
            if snapshot_date_column is None or snapshot_nm_column is None:
                return PriceMonitorResponse(snapshot_date=payload.snapshot_date, rows=0, alerts=0, items=[])

            scope_where_sql = ""
            current_params: dict[str, Any] = {"snapshot_date": payload.snapshot_date}
            if scope_nm_ids is not None:
                if not scope_nm_ids:
                    return PriceMonitorResponse(snapshot_date=payload.snapshot_date, rows=0, alerts=0, items=[])
                scope_where_sql = f" and p.{_quote_ident(snapshot_nm_column)} = any(:scope_nm_ids)"
                current_params["scope_nm_ids"] = scope_nm_ids

            current_sql = f"""
                select
                    {_select_expr(snapshot_resolved, "snapshot_date", cast_type="DATE", table_alias="p")},
                    {_select_expr(snapshot_resolved, "snapshot_at", cast_type="TIMESTAMP", table_alias="p")},
                    {_select_expr(snapshot_resolved, "nm_id", cast_type="BIGINT", table_alias="p")},
                    {_select_expr(snapshot_resolved, "item_label", table_alias="p")},
                    {_select_expr(snapshot_resolved, "product_url", table_alias="p")},
                    {_select_expr(snapshot_resolved, "buyer_visible_price", cast_type="NUMERIC", table_alias="p")},
                    {_select_expr(snapshot_resolved, "fetch_status", table_alias="p")}
                from {PRICE_SNAPSHOT_TABLE_NAME} p
                where p.{_quote_ident(snapshot_date_column)} = :snapshot_date
                  {scope_where_sql}
                order by p.{_quote_ident(snapshot_nm_column)} asc
            """
            current_rows = session.execute(text(current_sql), current_params).mappings().all()
            if len(current_rows) > self.settings.max_rows:
                raise ValueError(f"Result exceeds MCP_MAX_ROWS={self.settings.max_rows}.")

            nm_ids = [int(row["nm_id"]) for row in current_rows if row.get("nm_id") is not None]
            history_rows: list[dict[str, Any]] = []
            if nm_ids:
                history_sql = f"""
                    select
                        {_select_expr(snapshot_resolved, "snapshot_date", cast_type="DATE", table_alias="p")},
                        {_select_expr(snapshot_resolved, "snapshot_at", cast_type="TIMESTAMP", table_alias="p")},
                        {_select_expr(snapshot_resolved, "nm_id", cast_type="BIGINT", table_alias="p")},
                        {_select_expr(snapshot_resolved, "item_label", table_alias="p")},
                        {_select_expr(snapshot_resolved, "product_url", table_alias="p")},
                        {_select_expr(snapshot_resolved, "buyer_visible_price", cast_type="NUMERIC", table_alias="p")},
                        {_select_expr(snapshot_resolved, "fetch_status", table_alias="p")}
                    from {PRICE_SNAPSHOT_TABLE_NAME} p
                    where p.{_quote_ident(snapshot_nm_column)} = any(:nm_ids)
                      and p.{_quote_ident(snapshot_date_column)} <= :snapshot_date
                    order by p.{_quote_ident(snapshot_nm_column)} asc, p.{_quote_ident(snapshot_date_column)} asc
                """
                history_rows = [
                    dict(row)
                    for row in session.execute(text(history_sql), {"nm_ids": nm_ids, "snapshot_date": payload.snapshot_date}).mappings().all()
                ]

                alert_resolved, _ = self._resolve_table_aliases(session, PRICE_ALERT_TABLE_NAME, PRICE_ALERT_ALIASES)
                alert_date_column = alert_resolved.get("snapshot_date")
                alert_nm_column = alert_resolved.get("nm_id")
                if alert_date_column is not None and alert_nm_column is not None:
                    alerts_sql = f"""
                        select
                            {_select_expr(alert_resolved, "snapshot_date", cast_type="DATE", table_alias="a")},
                            {_select_expr(alert_resolved, "nm_id", cast_type="BIGINT", table_alias="a")},
                            {_select_expr(alert_resolved, "current_price", cast_type="NUMERIC", table_alias="a")},
                            {_select_expr(alert_resolved, "previous_success_price", cast_type="NUMERIC", table_alias="a")},
                            {_select_expr(alert_resolved, "price_delta", cast_type="NUMERIC", table_alias="a")},
                            {_select_expr(alert_resolved, "alert_status", table_alias="a")}
                        from {PRICE_ALERT_TABLE_NAME} a
                        where a.{_quote_ident(alert_date_column)} = :snapshot_date
                          and a.{_quote_ident(alert_nm_column)} = any(:nm_ids)
                        order by a.{_quote_ident(alert_nm_column)} asc
                    """
                    alert_rows = [
                        dict(row)
                        for row in session.execute(
                            text(alerts_sql),
                            {"nm_ids": nm_ids, "snapshot_date": payload.snapshot_date},
                        ).mappings().all()
                    ]
                else:
                    alert_rows = []
            else:
                alert_rows = []

        supplier_article_map: dict[int, str | None] = {}
        title_map: dict[int, str | None] = {}
        if nm_ids:
            with self.readonly_session() as session:
                for table_name in (SETTINGS_PRODUCTS_TABLE_NAME, DIM_PRODUCT_TABLE_NAME):
                    available_columns = self._get_table_columns(session, table_name)
                    if not {"nm_id"} & available_columns:
                        continue
                    resolved_lookup, _ = resolve_column_aliases(available_columns, PRODUCT_LOOKUP_ALIASES)
                    lookup_nm_column = resolved_lookup.get("nm_id")
                    if lookup_nm_column is None:
                        continue
                    lookup_sql = f"""
                        select
                            {_select_expr(resolved_lookup, "nm_id", cast_type="BIGINT", table_alias="p")},
                            {_select_expr(resolved_lookup, "supplier_article", table_alias="p")},
                            {_select_expr(resolved_lookup, "title", table_alias="p")}
                        from {table_name} p
                        where p.{_quote_ident(lookup_nm_column)} = any(:nm_ids)
                    """
                    lookup_rows = session.execute(text(lookup_sql), {"nm_ids": nm_ids}).mappings().all()
                    for row in lookup_rows:
                        nm_id = int(row["nm_id"])
                        supplier_article_map.setdefault(nm_id, row.get("supplier_article"))
                        title_map.setdefault(nm_id, row.get("title"))

        snapshot_payload_rows = [
            {
                "snapshot_date": row["snapshot_date"],
                "snapshot_at": row.get("snapshot_at"),
                "nm_id": row["nm_id"],
                "item_label": row.get("item_label"),
                "supplier_article": supplier_article_map.get(int(row["nm_id"])),
                "product_name": title_map.get(int(row["nm_id"])) or row.get("item_label"),
                "product_url": row.get("product_url"),
                "buyer_visible_price": row.get("buyer_visible_price"),
                "fetch_status": row.get("fetch_status"),
            }
            for row in current_rows
        ]
        history_payload_rows = snapshot_payload_rows + [
            {
                "snapshot_date": row["snapshot_date"],
                "snapshot_at": row.get("snapshot_at"),
                "nm_id": row["nm_id"],
                "item_label": row.get("item_label"),
                "supplier_article": None,
                "product_name": row.get("item_label"),
                "product_url": row.get("product_url"),
                "buyer_visible_price": row.get("buyer_visible_price"),
                "fetch_status": row.get("fetch_status"),
            }
            for row in history_rows
            if row["snapshot_date"] < payload.snapshot_date
        ]
        alert_payload_rows = [dict(row) for row in alert_rows]
        return build_price_monitor_response(payload, history_payload_rows, alert_payload_rows)
