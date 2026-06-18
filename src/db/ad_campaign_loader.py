from __future__ import annotations

from datetime import date
from decimal import Decimal
import time
from typing import Any, Mapping, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.db.ad_cost_loader import collect_ad_cost_rows
from src.db.funnel_loader import _to_date_or_none, _to_datetime_or_none, _to_decimal_or_none
from src.db.models import FactAdCampaignDay, FactAdCampaignNmDay
from src.db.session import session_scope, upsert_rows
from src.pipelines.mvp_real_run import (
    MvpRealRun,
    TEST_NM_IDS,
    _format_fullstats_conversion_type_for_sheet,
    _to_int,
)


FACT_AD_CAMPAIGN_DAY_CONFLICT_COLUMNS = ("date", "advert_id", "row_type")
FACT_AD_CAMPAIGN_NM_DAY_CONFLICT_COLUMNS = ("date", "advert_id", "row_type", "conversion_type_raw", "nm_id")
FULLSTATS_CHUNK_SLEEP_SECONDS = 4


def _resolve_nm_ids(nm_ids: Sequence[int] | None = None) -> tuple[int, ...]:
    return tuple(nm_ids) if nm_ids else tuple(TEST_NM_IDS)


def _json_safe_number(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def build_fact_ad_campaign_day_db_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "date": _to_date_or_none(row.get("date")),
        "advert_id": row.get("advertId"),
        "campaign_name": row.get("campaign_name") or None,
        "row_type": row.get("row_type") or None,
        "ad_spend": _to_decimal_or_none(row.get("ad_spend")),
        "ad_revenue": _to_decimal_or_none(row.get("ad_revenue")),
        "ad_views": _to_decimal_or_none(row.get("ad_views")),
        "ad_clicks": _to_decimal_or_none(row.get("ad_clicks")),
        "ad_atbs": _to_decimal_or_none(row.get("ad_atbs")),
        "ad_orders": _to_decimal_or_none(row.get("ad_orders")),
        "ordered_items_qty": _to_decimal_or_none(row.get("ordered_items_qty")),
        "ad_cancels": _to_decimal_or_none(row.get("ad_cancels")),
        "avg_position": _to_decimal_or_none(row.get("avg_position")),
        "ad_ctr": _to_decimal_or_none(row.get("ad_ctr")),
        "ad_cpc": _to_decimal_or_none(row.get("ad_cpc")),
        "ad_cpm": _to_decimal_or_none(row.get("ad_cpm")),
        "ad_cr": _to_decimal_or_none(row.get("ad_cr")),
        "ad_roi": _to_decimal_or_none(row.get("ad_roi")),
        "currency": row.get("currency") or None,
        "data_status": row.get("data_status") or None,
        "source_status": row.get("source_status") or None,
        "loaded_at": _to_datetime_or_none(row.get("loaded_at")),
    }


def build_fact_ad_campaign_nm_day_db_row(row: Mapping[str, Any]) -> dict[str, Any]:
    conversion_type_raw = row.get("conversion_type_raw")
    if conversion_type_raw in ("", None):
        conversion_type_raw = None
    conversion_type = row.get("conversion_type") or None
    conversion_type_display = row.get("conversion_type_display")
    if conversion_type_display in ("", None) and (
        conversion_type_raw is not None or conversion_type is not None
    ):
        conversion_type_display = _format_fullstats_conversion_type_for_sheet(conversion_type_raw, conversion_type)
    return {
        "date": _to_date_or_none(row.get("date")),
        "advert_id": row.get("advertId"),
        "campaign_name": row.get("campaign_name") or None,
        "row_type": row.get("row_type") or None,
        "conversion_type": conversion_type,
        "conversion_type_raw": conversion_type_raw,
        "conversion_type_display": conversion_type_display or None,
        "nm_id": row.get("nm_id") or None,
        "product_name": row.get("product_name") or None,
        "ad_spend": _to_decimal_or_none(row.get("ad_spend")),
        "ad_revenue": _to_decimal_or_none(row.get("ad_revenue")),
        "ad_views": _to_decimal_or_none(row.get("ad_views")),
        "ad_clicks": _to_decimal_or_none(row.get("ad_clicks")),
        "ad_atbs": _to_decimal_or_none(row.get("ad_atbs")),
        "ad_orders": _to_decimal_or_none(row.get("ad_orders")),
        "ordered_items_qty": _to_decimal_or_none(row.get("ordered_items_qty")),
        "ad_cancels": _to_decimal_or_none(row.get("ad_cancels")),
        "avg_position": _to_decimal_or_none(row.get("avg_position")),
        "ad_ctr": _to_decimal_or_none(row.get("ad_ctr")),
        "ad_cpc": _to_decimal_or_none(row.get("ad_cpc")),
        "ad_cpm": _to_decimal_or_none(row.get("ad_cpm")),
        "ad_cr": _to_decimal_or_none(row.get("ad_cr")),
        "ad_roi": _to_decimal_or_none(row.get("ad_roi")),
        "currency": row.get("currency") or None,
        "data_status": row.get("data_status") or None,
        "source_status": row.get("source_status") or None,
        "loaded_at": _to_datetime_or_none(row.get("loaded_at")),
    }


def prepare_fact_ad_campaign_day_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        mapped = build_fact_ad_campaign_day_db_row(row)
        key = tuple(mapped.get(column_name) for column_name in FACT_AD_CAMPAIGN_DAY_CONFLICT_COLUMNS)
        if mapped["date"] is None or mapped["advert_id"] in (None, "") or mapped["row_type"] in (None, ""):
            continue
        prepared[key] = mapped
    return list(prepared.values())


def prepare_fact_ad_campaign_nm_day_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        mapped = build_fact_ad_campaign_nm_day_db_row(row)
        key = tuple(mapped.get(column_name) for column_name in FACT_AD_CAMPAIGN_NM_DAY_CONFLICT_COLUMNS)
        if (
            mapped["date"] is None
            or mapped["advert_id"] in (None, "")
            or mapped["row_type"] in (None, "")
            or mapped["nm_id"] in (None, "")
        ):
            continue
        prepared[key] = mapped
    return list(prepared.values())


def replace_fact_ad_campaign_rows(
    session: Session,
    *,
    start: date,
    end: date,
    advert_ids: Sequence[int],
    campaign_rows: Sequence[Mapping[str, Any]],
    nm_rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    resolved_advert_ids = sorted({int(advert_id) for advert_id in advert_ids if advert_id is not None})
    if resolved_advert_ids:
        session.execute(
            delete(FactAdCampaignDay).where(
                FactAdCampaignDay.date >= start,
                FactAdCampaignDay.date <= end,
                FactAdCampaignDay.advert_id.in_(resolved_advert_ids),
            )
        )
        session.execute(
            delete(FactAdCampaignNmDay).where(
                FactAdCampaignNmDay.date >= start,
                FactAdCampaignNmDay.date <= end,
                FactAdCampaignNmDay.advert_id.in_(resolved_advert_ids),
            )
        )

    return {
        "campaign_rows_upserted": upsert_fact_ad_campaign_day(session, campaign_rows),
        "nm_rows_upserted": upsert_fact_ad_campaign_nm_day(session, nm_rows),
    }


def collect_ad_campaign_rows(
    runner: MvpRealRun,
    start: date,
    end: date,
    nm_ids: Sequence[int] | None = None,
    ad_event_rows: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    runner.nm_ids = list(resolved_nm_ids)
    if ad_event_rows is None:
        ad_event_rows, _, ad_cost_metadata = collect_ad_cost_rows(runner, start, end)
    else:
        ad_cost_metadata = {"status": "REUSED", "error": "", "event_rows_fetched": len(ad_event_rows)}
    campaign_name_index = {
        int(row["advertId"]): row["campaign_name"]
        for row in ad_event_rows
        if row.get("advertId") not in (None, "") and row.get("campaign_name")
    }
    campaign_ids = sorted(
        {
            int(row["advertId"])
            for row in ad_event_rows
            if row.get("advertId") not in (None, "") and _to_int(row.get("nm_id")) in resolved_nm_ids
        }
    )

    if not campaign_ids:
        return [], [], {
            "status": "200",
            "error": "",
            "campaign_ids": [],
            "campaign_rows_fetched": 0,
            "nm_rows_fetched": 0,
            "ad_cost_status": ad_cost_metadata["status"],
            "fullstats_requests": 0,
        }

    campaign_rows: list[dict[str, Any]] = []
    nm_rows: list[dict[str, Any]] = []
    fullstats_error = ""
    fullstats_status = "200"
    fullstats_requests = 0
    for index in range(0, len(campaign_ids), 20):
        campaign_chunk = campaign_ids[index:index + 20]
        chunk_status, chunk_payload, chunk_error = runner._fetch_fullstats(campaign_chunk)
        fullstats_requests += 1
        if chunk_status != "200":
            raise RuntimeError(f"Ad campaign stats request failed: {chunk_status} {chunk_error}")
        chunk_campaign_rows, chunk_nm_rows = runner._build_fullstats_rows(chunk_payload, campaign_name_index)
        for row in chunk_nm_rows:
            row["conversion_type_display"] = _format_fullstats_conversion_type_for_sheet(
                row.get("conversion_type_raw", ""),
                row.get("conversion_type", ""),
            )
        campaign_rows.extend(chunk_campaign_rows)
        nm_rows.extend(chunk_nm_rows)
        if index + 20 < len(campaign_ids):
            time.sleep(FULLSTATS_CHUNK_SLEEP_SECONDS)

    return campaign_rows, nm_rows, {
        "status": fullstats_status,
        "error": fullstats_error,
        "campaign_ids": campaign_ids,
        "campaign_rows_fetched": len(campaign_rows),
        "nm_rows_fetched": len(nm_rows),
        "ad_cost_status": ad_cost_metadata["status"],
        "fullstats_requests": fullstats_requests,
    }


def upsert_fact_ad_campaign_day(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_fact_ad_campaign_day_upsert_rows(rows)
    upsert_rows(
        session=session,
        model=FactAdCampaignDay,
        rows=prepared_rows,
        conflict_columns=FACT_AD_CAMPAIGN_DAY_CONFLICT_COLUMNS,
    )
    return len(prepared_rows)


def upsert_fact_ad_campaign_nm_day(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_fact_ad_campaign_nm_day_upsert_rows(rows)
    upsert_rows(
        session=session,
        model=FactAdCampaignNmDay,
        rows=prepared_rows,
        conflict_columns=FACT_AD_CAMPAIGN_NM_DAY_CONFLICT_COLUMNS,
    )
    return len(prepared_rows)


def count_fact_ad_campaign_day_rows(session: Session, start: date, end: date) -> int:
    stmt = (
        select(func.count())
        .select_from(FactAdCampaignDay)
        .where(FactAdCampaignDay.date >= start, FactAdCampaignDay.date <= end)
    )
    return int(session.execute(stmt).scalar_one())


def count_fact_ad_campaign_nm_day_rows(session: Session, start: date, end: date) -> int:
    stmt = (
        select(func.count())
        .select_from(FactAdCampaignNmDay)
        .where(FactAdCampaignNmDay.date >= start, FactAdCampaignNmDay.date <= end)
    )
    return int(session.execute(stmt).scalar_one())


def count_fact_ad_campaign_day_duplicates(session: Session, start: date, end: date) -> int:
    dup_stmt = (
        select(FactAdCampaignDay.date, FactAdCampaignDay.advert_id, FactAdCampaignDay.row_type)
        .where(FactAdCampaignDay.date >= start, FactAdCampaignDay.date <= end)
        .group_by(FactAdCampaignDay.date, FactAdCampaignDay.advert_id, FactAdCampaignDay.row_type)
        .having(func.count() > 1)
    )
    return len(session.execute(dup_stmt).all())


def count_fact_ad_campaign_nm_day_duplicates(session: Session, start: date, end: date) -> int:
    dup_stmt = (
        select(
            FactAdCampaignNmDay.date,
            FactAdCampaignNmDay.advert_id,
            FactAdCampaignNmDay.row_type,
            FactAdCampaignNmDay.conversion_type_raw,
            FactAdCampaignNmDay.nm_id,
        )
        .where(FactAdCampaignNmDay.date >= start, FactAdCampaignNmDay.date <= end)
        .group_by(
            FactAdCampaignNmDay.date,
            FactAdCampaignNmDay.advert_id,
            FactAdCampaignNmDay.row_type,
            FactAdCampaignNmDay.conversion_type_raw,
            FactAdCampaignNmDay.nm_id,
        )
        .having(func.count() > 1)
    )
    return len(session.execute(dup_stmt).all())


def sum_fact_ad_campaign_day_spend(session: Session, start: date, end: date) -> Decimal | None:
    stmt = (
        select(func.sum(FactAdCampaignDay.ad_spend))
        .where(FactAdCampaignDay.date >= start, FactAdCampaignDay.date <= end)
    )
    return session.execute(stmt).scalar_one()


def sum_fact_ad_campaign_nm_day_spend(session: Session, start: date, end: date) -> Decimal | None:
    stmt = (
        select(func.sum(FactAdCampaignNmDay.ad_spend))
        .where(FactAdCampaignNmDay.date >= start, FactAdCampaignNmDay.date <= end)
    )
    return session.execute(stmt).scalar_one()


def count_conversion_type_display(session: Session, start: date, end: date, display_value: str) -> int:
    stmt = (
        select(func.count())
        .select_from(FactAdCampaignNmDay)
        .where(
            FactAdCampaignNmDay.date >= start,
            FactAdCampaignNmDay.date <= end,
            FactAdCampaignNmDay.conversion_type_display == display_value,
        )
    )
    return int(session.execute(stmt).scalar_one())


def count_mock_like_rows(session: Session, start: date, end: date) -> int:
    stmt = (
        select(func.count())
        .select_from(FactAdCampaignNmDay)
        .where(
            FactAdCampaignNmDay.date >= start,
            FactAdCampaignNmDay.date <= end,
            (
                FactAdCampaignNmDay.product_name.ilike("%DRY_RUN%")
                | FactAdCampaignNmDay.product_name.ilike("%mock%")
                | FactAdCampaignNmDay.product_name.ilike("%fake%")
                | FactAdCampaignNmDay.product_name.ilike("%TestBrand%")
                | FactAdCampaignNmDay.product_name.ilike("%Товар тестовый%")
            ),
        )
    )
    return int(session.execute(stmt).scalar_one())


def load_ad_campaign_stats_to_db(
    start: date,
    end: date,
    nm_ids: Sequence[int] | None = None,
    ad_event_rows: Sequence[Mapping[str, Any]] | None = None,
    replace_scope: bool = False,
) -> dict[str, Any]:
    resolved_nm_ids = _resolve_nm_ids(nm_ids)
    runner = MvpRealRun()
    runner.date_from = start
    runner.date_to = end
    campaign_rows, nm_rows, metadata = collect_ad_campaign_rows(
        runner,
        start,
        end,
        nm_ids=resolved_nm_ids,
        ad_event_rows=ad_event_rows,
    )

    parsed_day_spend = sum((_to_decimal_or_none(row.get("ad_spend")) or Decimal("0")) for row in campaign_rows)
    parsed_nm_spend = sum((_to_decimal_or_none(row.get("ad_spend")) or Decimal("0")) for row in nm_rows)
    parsed_distribution = {
        "Ассоциированная": sum(1 for row in nm_rows if row.get("conversion_type_display") == "Ассоциированная"),
        "Прямая": sum(1 for row in nm_rows if row.get("conversion_type_display") == "Прямая"),
        "Мультикарточка": sum(1 for row in nm_rows if row.get("conversion_type_display") == "Мультикарточка"),
        "UNKNOWN_CODE_64": sum(1 for row in nm_rows if row.get("conversion_type_display") == "UNKNOWN_CODE_64"),
    }

    with session_scope() as session:
        if replace_scope:
            replace_result = replace_fact_ad_campaign_rows(
                session,
                start=start,
                end=end,
                advert_ids=metadata["campaign_ids"],
                campaign_rows=campaign_rows,
                nm_rows=nm_rows,
            )
            day_rows_upserted = replace_result["campaign_rows_upserted"]
            nm_rows_upserted = replace_result["nm_rows_upserted"]
        else:
            day_rows_upserted = upsert_fact_ad_campaign_day(session, campaign_rows)
            nm_rows_upserted = upsert_fact_ad_campaign_nm_day(session, nm_rows)
        day_rows_in_db = count_fact_ad_campaign_day_rows(session, start, end)
        nm_rows_in_db = count_fact_ad_campaign_nm_day_rows(session, start, end)
        day_duplicates = count_fact_ad_campaign_day_duplicates(session, start, end)
        nm_duplicates = count_fact_ad_campaign_nm_day_duplicates(session, start, end)
        db_day_spend = sum_fact_ad_campaign_day_spend(session, start, end)
        db_nm_spend = sum_fact_ad_campaign_nm_day_spend(session, start, end)
        db_distribution = {
            "Ассоциированная": count_conversion_type_display(session, start, end, "Ассоциированная"),
            "Прямая": count_conversion_type_display(session, start, end, "Прямая"),
            "Мультикарточка": count_conversion_type_display(session, start, end, "Мультикарточка"),
            "UNKNOWN_CODE_64": count_conversion_type_display(session, start, end, "UNKNOWN_CODE_64"),
        }
        mock_like_rows = count_mock_like_rows(session, start, end)

    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "campaign_ids": metadata["campaign_ids"],
        "campaign_rows_fetched": metadata["campaign_rows_fetched"],
        "campaign_rows_upserted": day_rows_upserted,
        "campaign_rows_in_db": day_rows_in_db,
        "campaign_duplicates": day_duplicates,
        "nm_rows_fetched": metadata["nm_rows_fetched"],
        "nm_rows_upserted": nm_rows_upserted,
        "nm_rows_in_db": nm_rows_in_db,
        "nm_duplicates": nm_duplicates,
        "parsed_day_spend": _json_safe_number(parsed_day_spend),
        "db_day_spend": _json_safe_number(db_day_spend),
        "day_spend_match": db_day_spend == parsed_day_spend,
        "parsed_nm_spend": _json_safe_number(parsed_nm_spend),
        "db_nm_spend": _json_safe_number(db_nm_spend),
        "nm_spend_match": db_nm_spend == parsed_nm_spend,
        "parsed_conversion_distribution": parsed_distribution,
        "db_conversion_distribution": db_distribution,
        "conversion_distribution_match": parsed_distribution == db_distribution,
        "unknown_code_64_rows": db_distribution["UNKNOWN_CODE_64"],
        "mock_like_rows": mock_like_rows,
        "ad_cost_status": metadata["ad_cost_status"],
        "fullstats_status": metadata["status"],
        "fullstats_requests": metadata.get("fullstats_requests", 0),
        "replace_scope": replace_scope,
    }
