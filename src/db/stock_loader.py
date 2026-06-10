from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.funnel_loader import _to_date_or_none, _to_datetime_or_none, _to_decimal_or_none
from src.db.models import FactStockSnapshot
from src.db.session import session_scope, upsert_rows
from src.pipelines.mvp_real_run import MvpRealRun, TEST_NM_IDS, _first_int, _list_from_payload


FACT_STOCK_SNAPSHOT_CONFLICT_COLUMNS = ("snapshot_date", "nm_id")
SUPPORTED_NM_IDS = tuple(TEST_NM_IDS)


def _resolve_nm_ids(nm_ids: Sequence[int] | None = None) -> tuple[int, ...]:
    return tuple(nm_ids) if nm_ids else tuple(SUPPORTED_NM_IDS)


def build_fact_stock_snapshot_db_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "snapshot_date": _to_date_or_none(row.get("snapshot_date")),
        "nm_id": _first_int(row, "nm_id", "nmId", "nmID"),
        "supplier_article": row.get("supplier_article") or None,
        "title": row.get("title") or None,
        "subject": row.get("subject") or None,
        "brand": row.get("brand") or None,
        "wb_stock_qty": _to_decimal_or_none(row.get("wb_stock_qty")),
        "mp_stock_qty": _to_decimal_or_none(row.get("mp_stock_qty")),
        "stock_total_qty": _to_decimal_or_none(row.get("stock_total_qty")),
        "stock_total_sum": _to_decimal_or_none(row.get("stock_total_sum")),
        "sale_rate": _to_decimal_or_none(row.get("saleRate")),
        "to_client_count": _to_decimal_or_none(row.get("toClientCount")),
        "from_client_count": _to_decimal_or_none(row.get("fromClientCount")),
        "availability": _to_decimal_or_none(row.get("availability")),
        "data_status": row.get("data_status") or None,
        "source_status": row.get("source_status") or None,
        "loaded_at": _to_datetime_or_none(row.get("loaded_at")),
    }


def prepare_fact_stock_snapshot_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: dict[tuple[date, int], dict[str, Any]] = {}
    for row in rows:
        mapped = build_fact_stock_snapshot_db_row(row)
        key = (mapped.get("snapshot_date"), mapped.get("nm_id"))
        if key[0] is None or key[1] is None:
            continue
        prepared[key] = mapped
    return list(prepared.values())


def collect_stock_rows(
    runner: MvpRealRun,
    snapshot_date: date,
    nm_ids: Sequence[int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    runner.nm_ids = list(resolved_nm_ids)
    stocks_status, stocks_payload, stocks_error = runner._fetch_stocks(snapshot_date)
    if stocks_status != "200":
        raise RuntimeError(f"Stocks request failed: {stocks_status} {stocks_error}")

    stocks_items = _list_from_payload(stocks_payload, ("data", "items"), ("items",))
    stock_rows: list[dict[str, Any]] = []
    for item in stocks_items:
        if not isinstance(item, dict):
            continue
        nm_id = _first_int(item, "nmID", "nmId")
        if nm_id is None or nm_id not in resolved_nm_ids:
            continue
        stock_rows.append(runner._build_stock_row(item))

    return stock_rows, {
        "status": stocks_status,
        "error": stocks_error,
        "rows_fetched": len(stock_rows),
        "snapshot_date": snapshot_date.isoformat(),
    }


def upsert_fact_stock_snapshot(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_fact_stock_snapshot_upsert_rows(rows)
    upsert_rows(
        session=session,
        model=FactStockSnapshot,
        rows=prepared_rows,
        conflict_columns=FACT_STOCK_SNAPSHOT_CONFLICT_COLUMNS,
    )
    return len(prepared_rows)


def count_fact_stock_snapshot_rows(session: Session, snapshot_date: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactStockSnapshot)
        .where(FactStockSnapshot.snapshot_date == snapshot_date, FactStockSnapshot.nm_id.in_(list(resolved_nm_ids)))
    )
    return int(session.execute(stmt).scalar_one())


def count_fact_stock_snapshot_duplicates(session: Session, snapshot_date: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    dup_stmt = (
        select(FactStockSnapshot.snapshot_date, FactStockSnapshot.nm_id)
        .where(FactStockSnapshot.snapshot_date == snapshot_date, FactStockSnapshot.nm_id.in_(list(resolved_nm_ids)))
        .group_by(FactStockSnapshot.snapshot_date, FactStockSnapshot.nm_id)
        .having(func.count() > 1)
    )
    return len(session.execute(dup_stmt).all())


def count_null_mp_stock_rows(session: Session, snapshot_date: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactStockSnapshot)
        .where(
            FactStockSnapshot.snapshot_date == snapshot_date,
            FactStockSnapshot.nm_id.in_(list(resolved_nm_ids)),
            FactStockSnapshot.mp_stock_qty.is_(None),
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_mock_like_rows(session: Session, snapshot_date: date, nm_ids: Sequence[int] | None = None) -> int:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    stmt = (
        select(func.count())
        .select_from(FactStockSnapshot)
        .where(
            FactStockSnapshot.snapshot_date == snapshot_date,
            FactStockSnapshot.nm_id.in_(list(resolved_nm_ids)),
            (
                FactStockSnapshot.supplier_article.in_(["DRY_RUN"])
                | FactStockSnapshot.brand.in_(["TestBrand"])
                | FactStockSnapshot.title.in_(["Товар тестовый"])
            ),
        )
    )
    return int(session.execute(stmt).scalar_one())


def load_stocks_to_db(snapshot_date: date, nm_ids: Sequence[int] | None = None) -> dict[str, Any]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    runner = MvpRealRun()
    runner.date_to = snapshot_date
    stock_rows, metadata = collect_stock_rows(runner, snapshot_date, nm_ids=resolved_nm_ids)

    with session_scope() as session:
        upserted_rows = upsert_fact_stock_snapshot(session, stock_rows)
        total_rows = count_fact_stock_snapshot_rows(session, snapshot_date, resolved_nm_ids)
        duplicate_keys = count_fact_stock_snapshot_duplicates(session, snapshot_date, resolved_nm_ids)
        null_mp_stock_rows = count_null_mp_stock_rows(session, snapshot_date, resolved_nm_ids)
        mock_like_rows = count_mock_like_rows(session, snapshot_date, resolved_nm_ids)

    return {
        "snapshot_date": snapshot_date.isoformat(),
        "nm_ids": list(resolved_nm_ids),
        "rows_fetched": metadata["rows_fetched"],
        "rows_upserted": upserted_rows,
        "rows_in_db": total_rows,
        "duplicate_keys": duplicate_keys,
        "null_mp_stock_rows": null_mp_stock_rows,
        "mock_like_rows": mock_like_rows,
        "status": metadata["status"],
    }
