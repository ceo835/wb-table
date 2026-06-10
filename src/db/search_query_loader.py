from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.funnel_loader import _to_date_or_none, _to_datetime_or_none, _to_decimal_or_none
from src.db.models import FactSearchQueryMetric
from src.db.session import session_scope, upsert_rows
from src.pipelines.mvp_real_run import (
    DATA_DIR,
    MvpRealRun,
    TEST_NM_IDS,
    _build_reference_index,
    _to_int,
)


FACT_SEARCH_QUERY_METRIC_CONFLICT_COLUMNS = ("period_start", "period_end", "nm_id", "search_query")
SUPPORTED_NM_IDS = tuple(TEST_NM_IDS)


def _resolve_nm_ids(nm_ids: Sequence[int] | None = None) -> tuple[int, ...]:
    return tuple(nm_ids) if nm_ids else tuple(SUPPORTED_NM_IDS)


def _json_safe_number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _read_processed_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def build_fact_search_query_metric_db_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "period_start": _to_date_or_none(row.get("period_start")),
        "period_end": _to_date_or_none(row.get("period_end")),
        "date": _to_date_or_none(row.get("date")),
        "nm_id": _to_int(row.get("nm_id")),
        "supplier_article": row.get("supplier_article") or None,
        "title": row.get("title") or None,
        "subject": row.get("subject") or None,
        "brand": row.get("brand") or None,
        "card_rating": _to_decimal_or_none(row.get("card_rating")),
        "reviews_rating": _to_decimal_or_none(row.get("reviews_rating")),
        "search_query": row.get("search_query") or None,
        "query_count": _to_decimal_or_none(row.get("query_count")),
        "query_count_prev": _to_decimal_or_none(row.get("query_count_prev")),
        "visibility": _to_decimal_or_none(row.get("visibility")),
        "visibility_prev": _to_decimal_or_none(row.get("visibility_prev")),
        "avg_position": _to_decimal_or_none(row.get("avg_position")),
        "avg_position_prev": _to_decimal_or_none(row.get("avg_position_prev")),
        "median_position": _to_decimal_or_none(row.get("median_position")),
        "median_position_prev": _to_decimal_or_none(row.get("median_position_prev")),
        "search_clicks": _to_decimal_or_none(row.get("search_clicks")),
        "search_clicks_prev": _to_decimal_or_none(row.get("search_clicks_prev")),
        "search_clicks_competitor_percentile": _to_decimal_or_none(row.get("search_clicks_competitor_percentile")),
        "search_cart": _to_decimal_or_none(row.get("search_cart")),
        "search_cart_prev": _to_decimal_or_none(row.get("search_cart_prev")),
        "search_cart_competitor_percentile": _to_decimal_or_none(row.get("search_cart_competitor_percentile")),
        "cart_conversion": _to_decimal_or_none(row.get("cart_conversion")),
        "cart_conversion_prev": _to_decimal_or_none(row.get("cart_conversion_prev")),
        "cart_conversion_competitor_percentile": _to_decimal_or_none(row.get("cart_conversion_competitor_percentile")),
        "search_orders": _to_decimal_or_none(row.get("search_orders")),
        "search_orders_prev": _to_decimal_or_none(row.get("search_orders_prev")),
        "search_orders_competitor_percentile": _to_decimal_or_none(row.get("search_orders_competitor_percentile")),
        "order_conversion": _to_decimal_or_none(row.get("order_conversion")),
        "order_conversion_prev": _to_decimal_or_none(row.get("order_conversion_prev")),
        "order_conversion_competitor_percentile": _to_decimal_or_none(row.get("order_conversion_competitor_percentile")),
        "min_discount_price": _to_decimal_or_none(row.get("min_discount_price")),
        "max_discount_price": _to_decimal_or_none(row.get("max_discount_price")),
        "competitor_metrics_json": None,
        "data_status": row.get("data_status") or None,
        "source_status": row.get("source_status") or None,
        "loaded_at": _to_datetime_or_none(row.get("loaded_at")),
    }


def prepare_fact_search_query_metric_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        mapped = build_fact_search_query_metric_db_row(row)
        key = tuple(mapped.get(column_name) for column_name in FACT_SEARCH_QUERY_METRIC_CONFLICT_COLUMNS)
        if (
            mapped["period_start"] is None
            or mapped["period_end"] is None
            or mapped["nm_id"] in (None, "")
            or mapped["search_query"] in (None, "")
        ):
            continue
        prepared[key] = mapped
    return list(prepared.values())


def collect_search_query_rows(
    runner: MvpRealRun,
    start: date,
    end: date,
    nm_ids: Sequence[int] | None = None,
    reference_index: Mapping[int, dict[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    runner.nm_ids = list(resolved_nm_ids)
    if reference_index is None:
        funnel_rows = _read_processed_csv_rows(DATA_DIR / "fact_funnel_day.csv")
        stock_rows = _read_processed_csv_rows(DATA_DIR / "fact_stock_snapshot.csv")
        reference_index = _build_reference_index(funnel_rows, stock_rows)

    current_status, current_payload, current_error, current_pagination = runner._fetch_search_texts_paginated(end)
    prev_status, prev_payload, prev_error, prev_pagination = runner._fetch_search_texts_paginated(start)
    if current_status != "200":
        raise RuntimeError(f"Search texts current request failed: {current_status} {current_error}")
    if prev_status != "200":
        raise RuntimeError(f"Search texts previous request failed: {prev_status} {prev_error}")

    current_rows = runner._build_search_rows(end, current_payload, prev_payload, reference_index)
    prev_rows = runner._build_search_rows(start, prev_payload, None, reference_index)
    search_rows = [
        row for row in sorted(current_rows + prev_rows, key=lambda item: (item.get("date", ""), item.get("nm_id", ""), item.get("search_query", "")))
        if _to_int(row.get("nm_id")) in resolved_nm_ids
    ]
    return search_rows, {
        "current_status": current_status,
        "prev_status": prev_status,
        "rows_fetched": len(search_rows),
        "current_pages_loaded": int(current_pagination.get("pages_loaded", 0) or 0),
        "prev_pages_loaded": int(prev_pagination.get("pages_loaded", 0) or 0),
        "current_page_logs": list(current_pagination.get("page_logs", [])),
        "prev_page_logs": list(prev_pagination.get("page_logs", [])),
        "current_http_error_counts": dict(current_pagination.get("http_error_counts", {})),
        "prev_http_error_counts": dict(prev_pagination.get("http_error_counts", {})),
        "current_failed_pages": list(current_pagination.get("failed_pages", [])),
        "prev_failed_pages": list(prev_pagination.get("failed_pages", [])),
        "current_pagination_supported": current_pagination.get("pagination_supported"),
        "prev_pagination_supported": prev_pagination.get("pagination_supported"),
    }


def upsert_fact_search_query_metric(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_fact_search_query_metric_upsert_rows(rows)
    upsert_rows(
        session=session,
        model=FactSearchQueryMetric,
        rows=prepared_rows,
        conflict_columns=FACT_SEARCH_QUERY_METRIC_CONFLICT_COLUMNS,
        batch_size=200,
    )
    return len(prepared_rows)


def count_fact_search_query_metric_rows(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactSearchQueryMetric)
        .where(
            FactSearchQueryMetric.period_start >= start,
            FactSearchQueryMetric.period_end <= end,
            FactSearchQueryMetric.nm_id.in_(list(resolved_nm_ids)),
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_fact_search_query_metric_duplicates(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    dup_stmt = (
        select(
            FactSearchQueryMetric.period_start,
            FactSearchQueryMetric.period_end,
            FactSearchQueryMetric.nm_id,
            FactSearchQueryMetric.search_query,
        )
        .where(
            FactSearchQueryMetric.period_start >= start,
            FactSearchQueryMetric.period_end <= end,
            FactSearchQueryMetric.nm_id.in_(list(resolved_nm_ids)),
        )
        .group_by(
            FactSearchQueryMetric.period_start,
            FactSearchQueryMetric.period_end,
            FactSearchQueryMetric.nm_id,
            FactSearchQueryMetric.search_query,
        )
        .having(func.count() > 1)
    )
    return len(session.execute(dup_stmt).all())


def count_null_competitor_percentile_rows(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactSearchQueryMetric)
        .where(
            FactSearchQueryMetric.period_start >= start,
            FactSearchQueryMetric.period_end <= end,
            FactSearchQueryMetric.nm_id.in_(list(resolved_nm_ids)),
            FactSearchQueryMetric.search_clicks_competitor_percentile.is_(None),
            FactSearchQueryMetric.search_cart_competitor_percentile.is_(None),
            FactSearchQueryMetric.cart_conversion_competitor_percentile.is_(None),
            FactSearchQueryMetric.search_orders_competitor_percentile.is_(None),
            FactSearchQueryMetric.order_conversion_competitor_percentile.is_(None),
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_nonnull_date_rows(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactSearchQueryMetric)
        .where(
            FactSearchQueryMetric.period_start >= start,
            FactSearchQueryMetric.period_end <= end,
            FactSearchQueryMetric.nm_id.in_(list(resolved_nm_ids)),
            FactSearchQueryMetric.date.is_not(None),
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_period_alignment_issues(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactSearchQueryMetric)
        .where(
            FactSearchQueryMetric.period_start >= start,
            FactSearchQueryMetric.period_end <= end,
            FactSearchQueryMetric.nm_id.in_(list(resolved_nm_ids)),
            (
                FactSearchQueryMetric.date.is_(None)
                | (FactSearchQueryMetric.date != FactSearchQueryMetric.period_start)
                | (FactSearchQueryMetric.date != FactSearchQueryMetric.period_end)
            ),
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_null_metric_rows(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> dict[str, int]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    def _count(column) -> int:
        stmt = (
            select(func.count())
            .select_from(FactSearchQueryMetric)
            .where(
                FactSearchQueryMetric.period_start >= start,
                FactSearchQueryMetric.period_end <= end,
                FactSearchQueryMetric.nm_id.in_(list(resolved_nm_ids)),
                column.is_(None),
            )
        )
        return int(session.execute(stmt).scalar_one())

    return {
        "min_discount_price": _count(FactSearchQueryMetric.min_discount_price),
        "max_discount_price": _count(FactSearchQueryMetric.max_discount_price),
        "search_clicks": _count(FactSearchQueryMetric.search_clicks),
        "search_cart": _count(FactSearchQueryMetric.search_cart),
        "search_orders": _count(FactSearchQueryMetric.search_orders),
    }


def count_mock_like_rows(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactSearchQueryMetric)
        .where(
            FactSearchQueryMetric.period_start >= start,
            FactSearchQueryMetric.period_end <= end,
            FactSearchQueryMetric.nm_id.in_(list(resolved_nm_ids)),
            (
                FactSearchQueryMetric.supplier_article.in_(["DRY_RUN"])
                | FactSearchQueryMetric.brand.in_(["TestBrand"])
                | FactSearchQueryMetric.title.in_(["Товар тестовый"])
                | FactSearchQueryMetric.search_query.ilike("%mock%")
                | FactSearchQueryMetric.search_query.ilike("%fake%")
            ),
        )
    )
    return int(session.execute(stmt).scalar_one())


def load_search_queries_to_db(
    start: date,
    end: date,
    nm_ids: Sequence[int] | None = None,
    reference_index: Mapping[int, dict[str, str]] | None = None,
) -> dict[str, Any]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    runner = MvpRealRun()
    runner.date_from = start
    runner.date_to = end
    search_rows, metadata = collect_search_query_rows(
        runner,
        start,
        end,
        nm_ids=resolved_nm_ids,
        reference_index=reference_index,
    )

    with session_scope() as session:
        upserted_rows = upsert_fact_search_query_metric(session, search_rows)
        total_rows = count_fact_search_query_metric_rows(session, start, end, resolved_nm_ids)
        duplicate_keys = count_fact_search_query_metric_duplicates(session, start, end, resolved_nm_ids)
        null_competitor_rows = count_null_competitor_percentile_rows(session, start, end, resolved_nm_ids)
        nonnull_date_rows = count_nonnull_date_rows(session, start, end, resolved_nm_ids)
        period_alignment_issues = count_period_alignment_issues(session, start, end, resolved_nm_ids)
        null_metric_rows = count_null_metric_rows(session, start, end, resolved_nm_ids)
        mock_like_rows = count_mock_like_rows(session, start, end, resolved_nm_ids)

    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "nm_ids": list(resolved_nm_ids),
        "rows_fetched": metadata["rows_fetched"],
        "rows_upserted": upserted_rows,
        "rows_in_db": total_rows,
        "duplicate_keys": duplicate_keys,
        "null_competitor_percentile_rows": null_competitor_rows,
        "nonnull_date_rows": nonnull_date_rows,
        "period_alignment_issues": period_alignment_issues,
        "null_metric_rows": null_metric_rows,
        "mock_like_rows": mock_like_rows,
        "current_status": metadata["current_status"],
        "prev_status": metadata["prev_status"],
        "current_pages_loaded": metadata["current_pages_loaded"],
        "prev_pages_loaded": metadata["prev_pages_loaded"],
        "current_page_logs": metadata["current_page_logs"],
        "prev_page_logs": metadata["prev_page_logs"],
        "current_http_error_counts": metadata["current_http_error_counts"],
        "prev_http_error_counts": metadata["prev_http_error_counts"],
        "current_failed_pages": metadata["current_failed_pages"],
        "prev_failed_pages": metadata["prev_failed_pages"],
        "current_pagination_supported": metadata["current_pagination_supported"],
        "prev_pagination_supported": metadata["prev_pagination_supported"],
    }
