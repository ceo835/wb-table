from __future__ import annotations

from datetime import date
from decimal import Decimal
from time import perf_counter
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


FINANCE_SEMANTICS_NOTE = (
    "fact_finance_realization_line uses operation_date derived from realization rows; "
    "it is suitable for observed logistics costs, but not for causal same-day attribution."
)
OPERATING_PROFIT_SEMANTICS_NOTE = (
    "Operating profit comes from fact_vvbromo_product_day and is maintained in the VVBromo layer. "
    "The project reads the stored field as-is and does not reconstruct a new formula inside MCP."
)
SELLER_PRICE_SPP_NOTE = (
    "SPP is derived only when fact_wb_seller_price_snapshot has a unique seller_price for date+nm_id. "
    "If size rows disagree, SPP stays PARTIAL instead of being averaged."
)
COMPETITOR_MAPPING_NOTE = (
    "Competitor mapping uses settings_products.query_group -> fact_competitor_wb_site_price_snapshot.competitor_group_key."
)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _record_query(query_counter: dict[str, Any], query_name: str, started_at: float) -> None:
    query_counter["count"] = int(query_counter.get("count") or 0) + 1
    elapsed_ms = int((perf_counter() - started_at) * 1000)
    query_counter.setdefault("timings", []).append({"query": query_name, "ms": elapsed_ms})


def _execute_one(session: Session, sql, params: dict[str, Any], query_counter: dict[str, Any], query_name: str) -> dict[str, Any]:
    started_at = perf_counter()
    row = session.execute(sql, params).mappings().one()
    _record_query(query_counter, query_name, started_at)
    return dict(row)


def _execute_rows(session: Session, sql, params: dict[str, Any], query_counter: dict[str, Any], query_name: str) -> list[dict[str, Any]]:
    started_at = perf_counter()
    rows = [dict(row) for row in session.execute(sql, params).mappings().all()]
    _record_query(query_counter, query_name, started_at)
    return rows


def _pct(filled: Any, total: Any) -> Decimal | None:
    filled_decimal = _to_decimal(filled)
    total_decimal = _to_decimal(total)
    if filled_decimal is None or total_decimal in (None, Decimal("0")):
        return None
    return filled_decimal / total_decimal * Decimal("100")


def _date_range(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "min_date": meta.get("min_date"),
        "max_date": meta.get("max_date"),
    }


def _coverage_item(
    *,
    metric_key: str,
    table_name: str,
    field_name: str,
    grain: str,
    join_keys: list[str],
    meta: dict[str, Any],
    filled_rows: Any | None,
    quality_status: str,
    limitations: list[str],
) -> dict[str, Any]:
    return {
        "metric_key": metric_key,
        "table": table_name,
        "field": field_name,
        "grain": grain,
        "date_range": _date_range(meta),
        "row_count": meta.get("rows"),
        "date_count": meta.get("day_count"),
        "nm_count": meta.get("nm_count"),
        "fill_rows": filled_rows,
        "fill_rate_pct": _pct(filled_rows, meta.get("rows")) if filled_rows is not None else None,
        "join_keys": join_keys,
        "quality_status": quality_status,
        "limitations": limitations,
    }


def fetch_database_audit_block(
    session: Session,
    *,
    query_counter: dict[str, Any],
) -> dict[str, Any]:
    vvbromo_meta = _execute_one(
        session,
        text(
            """
            select
                min(day) as min_date,
                max(day) as max_date,
                count(*) as rows,
                count(distinct day) as day_count,
                count(distinct nm_id) as nm_count,
                count(operating_profit) as operating_profit_rows,
                count(operating_profit_per_unit) as operating_profit_per_unit_rows,
                count(organic_sales) as organic_sales_rows
            from fact_vvbromo_product_day
            """
        ),
        {},
        query_counter,
        "database_audit_vvbromo",
    )
    finance_meta = _execute_one(
        session,
        text(
            """
            select
                min(operation_date) as min_date,
                max(operation_date) as max_date,
                count(*) as rows,
                count(distinct operation_date) as day_count,
                count(distinct nm_id) filter (where nm_id is not null) as nm_count,
                count(delivery_rub) as delivery_rows,
                count(rebill_logistic_cost) as rebill_rows,
                count(storage_fee) as storage_rows,
                count(acceptance) as acceptance_rows,
                count(penalty) as penalty_rows,
                count(deduction) as deduction_rows,
                count(additional_payment) as additional_payment_rows
            from fact_finance_realization_line
            """
        ),
        {},
        query_counter,
        "database_audit_finance",
    )
    site_price_meta = _execute_one(
        session,
        text(
            """
            select
                min(snapshot_date) as min_date,
                max(snapshot_date) as max_date,
                count(*) as rows,
                count(distinct snapshot_date) as day_count,
                count(distinct nm_id) as nm_count,
                count(buyer_visible_price) as buyer_visible_price_rows,
                count(*) filter (where fetch_status = 'success') as success_rows
            from fact_wb_site_price_snapshot
            """
        ),
        {},
        query_counter,
        "database_audit_site_price",
    )
    seller_price_meta = _execute_one(
        session,
        text(
            """
            select
                min(snapshot_date) as min_date,
                max(snapshot_date) as max_date,
                count(*) as rows,
                count(distinct snapshot_date) as day_count,
                count(distinct nm_id) as nm_count,
                count(seller_price) as seller_price_rows,
                count(discount) as discount_rows,
                count(price) as price_rows
            from fact_wb_seller_price_snapshot
            """
        ),
        {},
        query_counter,
        "database_audit_seller_price",
    )
    competitor_meta = _execute_one(
        session,
        text(
            """
            select
                min(snapshot_date) as min_date,
                max(snapshot_date) as max_date,
                count(*) as rows,
                count(distinct snapshot_date) as day_count,
                count(distinct competitor_group_key) as group_count,
                count(distinct competitor_nm_id) as competitor_nm_count,
                count(buyer_visible_price) as buyer_visible_price_rows,
                count(*) filter (where fetch_status = 'success') as success_rows
            from fact_competitor_wb_site_price_snapshot
            """
        ),
        {},
        query_counter,
        "database_audit_competitor",
    )
    price_alert_meta = _execute_one(
        session,
        text(
            """
            select
                min(snapshot_date) as min_date,
                max(snapshot_date) as max_date,
                count(*) as rows,
                count(distinct snapshot_date) as day_count,
                count(distinct nm_id) as nm_count,
                count(price_delta) as price_delta_rows
            from fact_wb_site_price_alert
            """
        ),
        {},
        query_counter,
        "database_audit_price_alert",
    )
    localization_meta = _execute_one(
        session,
        text(
            """
            select
                min(date) as min_date,
                max(date) as max_date,
                count(*) as rows,
                count(distinct date) as day_count,
                count(distinct nm_id) as nm_count,
                count(local_orders_percent) as local_orders_percent_rows,
                count(delivery_time) as delivery_time_rows
            from fact_localization_region_day
            """
        ),
        {},
        query_counter,
        "database_audit_localization",
    )
    mapping_meta = _execute_one(
        session,
        text(
            """
            with product_groups as (
                select distinct nm_id, query_group
                from settings_products
                where active is true and query_group is not null and btrim(query_group) <> ''
            ),
            competitor_groups as (
                select distinct competitor_group_key
                from fact_competitor_wb_site_price_snapshot
            )
            select
                count(*) as product_group_rows,
                count(*) filter (where cg.competitor_group_key is not null) as mapped_rows,
                count(distinct pg.query_group) as product_group_count,
                count(distinct cg.competitor_group_key) filter (where cg.competitor_group_key is not null) as mapped_group_count
            from product_groups pg
            left join competitor_groups cg on cg.competitor_group_key = pg.query_group
            """
        ),
        {},
        query_counter,
        "database_audit_competitor_mapping",
    )

    items = [
        _coverage_item(
            metric_key="operating_profit",
            table_name="fact_vvbromo_product_day",
            field_name="operating_profit",
            grain="day + nm_id",
            join_keys=["day", "nm_id"],
            meta=vvbromo_meta,
            filled_rows=vvbromo_meta.get("operating_profit_rows"),
            quality_status="OK",
            limitations=[OPERATING_PROFIT_SEMANTICS_NOTE],
        ),
        _coverage_item(
            metric_key="operating_profit_per_unit",
            table_name="fact_vvbromo_product_day",
            field_name="operating_profit_per_unit",
            grain="day + nm_id",
            join_keys=["day", "nm_id"],
            meta=vvbromo_meta,
            filled_rows=vvbromo_meta.get("operating_profit_per_unit_rows"),
            quality_status="OK",
            limitations=[OPERATING_PROFIT_SEMANTICS_NOTE],
        ),
        _coverage_item(
            metric_key="buyer_visible_price",
            table_name="fact_wb_site_price_snapshot",
            field_name="buyer_visible_price",
            grain="snapshot_date + nm_id",
            join_keys=["snapshot_date", "nm_id"],
            meta=site_price_meta,
            filled_rows=site_price_meta.get("buyer_visible_price_rows"),
            quality_status="OK",
            limitations=["Historical client price uses exact snapshot_date rows only."],
        ),
        _coverage_item(
            metric_key="seller_price",
            table_name="fact_wb_seller_price_snapshot",
            field_name="seller_price",
            grain="snapshot_date + nm_id + chrt_id",
            join_keys=["snapshot_date", "nm_id", "chrt_id"],
            meta=seller_price_meta,
            filled_rows=seller_price_meta.get("seller_price_rows"),
            quality_status="PARTIAL",
            limitations=[SELLER_PRICE_SPP_NOTE],
        ),
        _coverage_item(
            metric_key="spp_pct",
            table_name="fact_wb_site_price_snapshot + fact_wb_seller_price_snapshot",
            field_name="derived_spp_pct",
            grain="snapshot_date + nm_id",
            join_keys=["snapshot_date", "nm_id"],
            meta=site_price_meta,
            filled_rows=None,
            quality_status="PARTIAL",
            limitations=[SELLER_PRICE_SPP_NOTE],
        ),
        _coverage_item(
            metric_key="total_logistics_cost",
            table_name="fact_finance_realization_line",
            field_name="delivery_rub + rebill_logistic_cost + storage_fee + acceptance + penalty + deduction + additional_payment",
            grain="operation_date + nm_id + rrd_id",
            join_keys=["operation_date", "nm_id"],
            meta=finance_meta,
            filled_rows=finance_meta.get("rows"),
            quality_status="PARTIAL",
            limitations=[FINANCE_SEMANTICS_NOTE],
        ),
        _coverage_item(
            metric_key="delivery_rub",
            table_name="fact_finance_realization_line",
            field_name="delivery_rub",
            grain="operation_date + nm_id + rrd_id",
            join_keys=["operation_date", "nm_id"],
            meta=finance_meta,
            filled_rows=finance_meta.get("delivery_rows"),
            quality_status="PARTIAL",
            limitations=[FINANCE_SEMANTICS_NOTE],
        ),
        _coverage_item(
            metric_key="storage_fee",
            table_name="fact_finance_realization_line",
            field_name="storage_fee",
            grain="operation_date + nm_id + rrd_id",
            join_keys=["operation_date", "nm_id"],
            meta=finance_meta,
            filled_rows=finance_meta.get("storage_rows"),
            quality_status="PARTIAL",
            limitations=[FINANCE_SEMANTICS_NOTE],
        ),
        _coverage_item(
            metric_key="competitor_buyer_visible_price",
            table_name="fact_competitor_wb_site_price_snapshot",
            field_name="buyer_visible_price",
            grain="snapshot_date + competitor_group_key + competitor_nm_id + size_key",
            join_keys=["snapshot_date", "competitor_group_key"],
            meta={**competitor_meta, "nm_count": competitor_meta.get("competitor_nm_count")},
            filled_rows=competitor_meta.get("buyer_visible_price_rows"),
            quality_status="PARTIAL",
            limitations=["Competitor history is sparse and uses competitor-group mapping rather than direct our_nm_id storage."],
        ),
        {
            "metric_key": "competitor_mapping_query_group",
            "table": "settings_products + fact_competitor_wb_site_price_snapshot",
            "field": "settings_products.query_group -> competitor_group_key",
            "grain": "active nm_id -> query_group",
            "date_range": _date_range(competitor_meta),
            "row_count": mapping_meta.get("product_group_rows"),
            "date_count": None,
            "nm_count": None,
            "fill_rows": mapping_meta.get("mapped_rows"),
            "fill_rate_pct": _pct(mapping_meta.get("mapped_rows"), mapping_meta.get("product_group_rows")),
            "join_keys": ["query_group", "competitor_group_key"],
            "quality_status": "PARTIAL",
            "limitations": [COMPETITOR_MAPPING_NOTE],
        },
        _coverage_item(
            metric_key="price_alert_delta",
            table_name="fact_wb_site_price_alert",
            field_name="price_delta",
            grain="snapshot_date + nm_id",
            join_keys=["snapshot_date", "nm_id"],
            meta=price_alert_meta,
            filled_rows=price_alert_meta.get("price_delta_rows"),
            quality_status="OK",
            limitations=["Useful as an auxiliary price anomaly signal, not as causal proof."],
        ),
        _coverage_item(
            metric_key="local_orders_percent",
            table_name="fact_localization_region_day",
            field_name="local_orders_percent",
            grain="period_start + period_end + date + nm_id + region",
            join_keys=["date", "nm_id"],
            meta=localization_meta,
            filled_rows=localization_meta.get("local_orders_percent_rows"),
            quality_status="PARTIAL",
            limitations=["Regional rows are richer than the current summary grain and can be misread without explicit scope."],
        ),
    ]
    return {
        "status": "OK",
        "inventory": items,
        "tables": {
            "fact_vvbromo_product_day": vvbromo_meta,
            "fact_finance_realization_line": finance_meta,
            "fact_wb_site_price_snapshot": site_price_meta,
            "fact_wb_seller_price_snapshot": seller_price_meta,
            "fact_competitor_wb_site_price_snapshot": competitor_meta,
            "fact_wb_site_price_alert": price_alert_meta,
            "fact_localization_region_day": localization_meta,
        },
        "competitor_mapping": mapping_meta,
    }


def fetch_logistics_summary_block(
    session: Session,
    *,
    report_date: date,
    compare_date: date,
    trend_current_from: date,
    trend_current_to: date,
    trend_previous_from: date,
    trend_previous_to: date,
    top_n: int,
    query_counter: dict[str, Any],
) -> dict[str, Any]:
    daily_rows = _execute_rows(
        session,
        text(
            """
            select
                operation_date,
                sum(coalesce(delivery_rub, 0)) as delivery_rub,
                sum(coalesce(rebill_logistic_cost, 0)) as rebill_logistic_cost,
                sum(coalesce(storage_fee, 0)) as storage_fee,
                sum(coalesce(acceptance, 0)) as acceptance,
                sum(coalesce(penalty, 0)) as penalty,
                sum(coalesce(deduction, 0)) as deduction,
                sum(coalesce(additional_payment, 0)) as additional_payment,
                sum(coalesce(quantity, 0)) as quantity,
                count(*) as rows_count,
                count(distinct nm_id) filter (where nm_id is not null) as nm_count
            from fact_finance_realization_line
            where operation_date in (:report_date, :compare_date)
            group by operation_date
            order by operation_date asc
            """
        ),
        {"report_date": report_date, "compare_date": compare_date},
        query_counter,
        "logistics_summary_daily",
    )
    trend_rows = _execute_rows(
        session,
        text(
            """
            select
                case
                    when operation_date >= :trend_current_from and operation_date <= :trend_current_to then 'current'
                    when operation_date >= :trend_previous_from and operation_date <= :trend_previous_to then 'previous'
                    else null
                end as bucket,
                max(operation_date) as max_date,
                sum(coalesce(delivery_rub, 0)) as delivery_rub,
                sum(coalesce(rebill_logistic_cost, 0)) as rebill_logistic_cost,
                sum(coalesce(storage_fee, 0)) as storage_fee,
                sum(coalesce(acceptance, 0)) as acceptance,
                sum(coalesce(penalty, 0)) as penalty,
                sum(coalesce(deduction, 0)) as deduction,
                sum(coalesce(additional_payment, 0)) as additional_payment,
                sum(coalesce(quantity, 0)) as quantity
            from fact_finance_realization_line
            where operation_date >= :trend_previous_from and operation_date <= :trend_current_to
            group by bucket
            order by bucket asc
            """
        ),
        {
            "trend_current_from": trend_current_from,
            "trend_current_to": trend_current_to,
            "trend_previous_from": trend_previous_from,
            "trend_previous_to": trend_previous_to,
        },
        query_counter,
        "logistics_summary_trend",
    )
    article_rows = _execute_rows(
        session,
        text(
            """
            with current_day as (
                select
                    operation_date,
                    nm_id,
                    sum(coalesce(delivery_rub, 0)) as delivery_rub,
                    sum(coalesce(rebill_logistic_cost, 0)) as rebill_logistic_cost,
                    sum(coalesce(storage_fee, 0)) as storage_fee,
                    sum(coalesce(acceptance, 0)) as acceptance,
                    sum(coalesce(penalty, 0)) as penalty,
                    sum(coalesce(deduction, 0)) as deduction,
                    sum(coalesce(additional_payment, 0)) as additional_payment,
                    sum(coalesce(quantity, 0)) as quantity
                from fact_finance_realization_line
                where operation_date = :report_date and nm_id is not null
                group by operation_date, nm_id
            ),
            previous_day as (
                select
                    operation_date,
                    nm_id,
                    sum(coalesce(delivery_rub, 0) + coalesce(rebill_logistic_cost, 0) + coalesce(storage_fee, 0) + coalesce(acceptance, 0) + coalesce(penalty, 0) + coalesce(deduction, 0) + coalesce(additional_payment, 0)) as total_logistics_cost
                from fact_finance_realization_line
                where operation_date = :compare_date and nm_id is not null
                group by operation_date, nm_id
            ),
            mart_day as (
                select report_date, nm_id, supplier_article, title, subject, brand, order_count, order_sum
                from mart_total_report
                where report_date = :report_date
            )
            select
                c.nm_id,
                m.supplier_article,
                m.title,
                m.subject,
                m.brand,
                m.order_count,
                m.order_sum,
                c.delivery_rub,
                c.rebill_logistic_cost,
                c.storage_fee,
                c.acceptance,
                c.penalty,
                c.deduction,
                c.additional_payment,
                c.quantity,
                (coalesce(c.delivery_rub, 0) + coalesce(c.rebill_logistic_cost, 0) + coalesce(c.storage_fee, 0) + coalesce(c.acceptance, 0) + coalesce(c.penalty, 0) + coalesce(c.deduction, 0) + coalesce(c.additional_payment, 0)) as total_logistics_cost,
                p.total_logistics_cost as previous_total_logistics_cost
            from current_day c
            left join previous_day p on p.nm_id = c.nm_id
            left join mart_day m on m.nm_id = c.nm_id
            order by total_logistics_cost desc nulls last, c.nm_id asc
            """
        ),
        {"report_date": report_date, "compare_date": compare_date},
        query_counter,
        "logistics_summary_articles",
    )
    daily_by_date = {row.get("operation_date"): row for row in daily_rows}
    current = daily_by_date.get(report_date, {})
    previous = daily_by_date.get(compare_date, {})
    component_keys = (
        "delivery_rub",
        "rebill_logistic_cost",
        "storage_fee",
        "acceptance",
        "penalty",
        "deduction",
        "additional_payment",
    )

    def _total(row: dict[str, Any]) -> Decimal | None:
        if not row:
            return None
        return sum((_to_decimal(row.get(key)) or Decimal("0")) for key in component_keys)

    current_total = _total(current)
    previous_total = _total(previous)
    trend_by_bucket = {row.get("bucket"): row for row in trend_rows}
    current_trend_total = _total(trend_by_bucket.get("current", {}))
    previous_trend_total = _total(trend_by_bucket.get("previous", {}))

    enriched_articles = []
    for row in article_rows:
        current_value = _to_decimal(row.get("total_logistics_cost")) or Decimal("0")
        previous_value = _to_decimal(row.get("previous_total_logistics_cost")) or Decimal("0")
        quantity = _to_decimal(row.get("quantity"))
        logistics_per_unit = None
        if quantity not in (None, Decimal("0")):
            logistics_per_unit = current_value / quantity
        enriched_articles.append({
            **row,
            "delta_day": current_value - previous_value,
            "logistics_per_unit": logistics_per_unit,
            "per_unit_basis": "finance.quantity" if logistics_per_unit is not None else None,
        })

    top_growth = [row for row in enriched_articles if (_to_decimal(row.get("delta_day")) or Decimal("0")) > 0]
    top_growth.sort(key=lambda item: _to_decimal(item.get("delta_day")) or Decimal("0"), reverse=True)

    current_quantity = _to_decimal(current.get("quantity"))
    logistics_per_unit = None
    per_unit_status = "UNCONFIRMED"
    if current_total is not None and current_quantity not in (None, Decimal("0")):
        logistics_per_unit = current_total / current_quantity
        per_unit_status = "OK"

    return {
        "status": "PARTIAL" if current_total is not None else "MISSING",
        "source_table": "fact_finance_realization_line",
        "source_status": "PARTIAL",
        "semantics": FINANCE_SEMANTICS_NOTE,
        "overall": {
            "report_date": report_date,
            "compare_date": compare_date,
            "total_logistics_cost": current_total,
            "previous_total_logistics_cost": previous_total,
            "delta_day": (current_total - previous_total) if current_total is not None and previous_total is not None else None,
            "logistics_per_unit": logistics_per_unit,
            "per_unit_status": per_unit_status,
            "per_unit_basis": "finance.quantity",
            "rows_count": current.get("rows_count"),
            "nm_count": current.get("nm_count"),
            "components": {key: current.get(key) for key in component_keys},
        },
        "weekly_trend": {
            "current_total": current_trend_total,
            "previous_total": previous_trend_total,
            "delta": (current_trend_total - previous_trend_total) if current_trend_total is not None and previous_trend_total is not None else None,
            "current_window": {"from": trend_current_from, "to": trend_current_to},
            "previous_window": {"from": trend_previous_from, "to": trend_previous_to},
        },
        "top_growth_articles": top_growth[:top_n],
        "limitations": [FINANCE_SEMANTICS_NOTE],
    }


def fetch_operating_profit_block(
    session: Session,
    *,
    report_date: date,
    compare_date: date,
    trend_current_from: date,
    trend_current_to: date,
    trend_previous_from: date,
    trend_previous_to: date,
    top_n: int,
    query_counter: dict[str, Any],
) -> dict[str, Any]:
    summary_rows = _execute_rows(
        session,
        text(
            """
            select
                day,
                sum(coalesce(operating_profit, 0)) as operating_profit,
                sum(coalesce(organic_sales, 0)) as organic_sales,
                case when sum(coalesce(organic_sales, 0)) > 0 then sum(coalesce(operating_profit, 0)) / nullif(sum(coalesce(organic_sales, 0)), 0) end as operating_profit_per_unit
            from fact_vvbromo_product_day
            where day in (:report_date, :compare_date)
            group by day
            order by day asc
            """
        ),
        {"report_date": report_date, "compare_date": compare_date},
        query_counter,
        "operating_profit_summary_daily",
    )
    trend_rows = _execute_rows(
        session,
        text(
            """
            select
                case
                    when day >= :trend_current_from and day <= :trend_current_to then 'current'
                    when day >= :trend_previous_from and day <= :trend_previous_to then 'previous'
                    else null
                end as bucket,
                max(day) as max_day,
                sum(coalesce(operating_profit, 0)) as operating_profit,
                sum(coalesce(organic_sales, 0)) as organic_sales,
                case when sum(coalesce(organic_sales, 0)) > 0 then sum(coalesce(operating_profit, 0)) / nullif(sum(coalesce(organic_sales, 0)), 0) end as operating_profit_per_unit
            from fact_vvbromo_product_day
            where day >= :trend_previous_from and day <= :trend_current_to
            group by bucket
            order by bucket asc
            """
        ),
        {
            "trend_current_from": trend_current_from,
            "trend_current_to": trend_current_to,
            "trend_previous_from": trend_previous_from,
            "trend_previous_to": trend_previous_to,
        },
        query_counter,
        "operating_profit_summary_trend",
    )
    article_rows = _execute_rows(
        session,
        text(
            """
            with current_day as (
                select day, nm_id, vendor_code, organic_sales, operating_profit, operating_profit_per_unit
                from fact_vvbromo_product_day
                where day = :report_date
            ),
            previous_day as (
                select day, nm_id, operating_profit, operating_profit_per_unit
                from fact_vvbromo_product_day
                where day = :compare_date
            ),
            mart_day as (
                select report_date, nm_id, supplier_article, title, subject, brand, order_sum, ad_spend_total
                from mart_total_report
                where report_date = :report_date
            ),
            price_current as (
                select snapshot_date, nm_id, buyer_visible_price
                from fact_wb_site_price_snapshot
                where snapshot_date = :report_date
            ),
            price_previous as (
                select snapshot_date, nm_id, buyer_visible_price
                from fact_wb_site_price_snapshot
                where snapshot_date = :compare_date
            ),
            logistics_current as (
                select
                    operation_date,
                    nm_id,
                    sum(coalesce(delivery_rub, 0) + coalesce(rebill_logistic_cost, 0) + coalesce(storage_fee, 0) + coalesce(acceptance, 0) + coalesce(penalty, 0) + coalesce(deduction, 0) + coalesce(additional_payment, 0)) as total_logistics_cost
                from fact_finance_realization_line
                where operation_date = :report_date and nm_id is not null
                group by operation_date, nm_id
            )
            select
                c.nm_id,
                coalesce(m.supplier_article, c.vendor_code) as supplier_article,
                m.title,
                m.subject,
                m.brand,
                c.organic_sales,
                c.operating_profit,
                c.operating_profit_per_unit,
                p.operating_profit as previous_operating_profit,
                p.operating_profit_per_unit as previous_operating_profit_per_unit,
                m.order_sum,
                m.ad_spend_total,
                l.total_logistics_cost,
                pc.buyer_visible_price as buyer_visible_price,
                pp.buyer_visible_price as previous_buyer_visible_price
            from current_day c
            left join previous_day p on p.nm_id = c.nm_id
            left join mart_day m on m.nm_id = c.nm_id
            left join logistics_current l on l.nm_id = c.nm_id
            left join price_current pc on pc.nm_id = c.nm_id
            left join price_previous pp on pp.nm_id = c.nm_id
            order by c.operating_profit desc nulls last, c.nm_id asc
            """
        ),
        {"report_date": report_date, "compare_date": compare_date},
        query_counter,
        "operating_profit_articles",
    )
    freshness = _execute_one(
        session,
        text("select max(day) as max_day from fact_vvbromo_product_day"),
        {},
        query_counter,
        "operating_profit_freshness",
    )

    daily_by_date = {row.get("day"): row for row in summary_rows}
    current = daily_by_date.get(report_date, {})
    previous = daily_by_date.get(compare_date, {})
    trend_by_bucket = {row.get("bucket"): row for row in trend_rows}
    enriched_articles = []
    for row in article_rows:
        current_profit = _to_decimal(row.get("operating_profit")) or Decimal("0")
        previous_profit = _to_decimal(row.get("previous_operating_profit")) or Decimal("0")
        current_price = _to_decimal(row.get("buyer_visible_price"))
        previous_price = _to_decimal(row.get("previous_buyer_visible_price"))
        enriched_articles.append({
            **row,
            "delta_day": current_profit - previous_profit,
            "price_delta_day": (current_price - previous_price) if current_price is not None and previous_price is not None else None,
        })
    positive = [row for row in enriched_articles if (_to_decimal(row.get("operating_profit")) or Decimal("0")) > 0]
    negative = [row for row in enriched_articles if (_to_decimal(row.get("operating_profit")) or Decimal("0")) < 0]
    positive.sort(key=lambda item: _to_decimal(item.get("operating_profit")) or Decimal("0"), reverse=True)
    negative.sort(key=lambda item: _to_decimal(item.get("operating_profit")) or Decimal("0"))

    return {
        "status": "OK" if current.get("operating_profit") is not None else "MISSING",
        "source_table": "fact_vvbromo_product_day",
        "semantics": OPERATING_PROFIT_SEMANTICS_NOTE,
        "freshness": {"max_day": freshness.get("max_day")},
        "overall": {
            "report_date": report_date,
            "compare_date": compare_date,
            "operating_profit": current.get("operating_profit"),
            "previous_operating_profit": previous.get("operating_profit"),
            "delta_day": (_to_decimal(current.get("operating_profit")) - _to_decimal(previous.get("operating_profit"))) if _to_decimal(current.get("operating_profit")) is not None and _to_decimal(previous.get("operating_profit")) is not None else None,
            "operating_profit_per_unit": current.get("operating_profit_per_unit"),
            "previous_operating_profit_per_unit": previous.get("operating_profit_per_unit"),
            "profit_per_unit_delta_day": (_to_decimal(current.get("operating_profit_per_unit")) - _to_decimal(previous.get("operating_profit_per_unit"))) if _to_decimal(current.get("operating_profit_per_unit")) is not None and _to_decimal(previous.get("operating_profit_per_unit")) is not None else None,
            "organic_sales": current.get("organic_sales"),
        },
        "weekly_trend": {
            "current_window": {"from": trend_current_from, "to": trend_current_to},
            "previous_window": {"from": trend_previous_from, "to": trend_previous_to},
            "current_operating_profit": trend_by_bucket.get("current", {}).get("operating_profit"),
            "previous_operating_profit": trend_by_bucket.get("previous", {}).get("operating_profit"),
            "current_profit_per_unit": trend_by_bucket.get("current", {}).get("operating_profit_per_unit"),
            "previous_profit_per_unit": trend_by_bucket.get("previous", {}).get("operating_profit_per_unit"),
        },
        "top_positive_contributors": positive[:top_n],
        "top_negative_contributors": negative[:top_n],
        "by_article": enriched_articles[:top_n],
        "limitations": [OPERATING_PROFIT_SEMANTICS_NOTE],
    }


def fetch_pricing_spp_block(
    session: Session,
    *,
    report_date: date,
    compare_date: date,
    trend_current_from: date,
    top_n: int,
    query_counter: dict[str, Any],
) -> dict[str, Any]:
    item_rows = _execute_rows(
        session,
        text(
            """
            with mart_day as (
                select report_date, nm_id, supplier_article, title, subject, brand, order_sum
                from mart_total_report
                where report_date = :report_date
            ),
            current_site as (
                select snapshot_date, nm_id, buyer_visible_price, fetch_status, availability_status
                from fact_wb_site_price_snapshot
                where snapshot_date = :report_date
            ),
            previous_site as (
                select snapshot_date, nm_id, buyer_visible_price
                from fact_wb_site_price_snapshot
                where snapshot_date = :compare_date
            ),
            current_seller as (
                select snapshot_date, nm_id,
                       min(seller_price) as seller_price_min,
                       max(seller_price) as seller_price_max,
                       min(discount) as discount_min,
                       max(discount) as discount_max,
                       count(distinct chrt_id) as variants_count
                from fact_wb_seller_price_snapshot
                where snapshot_date = :report_date
                group by snapshot_date, nm_id
            ),
            previous_seller as (
                select snapshot_date, nm_id,
                       min(seller_price) as seller_price_min,
                       max(seller_price) as seller_price_max,
                       min(discount) as discount_min,
                       max(discount) as discount_max,
                       count(distinct chrt_id) as variants_count
                from fact_wb_seller_price_snapshot
                where snapshot_date = :compare_date
                group by snapshot_date, nm_id
            )
            select
                m.nm_id,
                m.supplier_article,
                m.title,
                m.subject,
                m.brand,
                m.order_sum,
                cs.buyer_visible_price,
                ps.buyer_visible_price as previous_buyer_visible_price,
                cs.fetch_status,
                cs.availability_status,
                case when csel.seller_price_min = csel.seller_price_max then csel.seller_price_min end as seller_price,
                case when psel.seller_price_min = psel.seller_price_max then psel.seller_price_min end as previous_seller_price,
                case when csel.discount_min = csel.discount_max then csel.discount_min end as discount_pct,
                case when psel.discount_min = psel.discount_max then psel.discount_min end as previous_discount_pct,
                case when csel.seller_price_min = csel.seller_price_max then csel.variants_count end as seller_variants_count,
                case when csel.seller_price_min = csel.seller_price_max and cs.buyer_visible_price is not null then csel.seller_price_min - cs.buyer_visible_price end as spp_rub,
                case when psel.seller_price_min = psel.seller_price_max and ps.buyer_visible_price is not null then psel.seller_price_min - ps.buyer_visible_price end as previous_spp_rub,
                case when csel.seller_price_min = csel.seller_price_max and cs.buyer_visible_price is not null and csel.seller_price_min <> 0 then (csel.seller_price_min - cs.buyer_visible_price) / nullif(csel.seller_price_min, 0) * 100 end as spp_pct,
                case when psel.seller_price_min = psel.seller_price_max and ps.buyer_visible_price is not null and psel.seller_price_min <> 0 then (psel.seller_price_min - ps.buyer_visible_price) / nullif(psel.seller_price_min, 0) * 100 end as previous_spp_pct
            from mart_day m
            left join current_site cs on cs.nm_id = m.nm_id
            left join previous_site ps on ps.nm_id = m.nm_id
            left join current_seller csel on csel.nm_id = m.nm_id
            left join previous_seller psel on psel.nm_id = m.nm_id
            where cs.buyer_visible_price is not null or ps.buyer_visible_price is not null or csel.seller_price_min is not null or psel.seller_price_min is not null
            order by m.order_sum desc nulls last, m.nm_id asc
            """
        ),
        {"report_date": report_date, "compare_date": compare_date},
        query_counter,
        "pricing_spp_items",
    )

    enriched_rows = []
    for row in item_rows:
        current_price = _to_decimal(row.get("buyer_visible_price"))
        previous_price = _to_decimal(row.get("previous_buyer_visible_price"))
        current_spp = _to_decimal(row.get("spp_rub"))
        previous_spp = _to_decimal(row.get("previous_spp_rub"))
        enriched_rows.append({
            **row,
            "price_delta_day": (current_price - previous_price) if current_price is not None and previous_price is not None else None,
            "spp_delta_day": (current_spp - previous_spp) if current_spp is not None and previous_spp is not None else None,
        })
    top_price_changes = sorted(
        [row for row in enriched_rows if row.get("price_delta_day") is not None],
        key=lambda item: abs(_to_decimal(item.get("price_delta_day")) or Decimal("0")),
        reverse=True,
    )[:top_n]
    top_spp_changes = sorted(
        [row for row in enriched_rows if row.get("spp_delta_day") is not None],
        key=lambda item: abs(_to_decimal(item.get("spp_delta_day")) or Decimal("0")),
        reverse=True,
    )[:top_n]

    trend_nm_ids = sorted({int(row["nm_id"]) for row in top_price_changes + top_spp_changes if row.get("nm_id") is not None})
    trend_by_nm: dict[int, list[dict[str, Any]]] = {}
    if trend_nm_ids:
        history_sql = text(
            """
            with seller_day as (
                select snapshot_date, nm_id,
                       min(seller_price) as seller_price_min,
                       max(seller_price) as seller_price_max
                from fact_wb_seller_price_snapshot
                where snapshot_date >= :trend_current_from and snapshot_date <= :report_date and nm_id in :nm_ids
                group by snapshot_date, nm_id
            )
            select
                s.snapshot_date,
                s.nm_id,
                s.buyer_visible_price,
                case when sd.seller_price_min = sd.seller_price_max then sd.seller_price_min end as seller_price,
                case when sd.seller_price_min = sd.seller_price_max and s.buyer_visible_price is not null then sd.seller_price_min - s.buyer_visible_price end as spp_rub,
                case when sd.seller_price_min = sd.seller_price_max and s.buyer_visible_price is not null and sd.seller_price_min <> 0 then (sd.seller_price_min - s.buyer_visible_price) / nullif(sd.seller_price_min, 0) * 100 end as spp_pct
            from fact_wb_site_price_snapshot s
            left join seller_day sd on sd.snapshot_date = s.snapshot_date and sd.nm_id = s.nm_id
            where s.snapshot_date >= :trend_current_from and s.snapshot_date <= :report_date and s.nm_id in :nm_ids
            order by s.nm_id asc, s.snapshot_date asc
            """
        ).bindparams(bindparam("nm_ids", expanding=True))
        history_rows = _execute_rows(
            session,
            history_sql,
            {"trend_current_from": trend_current_from, "report_date": report_date, "nm_ids": trend_nm_ids},
            query_counter,
            "pricing_spp_history",
        )
        for row in history_rows:
            trend_by_nm.setdefault(int(row["nm_id"]), []).append({
                "date": row.get("snapshot_date"),
                "buyer_visible_price": row.get("buyer_visible_price"),
                "seller_price": row.get("seller_price"),
                "spp_rub": row.get("spp_rub"),
                "spp_pct": row.get("spp_pct"),
            })

    for row in top_price_changes + top_spp_changes:
        if row.get("nm_id") is not None:
            row["trend_7d"] = trend_by_nm.get(int(row["nm_id"]), [])

    return {
        "status": "OK" if enriched_rows else "MISSING",
        "source_tables": ["fact_wb_site_price_snapshot", "fact_wb_seller_price_snapshot"],
        "semantics": SELLER_PRICE_SPP_NOTE,
        "report_date": report_date,
        "compare_date": compare_date,
        "items_with_price": len([row for row in enriched_rows if row.get("buyer_visible_price") is not None]),
        "items_with_spp": len([row for row in enriched_rows if row.get("spp_rub") is not None]),
        "top_price_changes": top_price_changes,
        "top_spp_changes": top_spp_changes,
        "limitations": [SELLER_PRICE_SPP_NOTE],
    }


def fetch_competitor_block(
    session: Session,
    *,
    report_date: date,
    top_n: int,
    query_counter: dict[str, Any],
) -> dict[str, Any]:
    snapshot_meta = _execute_one(
        session,
        text(
            """
            select
                max(snapshot_date) as latest_snapshot_date,
                count(*) filter (where snapshot_date = :report_date) as report_date_rows,
                count(distinct competitor_group_key) filter (where snapshot_date = :report_date) as report_date_groups
            from fact_competitor_wb_site_price_snapshot
            """
        ),
        {"report_date": report_date},
        query_counter,
        "competitor_snapshot_meta",
    )
    latest_snapshot_date = snapshot_meta.get("latest_snapshot_date")
    report_date_rows = int(snapshot_meta.get("report_date_rows") or 0)
    if latest_snapshot_date is None:
        return {
            "status": "MISSING",
            "mapping_type": COMPETITOR_MAPPING_NOTE,
            "report_date": report_date,
            "snapshot_date": None,
            "comparison_mode": "NO_SNAPSHOT",
            "items": [],
            "limitations": ["Competitor snapshot table has no rows."],
        }

    snapshot_date = report_date if report_date_rows > 0 else latest_snapshot_date
    comparison_mode = "EXACT_REPORT_DATE" if report_date_rows > 0 else "LATEST_AVAILABLE_SNAPSHOT"
    item_rows = _execute_rows(
        session,
        text(
            """
            with competitor_item as (
                select
                    competitor_group_key,
                    competitor_group_name,
                    competitor_nm_id,
                    min(buyer_visible_price) as competitor_price
                from fact_competitor_wb_site_price_snapshot
                where snapshot_date = :snapshot_date and fetch_status = 'success' and buyer_visible_price is not null
                group by competitor_group_key, competitor_group_name, competitor_nm_id
            ),
            competitor_group_stats as (
                select
                    competitor_group_key,
                    min(competitor_group_name) as competitor_group_name,
                    count(*) as competitor_count,
                    min(competitor_price) as min_competitor_price,
                    avg(competitor_price) as avg_competitor_price,
                    percentile_cont(0.5) within group (order by competitor_price) as median_competitor_price
                from competitor_item
                group by competitor_group_key
            ),
            our_products as (
                select
                    m.nm_id,
                    m.supplier_article,
                    m.title,
                    m.subject,
                    m.brand,
                    m.order_sum,
                    sp.query_group
                from mart_total_report m
                join settings_products sp on sp.nm_id = m.nm_id and sp.active is true
                where m.report_date = :report_date and sp.query_group is not null and btrim(sp.query_group) <> ''
            ),
            our_prices as (
                select nm_id, buyer_visible_price
                from fact_wb_site_price_snapshot
                where snapshot_date = :snapshot_date
            )
            select
                o.nm_id,
                o.supplier_article,
                o.title,
                o.subject,
                o.brand,
                o.order_sum,
                o.query_group,
                p.buyer_visible_price as our_buyer_visible_price,
                c.competitor_group_name,
                c.competitor_count,
                c.min_competitor_price,
                c.avg_competitor_price,
                c.median_competitor_price
            from our_products o
            join competitor_group_stats c on c.competitor_group_key = o.query_group
            left join our_prices p on p.nm_id = o.nm_id
            order by o.order_sum desc nulls last, o.nm_id asc
            limit :top_n
            """
        ),
        {"snapshot_date": snapshot_date, "report_date": report_date, "top_n": top_n},
        query_counter,
        "competitor_items",
    )
    for row in item_rows:
        our_price = _to_decimal(row.get("our_buyer_visible_price"))
        min_price = _to_decimal(row.get("min_competitor_price"))
        avg_price = _to_decimal(row.get("avg_competitor_price"))
        median_price = _to_decimal(row.get("median_competitor_price"))
        row["delta_vs_min_competitor_price"] = (our_price - min_price) if our_price is not None and min_price is not None else None
        row["delta_vs_avg_competitor_price"] = (our_price - avg_price) if our_price is not None and avg_price is not None else None
        row["delta_vs_median_competitor_price"] = (our_price - median_price) if our_price is not None and median_price is not None else None

    return {
        "status": "OK" if item_rows else "MISSING",
        "report_date": report_date,
        "snapshot_date": snapshot_date,
        "latest_snapshot_date": latest_snapshot_date,
        "comparison_mode": comparison_mode,
        "mapping_type": COMPETITOR_MAPPING_NOTE,
        "freshness_status": "OK" if comparison_mode == "EXACT_REPORT_DATE" else "PARTIAL",
        "items": item_rows,
        "limitations": [
            "Competitor data is grouped by competitor_group_key rather than direct our_nm_id + competitor_nm_id history.",
            "If the report date has no exact competitor snapshot, MCP exposes only the latest available snapshot and labels it explicitly.",
        ],
    }


def build_additional_data_candidates(*, database_audit_block: dict[str, Any]) -> list[dict[str, Any]]:
    tables = database_audit_block.get("tables", {})
    alert_meta = tables.get("fact_wb_site_price_alert", {})
    localization_meta = tables.get("fact_localization_region_day", {})
    return [
        {
            "candidate_key": "wb_site_price_alerts",
            "table": "fact_wb_site_price_alert",
            "grain": "snapshot_date + nm_id",
            "date_range": _date_range(alert_meta),
            "row_count": alert_meta.get("rows"),
            "management_value": "high",
            "quality_status": "OK",
            "join_keys": ["snapshot_date", "nm_id"],
            "interpretation_risk": "low",
            "note": "Useful for surfacing abrupt visible-price changes without reconstructing raw price history in the prompt.",
        },
        {
            "candidate_key": "localization_region_day",
            "table": "fact_localization_region_day",
            "grain": "period_start + period_end + date + nm_id + region",
            "date_range": _date_range(localization_meta),
            "row_count": localization_meta.get("rows"),
            "management_value": "medium",
            "quality_status": "PARTIAL",
            "join_keys": ["date", "nm_id"],
            "interpretation_risk": "medium",
            "note": "Useful for nonlocal-order and delivery-time diagnostics, but the regional grain is richer than the default daily summary.",
        },
    ]
