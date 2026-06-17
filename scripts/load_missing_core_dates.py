#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Sequence


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import distinct, func, select

from scripts.export_ad_campaign_product_dataset import export_ad_campaign_product_dataset
from scripts.export_streamlit_v1_dataset import export_streamlit_v1_dataset
from src.db.ad_fullstats_retry_queue import (
    build_failed_group_row,
    get_failed_group_attempts_count,
    load_due_failed_group_rows,
    mark_failed_group_success,
    upsert_failed_groups,
)
from src.db.ad_campaign_loader import load_ad_campaign_stats_to_db
from src.db.ad_cost_loader import load_ad_costs_to_db
from src.db.advert_metadata_loader import load_advert_metadata_to_db
from src.db.funnel_loader import load_funnel_to_db
from src.db.localization_loader import load_localization_to_db
from src.db.mart_total_report_builder import build_mart_total_report
from src.db.models import (
    AdFullstatsFailedGroup,
    FactAdCampaignDay,
    FactAdCampaignNmDay,
    FactAdCostDay,
    FactAdCostEvent,
    FactFunnelDay,
    FactLocalizationRegionDay,
    FactSearchQueryMetric,
    FactStockSnapshot,
    MartTotalReport,
    SettingsProducts,
)
from src.db.search_query_loader import load_search_queries_to_db
from src.db.session import session_scope
from src.db.stock_loader import load_stocks_to_db
from src.tracked_products import get_tracked_nm_ids


DEFAULT_DATE_FROM = date(2026, 6, 2)
DEFAULT_DATE_TO = date(2026, 6, 6)
DEFAULT_FULL_RANGE_FROM = date(2026, 5, 31)
DEFAULT_FULL_RANGE_TO = date(2026, 6, 7)
FUNNEL_CHUNK_SIZE = 20
SEARCH_CHUNK_SIZE = 50
STOCK_CHUNK_SIZE = 100
FULLSTATS_SLEEP_SECONDS = 60
SEARCH_CHUNK_SLEEP_SECONDS = 8


@dataclass(slots=True)
class SourceLogRow:
    source_name: str
    report_date: str
    chunk_number: int
    item_count: int
    rows_fetched: int
    rows_upserted: int
    status: str
    error: str
    retry_count: int


@dataclass(slots=True)
class FullstatsAdvertGroup:
    advert_id: int
    rows: list[dict[str, Any]]
    dates: set[date]


def _build_fullstats_group_key(*, date_from: date, date_to: date, advert_id: int) -> str:
    return f"{date_from.isoformat()}:{date_to.isoformat()}:{int(advert_id)}"


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _daterange(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _chunked(values: Sequence[int], size: int) -> list[list[int]]:
    return [list(values[index:index + size]) for index in range(0, len(values), size)]


def _load_active_products() -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.execute(
            select(
                SettingsProducts.nm_id,
                SettingsProducts.supplier_article,
                SettingsProducts.title,
                SettingsProducts.subject,
                SettingsProducts.brand,
            )
            .where(SettingsProducts.active.is_(True))
            .order_by(SettingsProducts.nm_id)
        ).all()
    return [row._asdict() for row in rows]


def _load_products_by_nm_ids(nm_ids: Sequence[int]) -> list[dict[str, Any]]:
    if not nm_ids:
        return []
    with session_scope() as session:
        rows = session.execute(
            select(
                SettingsProducts.nm_id,
                SettingsProducts.supplier_article,
                SettingsProducts.title,
                SettingsProducts.subject,
                SettingsProducts.brand,
            )
            .where(SettingsProducts.nm_id.in_(list(nm_ids)))
            .order_by(SettingsProducts.nm_id)
        ).all()
    return [row._asdict() for row in rows]


def _build_reference_indexes(
    active_products: Sequence[dict[str, Any]],
) -> tuple[dict[int, dict[str, str]], dict[str, dict[str, str]]]:
    int_index: dict[int, dict[str, str]] = {}
    str_index: dict[str, dict[str, str]] = {}
    for row in active_products:
        nm_id = int(row["nm_id"])
        payload = {
            "supplier_article": row.get("supplier_article") or "",
            "title": row.get("title") or "",
            "subject": row.get("subject") or "",
            "brand": row.get("brand") or "",
        }
        int_index[nm_id] = payload
        str_index[str(nm_id)] = payload
    return int_index, str_index


def _infer_http_code(error_text: str) -> int | None:
    for code in ("429", "500"):
        if code in (error_text or ""):
            return int(code)
    return None


def _run_with_retry(
    *,
    source_name: str,
    report_date: date,
    chunk_number: int,
    item_count: int,
    loader: Callable[[], dict[str, Any]],
    rows_fetched_key: str,
    rows_upserted_key: str,
    status_key: str | None = None,
    max_retries: int = 1,
    retry_sleep_seconds: int = 10,
) -> tuple[dict[str, Any], SourceLogRow]:
    retry_count = 0
    last_error = ""
    result: dict[str, Any] = {}
    status = "FAIL"
    while True:
        try:
            result = loader()
            status = str(result.get(status_key or "status") or "OK")
            last_error = ""
            break
        except Exception as exc:
            last_error = str(exc)
            if retry_count >= max_retries:
                break
            retry_count += 1
            time.sleep(retry_sleep_seconds * retry_count)

    return result, SourceLogRow(
        source_name=source_name,
        report_date=report_date.isoformat(),
        chunk_number=chunk_number,
        item_count=item_count,
        rows_fetched=int(result.get(rows_fetched_key, 0) or 0),
        rows_upserted=int(result.get(rows_upserted_key, 0) or 0),
        status=status,
        error=last_error,
        retry_count=retry_count,
    )


def _load_ad_event_groups(date_from: date, date_to: date, active_nm_ids: Sequence[int]) -> list[FullstatsAdvertGroup]:
    with session_scope() as session:
        rows = session.execute(
            select(
                FactAdCostEvent.advert_id,
                FactAdCostEvent.campaign_name,
                FactAdCostEvent.nm_id,
                FactAdCostEvent.date,
            )
            .where(
                FactAdCostEvent.date >= date_from,
                FactAdCostEvent.date <= date_to,
                FactAdCostEvent.advert_id.is_not(None),
                FactAdCostEvent.nm_id.is_not(None),
                FactAdCostEvent.nm_id.in_(list(active_nm_ids)),
            )
            .order_by(FactAdCostEvent.advert_id, FactAdCostEvent.nm_id)
        ).all()

    grouped_rows: dict[int, dict[str, Any]] = {}
    for row in rows:
        advert_id = int(row.advert_id)
        payload = grouped_rows.setdefault(
            advert_id,
            {
                "campaign_name": row.campaign_name,
                "nm_ids": set(),
                "dates": set(),
            },
        )
        payload["nm_ids"].add(int(row.nm_id))
        if row.date is not None:
            payload["dates"].add(row.date)

    result: list[FullstatsAdvertGroup] = []
    for advert_id in sorted(grouped_rows):
        payload = grouped_rows[advert_id]
        result.append(
            FullstatsAdvertGroup(
                advert_id=advert_id,
                rows=[
                    {
                        "advertId": advert_id,
                        "campaign_name": payload["campaign_name"],
                        "nm_id": nm_id,
                    }
                    for nm_id in sorted(payload["nm_ids"])
                ],
                dates=set(payload["dates"]),
            )
        )
    return result


def _load_processed_fullstats_advert_dates(date_from: date, date_to: date) -> set[tuple[int, date]]:
    with session_scope() as session:
        rows = session.execute(
            select(distinct(FactAdCampaignDay.advert_id), FactAdCampaignDay.date).where(
                FactAdCampaignDay.date >= date_from,
                FactAdCampaignDay.date <= date_to,
                FactAdCampaignDay.advert_id.is_not(None),
            )
        ).all()
    return {
        (int(row[0]), row[1])
        for row in rows
        if row[0] is not None and row[1] is not None
    }


def _select_fullstats_groups_for_processing(
    groups: Sequence[FullstatsAdvertGroup],
    processed_pairs: set[tuple[int, date]],
    *,
    force_refresh: bool,
) -> tuple[list[FullstatsAdvertGroup], int]:
    selected_groups: list[FullstatsAdvertGroup] = []
    fully_processed_count = 0
    for group in groups:
        required_pairs = {(group.advert_id, group_date) for group_date in group.dates}
        is_fully_processed = bool(required_pairs) and required_pairs.issubset(processed_pairs)
        if is_fully_processed:
            fully_processed_count += 1
        if force_refresh or not is_fully_processed:
            selected_groups.append(group)
    return selected_groups, fully_processed_count


def _count_remaining_fullstats_groups(
    groups: Sequence[FullstatsAdvertGroup],
    processed_pairs: set[tuple[int, date]],
) -> int:
    remaining = 0
    for group in groups:
        required_pairs = {(group.advert_id, group_date) for group_date in group.dates}
        if not required_pairs or not required_pairs.issubset(processed_pairs):
            remaining += 1
    return remaining


def _select_failed_fullstats_groups_for_retry(
    groups: Sequence[FullstatsAdvertGroup],
    failed_advert_ids: set[int],
) -> list[FullstatsAdvertGroup]:
    if not failed_advert_ids:
        return []
    return [group for group in groups if group.advert_id in failed_advert_ids]


def _merge_fullstats_groups(
    *groups_collections: Sequence[FullstatsAdvertGroup],
) -> list[FullstatsAdvertGroup]:
    merged: dict[int, FullstatsAdvertGroup] = {}
    for groups in groups_collections:
        for group in groups:
            merged[group.advert_id] = group
    return [merged[advert_id] for advert_id in sorted(merged)]


def _load_pending_failed_fullstats_advert_ids(date_from: date, date_to: date) -> set[int]:
    with session_scope() as session:
        failed_rows = load_due_failed_group_rows(
            session,
            date_from=date_from,
            date_to=date_to,
        )
    return {int(row.advert_id) for row in failed_rows}


def _count_by_date(model, date_column, start: date, end: date) -> dict[str, int]:
    with session_scope() as session:
        rows = session.execute(
            select(date_column, func.count())
            .select_from(model)
            .where(date_column >= start, date_column <= end)
            .group_by(date_column)
            .order_by(date_column)
        ).all()
    return {row[0].isoformat(): int(row[1]) for row in rows if row[0] is not None}


def _build_mart_date_diagnostics(start: date, end: date) -> dict[str, dict[str, int]]:
    diagnostics: dict[str, dict[str, int]] = {}
    for report_date in _daterange(start, end):
        with session_scope() as session:
            base_condition = MartTotalReport.report_date == report_date
            rows_in_mart = int(session.execute(select(func.count()).select_from(MartTotalReport).where(base_condition)).scalar_one())
            rows_with_funnel = int(
                session.execute(
                    select(func.count()).select_from(MartTotalReport).where(base_condition, MartTotalReport.has_funnel.is_(True))
                ).scalar_one()
            )
            rows_with_stock = int(
                session.execute(
                    select(func.count()).select_from(MartTotalReport).where(base_condition, MartTotalReport.has_stock.is_(True))
                ).scalar_one()
            )
            rows_with_ad_cost = int(
                session.execute(
                    select(func.count()).select_from(MartTotalReport).where(base_condition, MartTotalReport.has_ad_cost.is_(True))
                ).scalar_one()
            )
            rows_with_ad_campaign = int(
                session.execute(
                    select(func.count()).select_from(MartTotalReport).where(base_condition, MartTotalReport.has_ad_campaign.is_(True))
                ).scalar_one()
            )
            rows_with_search = int(
                session.execute(
                    select(func.count()).select_from(MartTotalReport).where(base_condition, MartTotalReport.has_search.is_(True))
                ).scalar_one()
            )
            rows_with_localization_partial = int(
                session.execute(
                    select(func.count()).select_from(MartTotalReport).where(base_condition, MartTotalReport.has_localization_partial.is_(True))
                ).scalar_one()
            )
            rows_without_any_data = int(
                session.execute(
                    select(func.count()).select_from(MartTotalReport).where(
                        base_condition,
                        MartTotalReport.has_funnel.is_(False),
                        MartTotalReport.has_stock.is_(False),
                        MartTotalReport.has_ad_cost.is_(False),
                        MartTotalReport.has_ad_campaign.is_(False),
                        MartTotalReport.has_search.is_(False),
                        MartTotalReport.has_localization_partial.is_(False),
                    )
                ).scalar_one()
            )

        diagnostics[report_date.isoformat()] = {
            "rows_in_mart": rows_in_mart,
            "rows_with_funnel": rows_with_funnel,
            "rows_with_stock": rows_with_stock,
            "rows_with_ad_cost": rows_with_ad_cost,
            "rows_with_ad_campaign": rows_with_ad_campaign,
            "rows_with_search": rows_with_search,
            "rows_with_localization_partial": rows_with_localization_partial,
            "rows_without_any_data": rows_without_any_data,
        }
    return diagnostics


def run_missing_core_dates_load(
    *,
    date_from: date,
    date_to: date,
    full_range_from: date,
    full_range_to: date,
    fullstats_sleep_seconds: int,
    use_tracked_products: bool = False,
    force_fullstats_refresh: bool = False,
    retry_failed_fullstats_only: bool = False,
    fullstats_only: bool = False,
) -> dict[str, Any]:
    scope_mode = "tracked_products" if use_tracked_products else "active_products"
    if use_tracked_products:
        active_nm_ids = sorted({int(nm_id) for nm_id in get_tracked_nm_ids()})
        active_products = _load_products_by_nm_ids(active_nm_ids)
    else:
        active_products = _load_active_products()
        active_nm_ids = [int(row["nm_id"]) for row in active_products]
    reference_index_int, reference_index_str = _build_reference_indexes(active_products)
    dates = _daterange(date_from, date_to)
    skip_base_loaders = retry_failed_fullstats_only or fullstats_only
    dates_to_refresh = [] if skip_base_loaders else dates
    source_logs: list[SourceLogRow] = []
    failed_chunks: list[dict[str, Any]] = []
    summary_by_source: dict[str, dict[str, Any]] = defaultdict(lambda: {"rows_fetched": 0, "rows_upserted": 0, "runs": 0})
    http_error_counts = {"429": 0, "500": 0}

    for report_date in dates_to_refresh:
        funnel_chunks = _chunked(active_nm_ids, FUNNEL_CHUNK_SIZE)
        for index, chunk in enumerate(funnel_chunks, start=1):
            result, log_row = _run_with_retry(
                source_name="fact_funnel_day",
                report_date=report_date,
                chunk_number=index,
                item_count=len(chunk),
                loader=lambda day=report_date, chunk=chunk: load_funnel_to_db(day, day, nm_ids=chunk),
                rows_fetched_key="rows_fetched",
                rows_upserted_key="rows_upserted",
                status_key="history_status",
                max_retries=2,
                retry_sleep_seconds=12,
            )
            source_logs.append(log_row)
            summary_by_source["fact_funnel_day"]["rows_fetched"] += log_row.rows_fetched
            summary_by_source["fact_funnel_day"]["rows_upserted"] += log_row.rows_upserted
            summary_by_source["fact_funnel_day"]["runs"] += 1
            if log_row.error:
                code = _infer_http_code(log_row.error)
                if code is not None:
                    http_error_counts[str(code)] += 1
                failed_chunks.append(
                    {
                        "source_name": log_row.source_name,
                        "date": log_row.report_date,
                        "chunk_number": log_row.chunk_number,
                        "error": log_row.error,
                    }
                )

        stock_chunks = _chunked(active_nm_ids, STOCK_CHUNK_SIZE)
        for index, chunk in enumerate(stock_chunks, start=1):
            result, log_row = _run_with_retry(
                source_name="fact_stock_snapshot",
                report_date=report_date,
                chunk_number=index,
                item_count=len(chunk),
                loader=lambda day=report_date, chunk=chunk: load_stocks_to_db(day, nm_ids=chunk),
                rows_fetched_key="rows_fetched",
                rows_upserted_key="rows_upserted",
            )
            source_logs.append(log_row)
            summary_by_source["fact_stock_snapshot"]["rows_fetched"] += log_row.rows_fetched
            summary_by_source["fact_stock_snapshot"]["rows_upserted"] += log_row.rows_upserted
            summary_by_source["fact_stock_snapshot"]["runs"] += 1
            if log_row.error:
                code = _infer_http_code(log_row.error)
                if code is not None:
                    http_error_counts[str(code)] += 1
                failed_chunks.append(
                    {
                        "source_name": log_row.source_name,
                        "date": log_row.report_date,
                        "chunk_number": log_row.chunk_number,
                        "error": log_row.error,
                    }
                )

        search_chunks = _chunked(active_nm_ids, SEARCH_CHUNK_SIZE)
        for index, chunk in enumerate(search_chunks, start=1):
            start_day = report_date - timedelta(days=1)
            result, log_row = _run_with_retry(
                source_name="fact_search_query_metric",
                report_date=report_date,
                chunk_number=index,
                item_count=len(chunk),
                loader=lambda start_day=start_day, end_day=report_date, chunk=chunk: load_search_queries_to_db(
                    start_day,
                    end_day,
                    nm_ids=chunk,
                    reference_index={nm_id: reference_index_int[nm_id] for nm_id in chunk if nm_id in reference_index_int},
                ),
                rows_fetched_key="rows_fetched",
                rows_upserted_key="rows_upserted",
                status_key="current_status",
                max_retries=2,
                retry_sleep_seconds=15,
            )
            source_logs.append(log_row)
            summary_by_source["fact_search_query_metric"]["rows_fetched"] += log_row.rows_fetched
            summary_by_source["fact_search_query_metric"]["rows_upserted"] += log_row.rows_upserted
            summary_by_source["fact_search_query_metric"]["runs"] += 1
            if log_row.error:
                code = _infer_http_code(log_row.error)
                if code is not None:
                    http_error_counts[str(code)] += 1
                failed_chunks.append(
                    {
                        "source_name": log_row.source_name,
                        "date": log_row.report_date,
                        "chunk_number": log_row.chunk_number,
                        "error": log_row.error,
                    }
                )
            if index < len(search_chunks):
                time.sleep(SEARCH_CHUNK_SLEEP_SECONDS)

        result, log_row = _run_with_retry(
            source_name="fact_ad_cost_day",
            report_date=report_date,
            chunk_number=1,
            item_count=len(active_nm_ids),
            loader=lambda day=report_date: load_ad_costs_to_db(day, day, nm_ids=active_nm_ids),
            rows_fetched_key="day_rows_built",
            rows_upserted_key="day_rows_upserted",
            max_retries=2,
            retry_sleep_seconds=15,
        )
        source_logs.append(log_row)
        summary_by_source["fact_ad_cost_event"]["rows_fetched"] += int(result.get("event_rows_fetched", 0) or 0)
        summary_by_source["fact_ad_cost_event"]["rows_upserted"] += int(result.get("event_rows_upserted", 0) or 0)
        summary_by_source["fact_ad_cost_event"]["runs"] += 1
        summary_by_source["fact_ad_cost_day"]["rows_fetched"] += log_row.rows_fetched
        summary_by_source["fact_ad_cost_day"]["rows_upserted"] += log_row.rows_upserted
        summary_by_source["fact_ad_cost_day"]["runs"] += 1
        if log_row.error:
            code = _infer_http_code(log_row.error)
            if code is not None:
                http_error_counts[str(code)] += 1
            failed_chunks.append(
                {
                    "source_name": log_row.source_name,
                    "date": log_row.report_date,
                    "chunk_number": 1,
                    "error": log_row.error,
                }
            )

        result, log_row = _run_with_retry(
            source_name="fact_localization_region_day",
            report_date=report_date,
            chunk_number=1,
            item_count=len(active_nm_ids),
            loader=lambda day=report_date: load_localization_to_db(
                day,
                day,
                nm_ids=active_nm_ids,
                reference_index=reference_index_str,
            ),
            rows_fetched_key="rows_fetched",
            rows_upserted_key="rows_upserted",
            max_retries=1,
            retry_sleep_seconds=10,
        )
        source_logs.append(log_row)
        summary_by_source["fact_localization_region_day"]["rows_fetched"] += log_row.rows_fetched
        summary_by_source["fact_localization_region_day"]["rows_upserted"] += log_row.rows_upserted
        summary_by_source["fact_localization_region_day"]["runs"] += 1
        if log_row.error:
            code = _infer_http_code(log_row.error)
            if code is not None:
                http_error_counts[str(code)] += 1
            failed_chunks.append(
                {
                    "source_name": log_row.source_name,
                    "date": log_row.report_date,
                    "chunk_number": 1,
                    "error": log_row.error,
                }
            )

    fullstats_groups = _load_ad_event_groups(date_from, date_to, active_nm_ids)
    try:
        advert_metadata_summary = load_advert_metadata_to_db(
            advert_ids=[group.advert_id for group in fullstats_groups],
        )
    except Exception as exc:
        advert_metadata_summary = {
            "status": "ERROR",
            "error": str(exc),
            "rows_fetched": 0,
            "rows_upserted": 0,
            "advert_ids_requested": [group.advert_id for group in fullstats_groups],
            "advert_ids_loaded": [],
        }
    processed_before = _load_processed_fullstats_advert_dates(date_from, date_to)
    coverage_groups, fully_processed_before = _select_fullstats_groups_for_processing(
        fullstats_groups,
        processed_before,
        force_refresh=force_fullstats_refresh,
    )
    pending_failed_advert_ids = _load_pending_failed_fullstats_advert_ids(date_from, date_to)
    retry_groups = _select_failed_fullstats_groups_for_retry(fullstats_groups, pending_failed_advert_ids)
    if retry_failed_fullstats_only:
        selected_groups = retry_groups
    else:
        selected_groups = _merge_fullstats_groups(coverage_groups, retry_groups)
    fullstats_summary = {
        "total_advert_ids_found": len(fullstats_groups),
        "already_processed_before_run": fully_processed_before,
        "coverage_selected_before_retry_merge": len(coverage_groups),
        "retry_queue_pending_before_run": len(pending_failed_advert_ids),
        "retry_groups_selected": len(retry_groups),
        "retry_failed_fullstats_only": retry_failed_fullstats_only,
        "fullstats_only": fullstats_only,
        "advert_ids_attempted": 0,
        "advert_ids_processed_this_run": 0,
        "remaining_after_run": 0,
        "stopped_on_429_advert_id": None,
        "failed_advert_ids": [],
        "force_fullstats_refresh": force_fullstats_refresh,
    }

    for index, group in enumerate(selected_groups, start=1):
        advert_id = group.advert_id
        ad_event_rows = group.rows
        nm_ids = sorted({int(row["nm_id"]) for row in ad_event_rows if row.get("nm_id") is not None})
        group_key = _build_fullstats_group_key(date_from=date_from, date_to=date_to, advert_id=advert_id)
        try:
            result, log_row = _run_with_retry(
                source_name="fact_ad_campaign_nm_day",
                report_date=date_to,
                chunk_number=index,
                item_count=len(nm_ids),
                loader=lambda rows=ad_event_rows, nm_ids=nm_ids: load_ad_campaign_stats_to_db(
                    date_from,
                    date_to,
                    nm_ids=nm_ids,
                    ad_event_rows=rows,
                    replace_scope=force_fullstats_refresh,
                ),
                rows_fetched_key="nm_rows_fetched",
                rows_upserted_key="nm_rows_upserted",
                status_key="fullstats_status",
                max_retries=1,
                retry_sleep_seconds=20,
            )
        except Exception as exc:  # defensive, _run_with_retry should absorb
            log_row = SourceLogRow(
                source_name="fact_ad_campaign_nm_day",
                report_date=date_to.isoformat(),
                chunk_number=index,
                item_count=len(nm_ids),
                rows_fetched=0,
                rows_upserted=0,
                status="FAIL",
                error=str(exc),
                retry_count=0,
            )
            result = {}

        fullstats_summary["advert_ids_attempted"] = index
        source_logs.append(log_row)
        summary_by_source["fact_ad_campaign_day"]["rows_fetched"] += int(result.get("campaign_rows_fetched", 0) or 0)
        summary_by_source["fact_ad_campaign_day"]["rows_upserted"] += int(result.get("campaign_rows_upserted", 0) or 0)
        summary_by_source["fact_ad_campaign_day"]["runs"] += 1
        summary_by_source["fact_ad_campaign_nm_day"]["rows_fetched"] += log_row.rows_fetched
        summary_by_source["fact_ad_campaign_nm_day"]["rows_upserted"] += log_row.rows_upserted
        summary_by_source["fact_ad_campaign_nm_day"]["runs"] += 1

        if log_row.error:
            attempted_at = datetime.now().astimezone()
            with session_scope() as session:
                attempts_count = get_failed_group_attempts_count(
                    session,
                    date_from=date_from,
                    date_to=date_to,
                    advert_id=advert_id,
                    group_key=group_key,
                ) + 1
                upsert_failed_groups(
                    session,
                    [
                        build_failed_group_row(
                            date_from=date_from,
                            date_to=date_to,
                            advert_id=advert_id,
                            group_key=group_key,
                            campaign_name=group.rows[0].get("campaign_name") if group.rows else None,
                            nm_ids=nm_ids,
                            last_error=log_row.error,
                            attempted_at=attempted_at,
                            attempts_count=attempts_count,
                            retry_delay_seconds=fullstats_sleep_seconds,
                        )
                    ],
                )
            code = _infer_http_code(log_row.error)
            if code is not None:
                http_error_counts[str(code)] += 1
            fullstats_summary["failed_advert_ids"].append(
                {
                    "advert_id": advert_id,
                    "error": log_row.error,
                }
            )
            failed_chunks.append(
                {
                    "source_name": "fact_ad_campaign_nm_day",
                    "date": f"{date_from.isoformat()}..{date_to.isoformat()}",
                    "advert_id": advert_id,
                    "error": log_row.error,
                }
            )
            if code == 429:
                fullstats_summary["stopped_on_429_advert_id"] = advert_id
                break
        else:
            attempted_at = datetime.now().astimezone()
            with session_scope() as session:
                mark_failed_group_success(
                    session,
                    date_from=date_from,
                    date_to=date_to,
                    advert_id=advert_id,
                    group_key=group_key,
                    attempted_at=attempted_at,
                )
            fullstats_summary["advert_ids_processed_this_run"] += 1

        if index < len(selected_groups):
            time.sleep(fullstats_sleep_seconds)

    processed_after = _load_processed_fullstats_advert_dates(date_from, date_to)
    fullstats_summary["remaining_after_run"] = _count_remaining_fullstats_groups(fullstats_groups, processed_after)
    with session_scope() as session:
        pending_after = session.execute(
            select(func.count())
            .select_from(AdFullstatsFailedGroup)
            .where(
                AdFullstatsFailedGroup.date_from == date_from,
                AdFullstatsFailedGroup.date_to == date_to,
                AdFullstatsFailedGroup.status == "pending",
            )
        ).scalar_one()
        success_after = session.execute(
            select(func.count())
            .select_from(AdFullstatsFailedGroup)
            .where(
                AdFullstatsFailedGroup.date_from == date_from,
                AdFullstatsFailedGroup.date_to == date_to,
                AdFullstatsFailedGroup.status == "success",
            )
        ).scalar_one()
    fullstats_summary["retry_queue_pending_after_run"] = int(pending_after or 0)
    fullstats_summary["retry_queue_success_after_run"] = int(success_after or 0)

    mart_summary = build_mart_total_report(full_range_from, full_range_to, version="v2")
    streamlit_dataset_summary = export_streamlit_v1_dataset(full_range_from, full_range_to)
    ad_campaign_product_summary = export_ad_campaign_product_dataset(full_range_from, full_range_to)

    mart_diagnostics = _build_mart_date_diagnostics(date_from, date_to)
    fact_diagnostics = {
        "fact_funnel_day": _count_by_date(FactFunnelDay, FactFunnelDay.date, date_from, date_to),
        "fact_ad_cost_day": _count_by_date(FactAdCostDay, FactAdCostDay.date, date_from, date_to),
        "fact_ad_campaign_nm_day": _count_by_date(FactAdCampaignNmDay, FactAdCampaignNmDay.date, date_from, date_to),
        "fact_search_query_metric": _count_by_date(FactSearchQueryMetric, FactSearchQueryMetric.date, date_from, date_to),
        "fact_stock_snapshot": _count_by_date(FactStockSnapshot, FactStockSnapshot.snapshot_date, date_from, date_to),
        "fact_localization_region_day": _count_by_date(FactLocalizationRegionDay, FactLocalizationRegionDay.date, date_from, date_to),
    }

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "scope_mode": scope_mode,
        "scope_products_count": len(active_nm_ids),
        "active_products_count": len(active_nm_ids),
        "dates_loaded": [day.isoformat() for day in dates],
        "skip_base_loaders": skip_base_loaders,
        "summary_by_source": summary_by_source,
        "mart_summary": mart_summary,
        "streamlit_dataset_summary": streamlit_dataset_summary,
        "ad_campaign_product_summary": ad_campaign_product_summary,
        "mart_date_diagnostics": mart_diagnostics,
        "fact_table_date_diagnostics": fact_diagnostics,
        "http_error_counts": http_error_counts,
        "advert_metadata_summary": advert_metadata_summary,
        "fullstats_summary": fullstats_summary,
        "failed_chunks": failed_chunks,
        "failed_sources": sorted({row.source_name for row in source_logs if row.error}),
        "source_logs": [
            {
                "source_name": row.source_name,
                "report_date": row.report_date,
                "chunk_number": row.chunk_number,
                "item_count": row.item_count,
                "rows_fetched": row.rows_fetched,
                "rows_upserted": row.rows_upserted,
                "status": row.status,
                "error": row.error,
                "retry_count": row.retry_count,
            }
            for row in source_logs
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Load missing API/core dates into dev PostgreSQL.")
    parser.add_argument("--date-from", type=_parse_date, default=DEFAULT_DATE_FROM)
    parser.add_argument("--date-to", type=_parse_date, default=DEFAULT_DATE_TO)
    parser.add_argument("--full-range-from", type=_parse_date, default=DEFAULT_FULL_RANGE_FROM)
    parser.add_argument("--full-range-to", type=_parse_date, default=DEFAULT_FULL_RANGE_TO)
    parser.add_argument("--fullstats-sleep-seconds", type=int, default=FULLSTATS_SLEEP_SECONDS)
    parser.add_argument("--tracked-products", action="store_true")
    parser.add_argument("--force-fullstats-refresh", action="store_true")
    parser.add_argument("--retry-failed-fullstats-only", action="store_true")
    parser.add_argument("--fullstats-only", action="store_true")
    args = parser.parse_args()

    if args.date_from > args.date_to:
        raise SystemExit("--date-from must be <= --date-to")
    if args.full_range_from > args.full_range_to:
        raise SystemExit("--full-range-from must be <= --full-range-to")
    if args.fullstats_sleep_seconds < 1:
        raise SystemExit("--fullstats-sleep-seconds must be >= 1")

    summary = run_missing_core_dates_load(
        date_from=args.date_from,
        date_to=args.date_to,
        full_range_from=args.full_range_from,
        full_range_to=args.full_range_to,
        fullstats_sleep_seconds=args.fullstats_sleep_seconds,
        use_tracked_products=bool(args.tracked_products),
        force_fullstats_refresh=bool(args.force_fullstats_refresh),
        retry_failed_fullstats_only=bool(args.retry_failed_fullstats_only),
        fullstats_only=bool(args.fullstats_only),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary.get("failed_chunks") else 0


if __name__ == "__main__":
    raise SystemExit(main())
