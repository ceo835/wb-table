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
    MartSchemaColumnResponse,
    MartSchemaResponse,
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
MART_TABLE_NAME = "mart_total_report"
SETTINGS_PRODUCTS_TABLE_NAME = "settings_products"
DIM_PRODUCT_TABLE_NAME = "dim_product"
PRICE_SNAPSHOT_TABLE_NAME = "fact_wb_site_price_snapshot"
PRICE_ALERT_TABLE_NAME = "fact_wb_site_price_alert"

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


class McpRepository(Protocol):
    def get_db_health(self) -> DbHealthResponse: ...
    def get_mart_schema(self) -> MartSchemaResponse: ...
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


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    getter = getattr(row, key, None)
    if getter is not None:
        return getter
    if hasattr(row, "_mapping"):
        return row._mapping.get(key)
    return None


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
                ctr=_as_decimal(row.get("ctr")),
                cart_count=cart_count,
                add_to_cart_conversion=_as_decimal(row.get("add_to_cart_conversion")),
                order_count=order_count,
                cart_to_order_conversion=_as_decimal(row.get("cart_to_order_conversion")),
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
            if payload.only_tracked:
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
            """
            aggregate_row = session.execute(
                text(aggregate_sql),
                {"date_from": payload.date_from, "date_to": payload.date_to},
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
                """
                status_row = session.execute(
                    text(status_sql),
                    {"date_from": payload.date_from, "date_to": payload.date_to},
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

    def get_price_monitor(self, payload: PriceMonitorRequest) -> PriceMonitorResponse:
        with self.readonly_session() as session:
            snapshot_resolved, _ = self._resolve_table_aliases(session, PRICE_SNAPSHOT_TABLE_NAME, PRICE_SNAPSHOT_ALIASES)
            snapshot_date_column = snapshot_resolved.get("snapshot_date")
            snapshot_nm_column = snapshot_resolved.get("nm_id")
            if snapshot_date_column is None or snapshot_nm_column is None:
                return PriceMonitorResponse(snapshot_date=payload.snapshot_date, rows=0, alerts=0, items=[])

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
                order by p.{_quote_ident(snapshot_nm_column)} asc
            """
            current_rows = session.execute(text(current_sql), {"snapshot_date": payload.snapshot_date}).mappings().all()
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
