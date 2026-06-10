from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.funnel_loader import _to_date_or_none, _to_datetime_or_none, _to_decimal_or_none
from src.db.models import FactLocalizationRegionDay
from src.db.session import session_scope, upsert_rows
from src.pipelines.vbro_localization_partial_run import (
    DATE_FROM,
    DATE_TO,
    TEST_NM_IDS,
    VbroLocalizationPartialRun,
    _index_funnel_rows,
    _index_stock_rows,
)


FACT_LOCALIZATION_REGION_DAY_CONFLICT_COLUMNS = ("period_start", "period_end", "nm_id", "region")
SUPPORTED_NM_IDS = tuple(TEST_NM_IDS)


def _resolve_nm_ids(nm_ids: Sequence[int] | None = None) -> tuple[int, ...]:
    return tuple(nm_ids) if nm_ids else tuple(SUPPORTED_NM_IDS)


def build_fact_localization_region_day_db_row(
    row: Mapping[str, Any],
    period_start: date,
    period_end: date,
) -> dict[str, Any]:
    report_date = _to_date_or_none(row.get("date")) or period_end
    return {
        "period_start": period_start,
        "period_end": period_end,
        "date": report_date,
        "nm_id": row.get("nm_id") or None,
        "supplier_article": row.get("supplier_article") or None,
        "title": row.get("title") or None,
        "subject": row.get("subject") or None,
        "brand": row.get("brand") or None,
        "country": row.get("country") or None,
        "region": row.get("region") or None,
        "city": row.get("city") or None,
        "orders_total_qty": _to_decimal_or_none(row.get("orders_total_qty")),
        "orders_local_qty": _to_decimal_or_none(row.get("orders_local_qty")),
        "orders_nonlocal_qty": _to_decimal_or_none(row.get("orders_nonlocal_qty")),
        "orders_nonlocal_percent": _to_decimal_or_none(row.get("orders_nonlocal_percent")),
        "wb_stock_orders_local_qty": _to_decimal_or_none(row.get("wb_stock_orders_local_qty")),
        "wb_stock_orders_nonlocal_qty": _to_decimal_or_none(row.get("wb_stock_orders_nonlocal_qty")),
        "wb_stock_orders_nonlocal_percent": _to_decimal_or_none(row.get("wb_stock_orders_nonlocal_percent")),
        "mp_orders_local_qty": _to_decimal_or_none(row.get("mp_orders_local_qty")),
        "mp_orders_nonlocal_qty": _to_decimal_or_none(row.get("mp_orders_nonlocal_qty")),
        "mp_orders_nonlocal_percent": _to_decimal_or_none(row.get("mp_orders_nonlocal_percent")),
        "sale_item_qty": _to_decimal_or_none(row.get("sale_item_qty")),
        "sale_amount": _to_decimal_or_none(row.get("sale_amount")),
        "wb_stock_qty": _to_decimal_or_none(row.get("wb_stock_qty")),
        "mp_stock_qty": _to_decimal_or_none(row.get("mp_stock_qty")),
        "delivery_time": _to_decimal_or_none(row.get("delivery_time")),
        "local_orders_percent": _to_decimal_or_none(row.get("local_orders_percent")),
        "nonlocal_orders_percent": _to_decimal_or_none(row.get("nonlocal_orders_percent")),
        "data_status": row.get("data_status") or "PARTIAL",
        "source_status": "PARTIAL",
        "loaded_at": _to_datetime_or_none(row.get("loaded_at")),
    }


def prepare_fact_localization_region_day_upsert_rows(
    rows: Sequence[Mapping[str, Any]],
    period_start: date,
    period_end: date,
) -> list[dict[str, Any]]:
    prepared: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        mapped = build_fact_localization_region_day_db_row(row, period_start, period_end)
        key = tuple(mapped.get(column_name) for column_name in FACT_LOCALIZATION_REGION_DAY_CONFLICT_COLUMNS)
        if (
            mapped["period_start"] is None
            or mapped["period_end"] is None
            or mapped["nm_id"] in (None, "")
            or mapped["region"] in (None, "")
        ):
            continue
        prepared[key] = mapped
    return list(prepared.values())


def collect_localization_rows(
    runner: VbroLocalizationPartialRun,
    period_start: date,
    period_end: date,
    nm_ids: Sequence[int] | None = None,
    reference_index: Mapping[str, dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    runner.nm_ids = list(resolved_nm_ids)
    if reference_index is None:
        funnel_index = _index_funnel_rows()
        stock_index = _index_stock_rows()
    else:
        funnel_index = {
            (period_end.isoformat(), nm_id): values
            for nm_id, values in reference_index.items()
        }
        stock_index = dict(reference_index)
    region_rows = runner._fetch_region_sales()
    fact_rows, _ = runner._build_localization_rows(region_rows, funnel_index, stock_index)
    fact_rows = [row for row in fact_rows if row.get("nm_id") in resolved_nm_ids]
    return fact_rows, {
        "rows_fetched": len(fact_rows),
        "source_status": "PARTIAL",
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
    }


def upsert_fact_localization_region_day(
    session: Session,
    rows: Sequence[Mapping[str, Any]],
    period_start: date,
    period_end: date,
) -> int:
    prepared_rows = prepare_fact_localization_region_day_upsert_rows(rows, period_start, period_end)
    upsert_rows(
        session=session,
        model=FactLocalizationRegionDay,
        rows=prepared_rows,
        conflict_columns=FACT_LOCALIZATION_REGION_DAY_CONFLICT_COLUMNS,
    )
    return len(prepared_rows)


def count_fact_localization_region_day_rows(session: Session, period_start: date, period_end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactLocalizationRegionDay)
        .where(
            FactLocalizationRegionDay.period_start == period_start,
            FactLocalizationRegionDay.period_end == period_end,
            FactLocalizationRegionDay.nm_id.in_(list(resolved_nm_ids)),
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_fact_localization_region_day_duplicates(session: Session, period_start: date, period_end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    dup_stmt = (
        select(
            FactLocalizationRegionDay.period_start,
            FactLocalizationRegionDay.period_end,
            FactLocalizationRegionDay.nm_id,
            FactLocalizationRegionDay.region,
        )
        .where(
            FactLocalizationRegionDay.period_start == period_start,
            FactLocalizationRegionDay.period_end == period_end,
            FactLocalizationRegionDay.nm_id.in_(list(resolved_nm_ids)),
        )
        .group_by(
            FactLocalizationRegionDay.period_start,
            FactLocalizationRegionDay.period_end,
            FactLocalizationRegionDay.nm_id,
            FactLocalizationRegionDay.region,
        )
        .having(func.count() > 1)
    )
    return len(session.execute(dup_stmt).all())


def count_nonnull_regional_stock_rows(session: Session, period_start: date, period_end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactLocalizationRegionDay)
        .where(
            FactLocalizationRegionDay.period_start == period_start,
            FactLocalizationRegionDay.period_end == period_end,
            FactLocalizationRegionDay.nm_id.in_(list(resolved_nm_ids)),
            (
                FactLocalizationRegionDay.wb_stock_qty.is_not(None)
                | FactLocalizationRegionDay.mp_stock_qty.is_not(None)
            ),
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_nonnull_local_nonlocal_rows(session: Session, period_start: date, period_end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactLocalizationRegionDay)
        .where(
            FactLocalizationRegionDay.period_start == period_start,
            FactLocalizationRegionDay.period_end == period_end,
            FactLocalizationRegionDay.nm_id.in_(list(resolved_nm_ids)),
            (
                FactLocalizationRegionDay.orders_local_qty.is_not(None)
                | FactLocalizationRegionDay.orders_nonlocal_qty.is_not(None)
                | FactLocalizationRegionDay.orders_nonlocal_percent.is_not(None)
                | FactLocalizationRegionDay.wb_stock_orders_local_qty.is_not(None)
                | FactLocalizationRegionDay.wb_stock_orders_nonlocal_qty.is_not(None)
                | FactLocalizationRegionDay.wb_stock_orders_nonlocal_percent.is_not(None)
                | FactLocalizationRegionDay.mp_orders_local_qty.is_not(None)
                | FactLocalizationRegionDay.mp_orders_nonlocal_qty.is_not(None)
                | FactLocalizationRegionDay.mp_orders_nonlocal_percent.is_not(None)
                | FactLocalizationRegionDay.local_orders_percent.is_not(None)
                | FactLocalizationRegionDay.nonlocal_orders_percent.is_not(None)
            ),
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_nonnull_delivery_time_rows(session: Session, period_start: date, period_end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactLocalizationRegionDay)
        .where(
            FactLocalizationRegionDay.period_start == period_start,
            FactLocalizationRegionDay.period_end == period_end,
            FactLocalizationRegionDay.nm_id.in_(list(resolved_nm_ids)),
            FactLocalizationRegionDay.delivery_time.is_not(None),
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_partial_source_status_rows(session: Session, period_start: date, period_end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactLocalizationRegionDay)
        .where(
            FactLocalizationRegionDay.period_start == period_start,
            FactLocalizationRegionDay.period_end == period_end,
            FactLocalizationRegionDay.nm_id.in_(list(resolved_nm_ids)),
            FactLocalizationRegionDay.source_status == "PARTIAL",
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_mock_like_rows(session: Session, period_start: date, period_end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactLocalizationRegionDay)
        .where(
            FactLocalizationRegionDay.period_start == period_start,
            FactLocalizationRegionDay.period_end == period_end,
            FactLocalizationRegionDay.nm_id.in_(list(resolved_nm_ids)),
            (
                FactLocalizationRegionDay.supplier_article.in_(["DRY_RUN"])
                | FactLocalizationRegionDay.brand.in_(["TestBrand"])
                | FactLocalizationRegionDay.title.in_(["Товар тестовый"])
                | FactLocalizationRegionDay.region.ilike("%mock%")
                | FactLocalizationRegionDay.region.ilike("%fake%")
            ),
        )
    )
    return int(session.execute(stmt).scalar_one())


def load_localization_to_db(
    period_start: date = DATE_FROM,
    period_end: date = DATE_TO,
    nm_ids: Sequence[int] | None = None,
    reference_index: Mapping[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    runner = VbroLocalizationPartialRun()
    fact_rows, metadata = collect_localization_rows(
        runner,
        period_start,
        period_end,
        nm_ids=resolved_nm_ids,
        reference_index=reference_index,
    )

    with session_scope() as session:
        upserted_rows = upsert_fact_localization_region_day(session, fact_rows, period_start, period_end)
        total_rows = count_fact_localization_region_day_rows(session, period_start, period_end, resolved_nm_ids)
        duplicate_keys = count_fact_localization_region_day_duplicates(session, period_start, period_end, resolved_nm_ids)
        nonnull_regional_stock_rows = count_nonnull_regional_stock_rows(session, period_start, period_end, resolved_nm_ids)
        nonnull_local_nonlocal_rows = count_nonnull_local_nonlocal_rows(session, period_start, period_end, resolved_nm_ids)
        nonnull_delivery_time_rows = count_nonnull_delivery_time_rows(session, period_start, period_end, resolved_nm_ids)
        partial_source_status_rows = count_partial_source_status_rows(session, period_start, period_end, resolved_nm_ids)
        mock_like_rows = count_mock_like_rows(session, period_start, period_end, resolved_nm_ids)

    return {
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "rows_fetched": metadata["rows_fetched"],
        "rows_upserted": upserted_rows,
        "rows_in_db": total_rows,
        "duplicate_keys": duplicate_keys,
        "nm_ids": list(resolved_nm_ids),
        "nonnull_regional_stock_rows": nonnull_regional_stock_rows,
        "nonnull_local_nonlocal_rows": nonnull_local_nonlocal_rows,
        "nonnull_delivery_time_rows": nonnull_delivery_time_rows,
        "partial_source_status_rows": partial_source_status_rows,
        "mock_like_rows": mock_like_rows,
    }
