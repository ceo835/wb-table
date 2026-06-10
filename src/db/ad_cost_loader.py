from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.funnel_loader import _to_date_or_none, _to_datetime_or_none, _to_decimal_or_none
from src.db.models import FactAdCostDay, FactAdCostEvent
from src.db.session import session_scope, upsert_rows
from src.pipelines.mvp_real_run import MvpRealRun


FACT_AD_COST_EVENT_CONFLICT_COLUMNS = ("date", "advert_id", "writeoff_datetime", "document_number", "spend")
FACT_AD_COST_DAY_CONFLICT_COLUMNS = ("date", "advert_id", "nm_id")


def _resolve_nm_ids(nm_ids: Sequence[int] | None = None) -> tuple[int, ...] | None:
    return tuple(nm_ids) if nm_ids else None


def _json_safe_number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def build_fact_ad_cost_event_db_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "date": _to_date_or_none(row.get("date")),
        "advert_id": row.get("advertId"),
        "campaign_name": row.get("campaign_name") or None,
        "section_raw": row.get("section_raw") or None,
        "section_display": row.get("section_display") or None,
        "writeoff_datetime": _to_datetime_or_none(row.get("writeoff_datetime")),
        "writeoff_source": row.get("writeoff_source") or None,
        "spend": _to_decimal_or_none(row.get("spend")),
        "document_number": row.get("document_number") or None,
        "nm_id_from_section": row.get("nm_id_from_section") or None,
        "nm_id_from_campaign_name": row.get("nm_id_from_campaign_name") or None,
        "nm_id": row.get("nm_id") or None,
        "nm_id_parse_status": row.get("nm_id_parse_status") or None,
        "campaign_type": row.get("campaign_type") or None,
        "currency": row.get("currency") or None,
        "data_status": row.get("data_status") or None,
        "source_status": row.get("source_status") or None,
        "loaded_at": _to_datetime_or_none(row.get("loaded_at")),
    }


def prepare_fact_ad_cost_event_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        mapped = build_fact_ad_cost_event_db_row(row)
        key = tuple(mapped.get(column_name) for column_name in FACT_AD_COST_EVENT_CONFLICT_COLUMNS)
        if mapped["date"] is None or mapped["advert_id"] in (None, "") or mapped["writeoff_datetime"] is None or mapped["spend"] is None:
            continue
        prepared[key] = mapped
    return list(prepared.values())


def build_fact_ad_cost_day_db_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "date": _to_date_or_none(row.get("date")),
        "advert_id": row.get("advertId"),
        "campaign_name": row.get("campaign_name") or None,
        "nm_id": row.get("nm_id") or None,
        "total_spend": _to_decimal_or_none(row.get("total_spend")),
        "events_count": row.get("events_count") if row.get("events_count") not in ("", None) else None,
        "allocation_status": row.get("allocation_status") or None,
        "data_status": row.get("data_status") or None,
        "source_status": row.get("source_status") or None,
        "loaded_at": _to_datetime_or_none(row.get("loaded_at")),
    }


def prepare_fact_ad_cost_day_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        mapped = build_fact_ad_cost_day_db_row(row)
        key = tuple(mapped.get(column_name) for column_name in FACT_AD_COST_DAY_CONFLICT_COLUMNS)
        if mapped["date"] is None or mapped["advert_id"] in (None, ""):
            continue
        prepared[key] = mapped
    return list(prepared.values())


def collect_ad_cost_rows(
    runner: MvpRealRun,
    start: date,
    end: date,
    nm_ids: Sequence[int] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    ad_costs_status, ad_costs_payload, ad_costs_error = runner._fetch_ad_costs(start, end)
    if ad_costs_status != "200":
        raise RuntimeError(f"Ad costs request failed: {ad_costs_status} {ad_costs_error}")

    ad_cost_items = ad_costs_payload if isinstance(ad_costs_payload, list) else []
    ad_event_rows: list[dict[str, Any]] = []
    for item in ad_cost_items:
        if isinstance(item, dict):
            row = runner._build_ad_event_row(item)
            if resolved_nm_ids is not None and row.get("nm_id") not in resolved_nm_ids:
                continue
            ad_event_rows.append(row)
    ad_day_rows = runner._build_ad_day_rows(ad_event_rows)

    return ad_event_rows, ad_day_rows, {
        "status": ad_costs_status,
        "error": ad_costs_error,
        "event_rows_fetched": len(ad_event_rows),
        "day_rows_built": len(ad_day_rows),
    }


def upsert_fact_ad_cost_event(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_fact_ad_cost_event_upsert_rows(rows)
    upsert_rows(
        session=session,
        model=FactAdCostEvent,
        rows=prepared_rows,
        conflict_columns=FACT_AD_COST_EVENT_CONFLICT_COLUMNS,
    )
    return len(prepared_rows)


def upsert_fact_ad_cost_day(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_fact_ad_cost_day_upsert_rows(rows)
    upsert_rows(
        session=session,
        model=FactAdCostDay,
        rows=prepared_rows,
        conflict_columns=FACT_AD_COST_DAY_CONFLICT_COLUMNS,
    )
    return len(prepared_rows)


def count_fact_ad_cost_event_rows(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    stmt = select(func.count()).select_from(FactAdCostEvent).where(FactAdCostEvent.date >= start, FactAdCostEvent.date <= end)
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    if resolved_nm_ids is not None:
        stmt = stmt.where(FactAdCostEvent.nm_id.in_(list(resolved_nm_ids)))
    return int(session.execute(stmt).scalar_one())


def count_fact_ad_cost_day_rows(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    stmt = select(func.count()).select_from(FactAdCostDay).where(FactAdCostDay.date >= start, FactAdCostDay.date <= end)
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    if resolved_nm_ids is not None:
        stmt = stmt.where(FactAdCostDay.nm_id.in_(list(resolved_nm_ids)))
    return int(session.execute(stmt).scalar_one())


def count_fact_ad_cost_event_duplicates(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    dup_stmt = (
        select(
            FactAdCostEvent.date,
            FactAdCostEvent.advert_id,
            FactAdCostEvent.writeoff_datetime,
            FactAdCostEvent.document_number,
            FactAdCostEvent.spend,
        )
        .where(FactAdCostEvent.date >= start, FactAdCostEvent.date <= end)
        .group_by(
            FactAdCostEvent.date,
            FactAdCostEvent.advert_id,
            FactAdCostEvent.writeoff_datetime,
            FactAdCostEvent.document_number,
            FactAdCostEvent.spend,
        )
        .having(func.count() > 1)
    )
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    if resolved_nm_ids is not None:
        dup_stmt = dup_stmt.where(FactAdCostEvent.nm_id.in_(list(resolved_nm_ids)))
    return len(session.execute(dup_stmt).all())


def count_fact_ad_cost_day_duplicates(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    dup_stmt = (
        select(FactAdCostDay.date, FactAdCostDay.advert_id, FactAdCostDay.nm_id)
        .where(FactAdCostDay.date >= start, FactAdCostDay.date <= end)
        .group_by(FactAdCostDay.date, FactAdCostDay.advert_id, FactAdCostDay.nm_id)
        .having(func.count() > 1)
    )
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    if resolved_nm_ids is not None:
        dup_stmt = dup_stmt.where(FactAdCostDay.nm_id.in_(list(resolved_nm_ids)))
    return len(session.execute(dup_stmt).all())


def sum_event_spend(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> Decimal | None:
    stmt = select(func.sum(FactAdCostEvent.spend)).where(FactAdCostEvent.date >= start, FactAdCostEvent.date <= end)
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    if resolved_nm_ids is not None:
        stmt = stmt.where(FactAdCostEvent.nm_id.in_(list(resolved_nm_ids)))
    return session.execute(stmt).scalar_one()


def sum_day_spend(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> Decimal | None:
    stmt = select(func.sum(FactAdCostDay.total_spend)).where(FactAdCostDay.date >= start, FactAdCostDay.date <= end)
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    if resolved_nm_ids is not None:
        stmt = stmt.where(FactAdCostDay.nm_id.in_(list(resolved_nm_ids)))
    return session.execute(stmt).scalar_one()


def count_recognized_nm_ids(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(FactAdCostEvent)
        .where(
            FactAdCostEvent.date >= start,
            FactAdCostEvent.date <= end,
            FactAdCostEvent.nm_id.is_not(None),
            FactAdCostEvent.nm_id_parse_status.in_(["FROM_CAMPAIGN_NAME", "FROM_SECTION"]),
        )
    )
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    if resolved_nm_ids is not None:
        stmt = stmt.where(FactAdCostEvent.nm_id.in_(list(resolved_nm_ids)))
    return int(session.execute(stmt).scalar_one())


def count_not_found_nm_ids(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(FactAdCostEvent)
        .where(
            FactAdCostEvent.date >= start,
            FactAdCostEvent.date <= end,
            FactAdCostEvent.nm_id_parse_status == "NOT_FOUND",
        )
    )
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    if resolved_nm_ids is not None:
        stmt = stmt.where(FactAdCostEvent.nm_id.in_(list(resolved_nm_ids)))
    return int(session.execute(stmt).scalar_one())


def count_mock_like_rows(session: Session, start: date, end: date, nm_ids: Sequence[int] | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(FactAdCostEvent)
        .where(
            FactAdCostEvent.date >= start,
            FactAdCostEvent.date <= end,
            (
                FactAdCostEvent.campaign_name.ilike("%DRY_RUN%")
                | FactAdCostEvent.campaign_name.ilike("%mock%")
                | FactAdCostEvent.campaign_name.ilike("%fake%")
                | FactAdCostEvent.campaign_name.ilike("%TestBrand%")
            ),
        )
    )
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    if resolved_nm_ids is not None:
        stmt = stmt.where(FactAdCostEvent.nm_id.in_(list(resolved_nm_ids)))
    return int(session.execute(stmt).scalar_one())


def load_ad_costs_to_db(start: date, end: date, nm_ids: Sequence[int] | None = None) -> dict[str, Any]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    runner = MvpRealRun()
    runner.date_from = start
    runner.date_to = end
    ad_event_rows, ad_day_rows, metadata = collect_ad_cost_rows(runner, start, end, nm_ids=resolved_nm_ids)

    with session_scope() as session:
        event_rows_upserted = upsert_fact_ad_cost_event(session, ad_event_rows)
        day_rows_upserted = upsert_fact_ad_cost_day(session, ad_day_rows)
        event_rows_in_db = count_fact_ad_cost_event_rows(session, start, end, resolved_nm_ids)
        day_rows_in_db = count_fact_ad_cost_day_rows(session, start, end, resolved_nm_ids)
        event_duplicates = count_fact_ad_cost_event_duplicates(session, start, end, resolved_nm_ids)
        day_duplicates = count_fact_ad_cost_day_duplicates(session, start, end, resolved_nm_ids)
        total_event_spend = sum_event_spend(session, start, end, resolved_nm_ids)
        total_day_spend = sum_day_spend(session, start, end, resolved_nm_ids)
        recognized_nm_ids = count_recognized_nm_ids(session, start, end, resolved_nm_ids)
        not_found_nm_ids = count_not_found_nm_ids(session, start, end, resolved_nm_ids)
        mock_like_rows = count_mock_like_rows(session, start, end, resolved_nm_ids)

    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "nm_ids": list(resolved_nm_ids) if resolved_nm_ids is not None else [],
        "event_rows_fetched": metadata["event_rows_fetched"],
        "event_rows_upserted": event_rows_upserted,
        "event_rows_in_db": event_rows_in_db,
        "event_duplicates": event_duplicates,
        "day_rows_built": metadata["day_rows_built"],
        "day_rows_upserted": day_rows_upserted,
        "day_rows_in_db": day_rows_in_db,
        "day_duplicates": day_duplicates,
        "total_event_spend": _json_safe_number(total_event_spend),
        "total_day_spend": _json_safe_number(total_day_spend),
        "spend_totals_match": total_event_spend == total_day_spend,
        "recognized_nm_ids": recognized_nm_ids,
        "not_found_nm_ids": not_found_nm_ids,
        "mock_like_rows": mock_like_rows,
        "status": metadata["status"],
    }
