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
from src.mcp_server.settings import McpServiceSettings


ACTIVE_ALERT_STATUS = "PRICE_CHANGED_50"
SUPPRESSED_ALERT_PREFIX = "MANUAL_SUPPRESSED_"
logger = logging.getLogger(__name__)


class McpRepository(Protocol):
    def get_db_health(self) -> DbHealthResponse: ...
    def get_dashboard_summary(self, payload: DashboardSummaryRequest) -> DashboardSummaryResponse: ...
    def get_product_metrics(self, payload: ProductMetricsRequest) -> ProductMetricsResponse: ...
    def get_price_monitor(self, payload: PriceMonitorRequest) -> PriceMonitorResponse: ...


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


def build_dashboard_summary_response(
    payload: DashboardSummaryRequest,
    aggregate_row: Any,
    partial_rows: int,
    empty_rows: int,
    notes: list[str],
) -> DashboardSummaryResponse:
    cart_count = _as_decimal(aggregate_row.cart_count)
    order_count = _as_decimal(aggregate_row.order_count)
    order_sum = _as_decimal(aggregate_row.order_sum)
    ad_spend = _as_decimal(aggregate_row.ad_spend)
    ad_atbs = _as_decimal(aggregate_row.ad_atbs)
    ad_orders = _as_decimal(aggregate_row.ad_orders)
    return DashboardSummaryResponse(
        date_from=payload.date_from,
        date_to=payload.date_to,
        rows=int(aggregate_row.rows or 0),
        nm_count=int(aggregate_row.nm_count or 0),
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
                cart_count=None,
                order_count=None,
                order_sum=None,
                ad_spend=None,
            ),
        )

    daily: list[ProductDailyMetricsResponse] = []
    cart_total = Decimal("0")
    order_total = Decimal("0")
    order_sum_total = Decimal("0")
    ad_spend_total = Decimal("0")
    has_cart = False
    has_orders = False
    has_order_sum = False
    has_ad_spend = False

    for row in mart_rows:
        report_date = row["report_date"]
        cart_count = _as_decimal(row.get("cart_count"))
        order_count = _as_decimal(row.get("order_count"))
        order_sum = _as_decimal(row.get("order_sum"))
        ad_spend = _as_decimal(row.get("ad_campaign_spend_total"))
        ad_clicks = _as_decimal(row.get("ad_clicks_total"))
        ad_atbs = _as_decimal(row.get("ad_atbs_total"))
        ad_orders = _as_decimal(row.get("ad_orders_total"))
        current_stock_qty = _as_decimal(row.get("current_stock_qty"))

        if cart_count is not None:
            cart_total += cart_count
            has_cart = True
        if order_count is not None:
            order_total += order_count
            has_orders = True
        if order_sum is not None:
            order_sum_total += order_sum
            has_order_sum = True
        if ad_spend is not None:
            ad_spend_total += ad_spend
            has_ad_spend = True

        daily.append(
            ProductDailyMetricsResponse(
                date=report_date,
                card_clicks=_as_decimal(row.get("card_clicks")),
                cart_count=cart_count,
                order_count=order_count,
                order_sum=order_sum,
                ad_spend=ad_spend,
                ad_clicks=ad_clicks,
                ad_atbs=ad_atbs,
                ad_orders=ad_orders,
                current_stock_qty=current_stock_qty,
                wb_buyer_price=price_by_date.get((report_date, payload.nm_id)),
            )
        )

    first_row = mart_rows[0]
    return ProductMetricsResponse(
        found=True,
        nm_id=payload.nm_id,
        supplier_article=first_row.get("supplier_article"),
        product_name=first_row.get("title"),
        date_from=payload.date_from,
        date_to=payload.date_to,
        daily=daily,
        summary=ProductSummaryResponse(
            cart_count=cart_total if has_cart else None,
            order_count=order_total if has_orders else None,
            order_sum=order_sum_total if has_order_sum else None,
            ad_spend=ad_spend_total if has_ad_spend else None,
        ),
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

    def get_dashboard_summary(self, payload: DashboardSummaryRequest) -> DashboardSummaryResponse:
        validate_date_window(payload.date_from, payload.date_to, max_days=self.settings.max_date_range_days)
        with self.readonly_session() as session:
            base_stmt = (
                select(
                    func.count().label("rows"),
                    func.count(distinct(MartTotalReport.nm_id)).label("nm_count"),
                    func.sum(MartTotalReport.cart_count).label("cart_count"),
                    func.sum(MartTotalReport.order_count).label("order_count"),
                    func.sum(MartTotalReport.order_sum).label("order_sum"),
                    func.sum(MartTotalReport.ad_campaign_spend_total).label("ad_spend"),
                    func.sum(MartTotalReport.ad_atbs_total).label("ad_atbs"),
                    func.sum(MartTotalReport.ad_orders_total).label("ad_orders"),
                )
                .where(MartTotalReport.report_date >= payload.date_from)
                .where(MartTotalReport.report_date <= payload.date_to)
            )
            base_stmt = self._apply_tracked_filter(base_stmt, payload.only_tracked)
            aggregate_row = session.execute(base_stmt).one()

            status_stmt = (
                select(
                    func.sum(case((MartTotalReport.data_quality_status == "PARTIAL", 1), else_=0)).label("partial_rows"),
                    func.sum(case((MartTotalReport.data_quality_status == "NO_DATA", 1), else_=0)).label("empty_rows"),
                )
                .where(MartTotalReport.report_date >= payload.date_from)
                .where(MartTotalReport.report_date <= payload.date_to)
            )
            status_stmt = self._apply_tracked_filter(status_stmt, payload.only_tracked)
            status_row = session.execute(status_stmt).one()

        notes: list[str] = []
        if payload.only_tracked:
            notes.append("Tracked scope filtered via settings_products.active = true.")
        return build_dashboard_summary_response(
            payload=payload,
            aggregate_row=aggregate_row,
            partial_rows=int(status_row.partial_rows or 0),
            empty_rows=int(status_row.empty_rows or 0),
            notes=notes,
        )

    def get_product_metrics(self, payload: ProductMetricsRequest) -> ProductMetricsResponse:
        validate_date_window(payload.date_from, payload.date_to, max_days=self.settings.max_date_range_days)
        with self.readonly_session() as session:
            mart_stmt = (
                select(MartTotalReport)
                .where(MartTotalReport.nm_id == payload.nm_id)
                .where(MartTotalReport.report_date >= payload.date_from)
                .where(MartTotalReport.report_date <= payload.date_to)
                .order_by(MartTotalReport.report_date.asc())
            )
            mart_rows = session.execute(mart_stmt).scalars().all()
            if len(mart_rows) > self.settings.max_rows:
                raise ValueError(f"Result exceeds MCP_MAX_ROWS={self.settings.max_rows}.")

            price_stmt = (
                select(FactWbSitePriceSnapshot)
                .where(FactWbSitePriceSnapshot.nm_id == payload.nm_id)
                .where(FactWbSitePriceSnapshot.snapshot_date >= payload.date_from)
                .where(FactWbSitePriceSnapshot.snapshot_date <= payload.date_to)
                .order_by(FactWbSitePriceSnapshot.snapshot_date.asc())
            )
            price_rows = session.execute(price_stmt).scalars().all()

        mart_payload_rows = [
            {
                "report_date": row.report_date,
                "supplier_article": row.supplier_article,
                "title": row.title,
                "card_clicks": row.card_clicks,
                "cart_count": row.cart_count,
                "order_count": row.order_count,
                "order_sum": row.order_sum,
                "ad_campaign_spend_total": row.ad_campaign_spend_total,
                "ad_clicks_total": row.ad_clicks_total,
                "ad_atbs_total": row.ad_atbs_total,
                "ad_orders_total": row.ad_orders_total,
                "current_stock_qty": row.current_stock_qty,
            }
            for row in mart_rows
        ]
        price_payload_rows = [
            {
                "snapshot_date": row.snapshot_date,
                "snapshot_at": row.snapshot_at,
                "nm_id": row.nm_id,
                "buyer_visible_price": row.buyer_visible_price,
            }
            for row in price_rows
        ]
        return build_product_metrics_response(payload, mart_payload_rows, price_payload_rows)

    def get_price_monitor(self, payload: PriceMonitorRequest) -> PriceMonitorResponse:
        with self.readonly_session() as session:
            current_stmt = (
                select(
                    FactWbSitePriceSnapshot.snapshot_date,
                    FactWbSitePriceSnapshot.snapshot_at,
                    FactWbSitePriceSnapshot.nm_id,
                    FactWbSitePriceSnapshot.item_label,
                    FactWbSitePriceSnapshot.product_url,
                    FactWbSitePriceSnapshot.buyer_visible_price,
                    FactWbSitePriceSnapshot.fetch_status,
                    SettingsProducts.supplier_article.label("settings_supplier_article"),
                    SettingsProducts.title.label("settings_title"),
                    DimProduct.supplier_article.label("dim_supplier_article"),
                    DimProduct.title.label("dim_title"),
                )
                .select_from(FactWbSitePriceSnapshot)
                .outerjoin(SettingsProducts, SettingsProducts.nm_id == FactWbSitePriceSnapshot.nm_id)
                .outerjoin(DimProduct, DimProduct.nm_id == FactWbSitePriceSnapshot.nm_id)
                .where(FactWbSitePriceSnapshot.snapshot_date == payload.snapshot_date)
                .order_by(FactWbSitePriceSnapshot.nm_id.asc())
            )
            current_rows = session.execute(current_stmt).all()
            if len(current_rows) > self.settings.max_rows:
                raise ValueError(f"Result exceeds MCP_MAX_ROWS={self.settings.max_rows}.")

            nm_ids = [int(row.nm_id) for row in current_rows]
            history_rows: list[Any] = []
            if nm_ids:
                history_stmt = (
                    select(FactWbSitePriceSnapshot)
                    .where(FactWbSitePriceSnapshot.nm_id.in_(nm_ids))
                    .where(FactWbSitePriceSnapshot.snapshot_date <= payload.snapshot_date)
                    .order_by(FactWbSitePriceSnapshot.nm_id.asc(), FactWbSitePriceSnapshot.snapshot_date.asc())
                )
                history_rows = session.execute(history_stmt).scalars().all()

                alerts_stmt = (
                    select(FactWbSitePriceAlert)
                    .where(FactWbSitePriceAlert.snapshot_date == payload.snapshot_date)
                    .where(FactWbSitePriceAlert.nm_id.in_(nm_ids))
                    .order_by(FactWbSitePriceAlert.nm_id.asc())
                )
                alert_rows = session.execute(alerts_stmt).scalars().all()
            else:
                alert_rows = []

        snapshot_payload_rows = [
            {
                "snapshot_date": row.snapshot_date,
                "snapshot_at": row.snapshot_at,
                "nm_id": row.nm_id,
                "item_label": row.item_label,
                "supplier_article": row.settings_supplier_article or row.dim_supplier_article,
                "product_name": row.settings_title or row.dim_title or row.item_label,
                "product_url": row.product_url,
                "buyer_visible_price": row.buyer_visible_price,
                "fetch_status": row.fetch_status,
            }
            for row in current_rows
        ]
        history_payload_rows = snapshot_payload_rows + [
            {
                "snapshot_date": row.snapshot_date,
                "snapshot_at": row.snapshot_at,
                "nm_id": row.nm_id,
                "item_label": row.item_label,
                "supplier_article": None,
                "product_name": row.item_label,
                "product_url": row.product_url,
                "buyer_visible_price": row.buyer_visible_price,
                "fetch_status": row.fetch_status,
            }
            for row in history_rows
            if row.snapshot_date < payload.snapshot_date
        ]
        alert_payload_rows = [
            {
                "snapshot_date": row.snapshot_date,
                "nm_id": row.nm_id,
                "current_price": row.current_price,
                "previous_success_price": row.previous_success_price,
                "price_delta": row.price_delta,
                "alert_status": row.alert_status,
            }
            for row in alert_rows
        ]
        return build_price_monitor_response(payload, history_payload_rows, alert_payload_rows)
