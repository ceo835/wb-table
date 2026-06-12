#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import distinct, func, or_, select


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.export_streamlit_v1_dataset import export_streamlit_v1_dataset
from src.db.ad_campaign_loader import load_ad_campaign_stats_to_db
from src.db.ad_cost_loader import load_ad_costs_to_db
from src.db.funnel_loader import load_funnel_to_db
from src.db.mart_total_report_builder import build_mart_total_report
from src.db.models import (
    FactAdCampaignNmDay,
    FactAdCostDay,
    FactAdCostEvent,
    FactFunnelDay,
    FactSearchQueryMetric,
    FactStockSnapshot,
    MartTotalReport,
    SettingsProducts,
)
from src.db.search_query_loader import load_search_queries_to_db
from src.db.session import session_scope
from src.db.stock_loader import load_stocks_to_db


DEFAULT_DATE_FROM = date(2026, 5, 1)
DEFAULT_DATE_TO = date(2026, 6, 7)
DEFAULT_FUNNEL_CHUNK_SIZE = 20
DEFAULT_FUNNEL_WINDOW_DAYS = 7
DEFAULT_SEARCH_CHUNK_SIZE = 20
DEFAULT_STOCK_CHUNK_SIZE = 50
DEFAULT_SEARCH_SLEEP_SECONDS = 20
DEFAULT_FUNNEL_SLEEP_SECONDS = 20
DEFAULT_STOCK_SLEEP_SECONDS = 5
DEFAULT_FULLSTATS_SLEEP_SECONDS = 60
DEFAULT_FULLSTATS_MAX_DAYS = 31
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
RUNTIME_SUMMARY_PATH = PROCESSED_DIR / "api_backfill_runtime_summary.json"
FAILED_CHUNKS_PATH = PROCESSED_DIR / "api_backfill_failed_chunks.json"
SUPPORTED_SOURCES = ("funnel", "search", "stocks", "ad_cost", "fullstats")

TARGET_METRIC_FIELDS = (
    "impressions",
    "card_clicks",
    "cart_count",
    "order_count",
    "order_sum",
    "ad_campaign_spend_total",
    "ad_views_total",
    "ad_clicks_total",
    "ad_atbs_total",
    "ad_orders_total",
    "current_stock_qty",
    "current_mp_stock_qty",
    "search_queries_count",
    "local_orders_percent",
)


@dataclass(slots=True)
class ChunkLogRow:
    source_name: str
    report_date: str
    chunk_number: int
    item_count: int
    nm_ids: list[int]
    advert_id: int | None
    rows_fetched: int
    rows_upserted: int
    status: str
    error_type: str
    error: str
    retry_count: int
    started_at: str
    finished_at: str


def _empty_failure_reason_counts() -> dict[str, int]:
    return {
        "429": 0,
        "500": 0,
        "TIMEOUT": 0,
        "API_DATE_LIMIT": 0,
        "REQUEST_ERROR": 0,
        "EMPTY_RESPONSE": 0,
        "NO_DATA": 0,
        "FAILED_PAGES": 0,
        "FAILED_CHUNK": 0,
    }


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _normalize_sources(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return SUPPORTED_SOURCES
    normalized: list[str] = []
    for value in values:
        source = str(value).strip().lower()
        if source not in SUPPORTED_SOURCES:
            raise ValueError(f"Unsupported source: {value}")
        if source not in normalized:
            normalized.append(source)
    return tuple(normalized)


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value != value


def _row_has_target_metric(row: Mapping[str, Any]) -> bool:
    return any(not _is_missing(row.get(field)) for field in TARGET_METRIC_FIELDS)


def _safe_fullstats_date(today: date | None = None) -> date:
    current = today or datetime.now(timezone.utc).date()
    return current - timedelta(days=2)


def _split_date_windows(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    if start > end:
        return []
    if max_days <= 0:
        raise ValueError("max_days must be positive")
    windows: list[tuple[date, date]] = []
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=max_days - 1), end)
        windows.append((current, window_end))
        current = window_end + timedelta(days=1)
    return windows


def _resolve_window_bounds(item: Mapping[str, Any]) -> tuple[date, date]:
    window_start_text = item.get("window_start")
    window_end_text = item.get("window_end")
    if window_start_text and window_end_text:
        return date.fromisoformat(str(window_start_text)), date.fromisoformat(str(window_end_text))
    report_date = str(item.get("report_date") or "")
    if ".." in report_date:
        start_text, end_text = report_date.split("..", 1)
        return date.fromisoformat(start_text), date.fromisoformat(end_text)
    day = date.fromisoformat(report_date)
    return day, day


def _daterange(start: date, end: date) -> list[date]:
    values: list[date] = []
    current = start
    while current <= end:
        values.append(current)
        current += timedelta(days=1)
    return values


def _chunked(values: Sequence[int], size: int) -> list[list[int]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [list(values[index:index + size]) for index in range(0, len(values), size)]


def _load_active_nm_ids() -> list[int]:
    with session_scope() as session:
        rows = session.execute(
            select(SettingsProducts.nm_id)
            .where(SettingsProducts.active.is_(True))
            .order_by(SettingsProducts.nm_id)
        ).all()
    return [int(row[0]) for row in rows if row[0] is not None]


def _load_reference_index(nm_ids: Sequence[int]) -> dict[int, dict[str, str]]:
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
        ).all()
    return {
        int(row.nm_id): {
            "supplier_article": row.supplier_article or "",
            "title": row.title or "",
            "subject": row.subject or "",
            "brand": row.brand or "",
        }
        for row in rows
        if row.nm_id is not None
    }


def _load_target_nm_ids_from_mart(start: date, end: date) -> list[int]:
    metric_conditions = [getattr(MartTotalReport, field).is_not(None) for field in TARGET_METRIC_FIELDS]
    with session_scope() as session:
        rows = session.execute(
            select(distinct(MartTotalReport.nm_id))
            .where(
                MartTotalReport.report_date >= start,
                MartTotalReport.report_date <= end,
                or_(*metric_conditions),
            )
            .order_by(MartTotalReport.nm_id)
        ).all()
    return [int(row[0]) for row in rows if row[0] is not None]


def _error_type_from_text(error_text: str) -> str:
    normalized = (error_text or "").lower()
    if not normalized:
        return ""
    if (
        "invalid start day: excess limit on days" in normalized
        or "invalid start day: excess limit" in normalized
        or "excess limit on days" in normalized
        or "max date range 31 days" in normalized
    ):
        return "API_DATE_LIMIT"
    if re.search(r"(^|[^0-9])429([^0-9]|$)", normalized) or "code=429" in normalized:
        return "429"
    if re.search(r"(^|[^0-9])500([^0-9]|$)", normalized) or "code=500" in normalized:
        return "500"
    if "timeout" in normalized or "timed out" in normalized:
        return "TIMEOUT"
    if "request" in normalized or "connection" in normalized:
        return "REQUEST_ERROR"
    return "FAILED_CHUNK"


def _is_retryable_error(error_type: str) -> bool:
    return error_type in {"429", "500", "TIMEOUT", "REQUEST_ERROR"}


def _status_from_result(source_name: str, result: Mapping[str, Any], error_text: str) -> tuple[str, str]:
    if error_text:
        return "FAILED_CHUNK", _error_type_from_text(error_text)
    if source_name == "search":
        if result.get("current_failed_pages") or result.get("prev_failed_pages"):
            return "FAILED_PAGES", "FAILED_PAGES"
        if int(result.get("rows_fetched", 0) or 0) == 0:
            return "NO_DATA", "NO_DATA"
        return "OK", ""
    if source_name == "stocks":
        if result.get("failed_pages"):
            return "FAILED_PAGES", "FAILED_PAGES"
        if int(result.get("rows_fetched", 0) or 0) == 0:
            return "EMPTY_RESPONSE", "EMPTY_RESPONSE"
        return "OK", ""
    if source_name == "funnel":
        if int(result.get("rows_fetched", 0) or 0) == 0:
            return "NO_DATA", "NO_DATA"
        return "OK", ""
    if source_name == "ad_cost":
        rows_fetched = int(result.get("event_rows_fetched", 0) or 0) + int(result.get("day_rows_built", 0) or 0)
        if rows_fetched == 0:
            return "NO_DATA", "NO_DATA"
        return "OK", ""
    if source_name == "fullstats":
        rows_fetched = int(result.get("nm_rows_fetched", 0) or 0) + int(result.get("campaign_rows_fetched", 0) or 0)
        if rows_fetched == 0:
            return "NO_DATA", "NO_DATA"
        return "OK", ""
    return "OK", ""


def _distinct_nm_ids(model, column, *conditions: Any) -> set[int]:
    with session_scope() as session:
        rows = session.execute(select(distinct(column)).where(*conditions)).all()
    return {int(row[0]) for row in rows if row[0] is not None}


def _meaningful_funnel_nm_ids(start: date, end: date, nm_ids: Sequence[int]) -> set[int]:
    with session_scope() as session:
        rows = session.execute(
            select(distinct(FactFunnelDay.nm_id)).where(
                FactFunnelDay.date >= start,
                FactFunnelDay.date <= end,
                FactFunnelDay.nm_id.in_(list(nm_ids)),
                or_(
                    FactFunnelDay.card_clicks.is_not(None),
                    FactFunnelDay.cart_count.is_not(None),
                    FactFunnelDay.order_count.is_not(None),
                    FactFunnelDay.order_sum.is_not(None),
                    FactFunnelDay.add_to_cart_conversion.is_not(None),
                    FactFunnelDay.cart_to_order_conversion.is_not(None),
                    FactFunnelDay.buyout_count.is_not(None),
                    FactFunnelDay.buyout_sum.is_not(None),
                ),
            )
        ).all()
    return {int(row[0]) for row in rows if row[0] is not None}


def _source_sets(start: date, end: date, nm_ids: Sequence[int]) -> dict[str, set[int]]:
    scoped = list(nm_ids)
    return {
        "funnel": _meaningful_funnel_nm_ids(start, end, scoped),
        "search": _distinct_nm_ids(
            FactSearchQueryMetric,
            FactSearchQueryMetric.nm_id,
            FactSearchQueryMetric.period_start >= start,
            FactSearchQueryMetric.period_end <= end,
            FactSearchQueryMetric.nm_id.in_(scoped),
        ),
        "stocks": _distinct_nm_ids(
            FactStockSnapshot,
            FactStockSnapshot.nm_id,
            FactStockSnapshot.snapshot_date >= start,
            FactStockSnapshot.snapshot_date <= end,
            FactStockSnapshot.nm_id.in_(scoped),
        ),
        "ad_cost": _distinct_nm_ids(
            FactAdCostDay,
            FactAdCostDay.nm_id,
            FactAdCostDay.date >= start,
            FactAdCostDay.date <= end,
            FactAdCostDay.nm_id.in_(scoped),
        ),
        "fullstats": _distinct_nm_ids(
            FactAdCampaignNmDay,
            FactAdCampaignNmDay.nm_id,
            FactAdCampaignNmDay.date >= start,
            FactAdCampaignNmDay.date <= end,
            FactAdCampaignNmDay.nm_id.in_(scoped),
        ),
    }


def _coverage_snapshot(
    *,
    start: date,
    end: date,
    active_nm_ids: Sequence[int],
    target_nm_ids: Sequence[int],
) -> dict[str, Any]:
    active_sets = _source_sets(start, end, active_nm_ids)
    target_sets = _source_sets(start, end, target_nm_ids)

    def _scope_summary(scope_nm_ids: Sequence[int], source_sets: Mapping[str, set[int]]) -> dict[str, Any]:
        base_set = set(scope_nm_ids)
        union_any = set().union(*source_sets.values()) if source_sets else set()
        sparse_count = 0
        for nm_id in base_set:
            source_hits = sum(1 for values in source_sets.values() if nm_id in values)
            if source_hits <= 1:
                sparse_count += 1
        return {
            "products_total": len(base_set),
            "funnel_coverage": len(source_sets["funnel"]),
            "search_coverage": len(source_sets["search"]),
            "stock_coverage": len(source_sets["stocks"]),
            "ads_coverage": len(source_sets["fullstats"]),
            "ad_cost_coverage": len(source_sets["ad_cost"]),
            "with_any_metric": len(union_any),
            "without_any_metric": len(base_set - union_any),
            "almost_empty_count": sparse_count,
        }

    return {
        "active": _scope_summary(active_nm_ids, active_sets),
        "target": _scope_summary(target_nm_ids, target_sets),
    }


def _persist_runtime_state(state: Mapping[str, Any]) -> None:
    RUNTIME_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_SUMMARY_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    FAILED_CHUNKS_PATH.write_text(json.dumps(state.get("failed_chunks", []), ensure_ascii=False, indent=2), encoding="utf-8")


def _load_failed_chunks() -> list[dict[str, Any]]:
    if not FAILED_CHUNKS_PATH.exists():
        return []
    return json.loads(FAILED_CHUNKS_PATH.read_text(encoding="utf-8"))


def _load_runtime_state() -> dict[str, Any] | None:
    if not RUNTIME_SUMMARY_PATH.exists():
        return None
    return json.loads(RUNTIME_SUMMARY_PATH.read_text(encoding="utf-8"))


def _build_failed_chunk_record(
    *,
    source_name: str,
    report_date: str,
    chunk_number: int,
    nm_ids: Sequence[int],
    advert_id: int | None,
    status: str,
    error_type: str,
    error: str,
) -> dict[str, Any]:
    return {
        "source_name": source_name,
        "report_date": report_date,
        "chunk_number": chunk_number,
        "nm_ids": list(nm_ids),
        "advert_id": advert_id,
        "status": status,
        "error_type": error_type,
        "error": error,
    }


def _run_with_retry(
    *,
    source_name: str,
    report_date: str,
    chunk_number: int,
    nm_ids: Sequence[int],
    advert_id: int | None,
    loader: Any,
    rows_fetched_key: str,
    rows_upserted_key: str,
    max_retries: int,
    retry_sleep_seconds: int,
) -> tuple[dict[str, Any], ChunkLogRow, dict[str, Any] | None]:
    started_at = _now_utc()
    retry_count = 0
    result: dict[str, Any] = {}
    error_text = ""
    status = "FAILED_CHUNK"
    error_type = ""
    while True:
        try:
            result = loader()
            status, error_type = _status_from_result(source_name, result, "")
            error_text = ""
            break
        except Exception as exc:
            error_text = str(exc)
            error_type = _error_type_from_text(error_text)
            status = "FAILED_CHUNK"
            if not _is_retryable_error(error_type) or retry_count >= max_retries:
                break
            retry_count += 1
            time.sleep(retry_sleep_seconds * retry_count)

    finished_at = _now_utc()
    log_row = ChunkLogRow(
        source_name=source_name,
        report_date=report_date,
        chunk_number=chunk_number,
        item_count=len(nm_ids),
        nm_ids=list(nm_ids),
        advert_id=advert_id,
        rows_fetched=int(result.get(rows_fetched_key, 0) or 0),
        rows_upserted=int(result.get(rows_upserted_key, 0) or 0),
        status=status,
        error_type=error_type,
        error=error_text,
        retry_count=retry_count,
        started_at=started_at,
        finished_at=finished_at,
    )
    failed_record = None
    if log_row.status != "OK":
        failed_record = _build_failed_chunk_record(
            source_name=source_name,
            report_date=report_date,
            chunk_number=chunk_number,
            nm_ids=nm_ids,
            advert_id=advert_id,
            status=log_row.status,
            error_type=log_row.error_type,
            error=log_row.error,
        )
    return result, log_row, failed_record


def _append_log(state: dict[str, Any], log_row: ChunkLogRow, failed_record: dict[str, Any] | None) -> None:
    state["source_logs"].append(asdict(log_row))
    if failed_record is not None:
        state["failed_chunks"].append(failed_record)
    if log_row.error_type:
        state["failure_reason_counts"][log_row.error_type] = int(state["failure_reason_counts"].get(log_row.error_type, 0) or 0) + 1
    elif failed_record is not None:
        state["failure_reason_counts"]["FAILED_CHUNK"] = int(state["failure_reason_counts"].get("FAILED_CHUNK", 0) or 0) + 1
    if log_row.status in {"NO_DATA", "EMPTY_RESPONSE", "FAILED_PAGES"}:
        state["failure_reason_counts"][log_row.status] = int(state["failure_reason_counts"].get(log_row.status, 0) or 0) + 1
    summary = state["summary_by_source"].setdefault(
        log_row.source_name,
        {"runs": 0, "rows_fetched": 0, "rows_upserted": 0, "status_counts": {}},
    )
    summary["runs"] += 1
    summary["rows_fetched"] += log_row.rows_fetched
    summary["rows_upserted"] += log_row.rows_upserted
    summary["status_counts"][log_row.status] = int(summary["status_counts"].get(log_row.status, 0) or 0) + 1


def _parse_resume_chunks(failed_chunks: Sequence[Mapping[str, Any]], source_name: str) -> list[dict[str, Any]]:
    return [dict(item) for item in failed_chunks if item.get("source_name") == source_name]


def _resumable_statuses() -> set[str]:
    return {"OK", "NO_DATA", "EMPTY_RESPONSE"}


def _chunk_key(
    *,
    source_name: str,
    report_date: str,
    chunk_number: int,
    advert_id: int | None = None,
) -> tuple[str, str, int, int | None]:
    return (source_name, report_date, chunk_number, advert_id)


def _completed_chunk_keys(state: Mapping[str, Any], source_name: str) -> set[tuple[str, str, int, int | None]]:
    completed: set[tuple[str, str, int, int | None]] = set()
    for row in state.get("source_logs", []):
        if row.get("source_name") != source_name:
            continue
        if str(row.get("status") or "") not in _resumable_statuses():
            continue
        completed.add(
            _chunk_key(
                source_name=source_name,
                report_date=str(row.get("report_date")),
                chunk_number=int(row.get("chunk_number", 0) or 0),
                advert_id=int(row["advert_id"]) if row.get("advert_id") is not None else None,
            )
        )
    return completed


def _filter_already_completed_plan(
    plan: Sequence[Mapping[str, Any]],
    *,
    source_name: str,
    completed_keys: set[tuple[str, str, int, int | None]],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in plan:
        key = _chunk_key(
            source_name=source_name,
            report_date=str(item.get("report_date")),
            chunk_number=int(item.get("chunk_number", 0) or 0),
            advert_id=int(item["advert_id"]) if item.get("advert_id") is not None else None,
        )
        if key in completed_keys:
            continue
        filtered.append(dict(item))
    return filtered


def _load_ad_event_groups(start: date, end: date, nm_ids: Sequence[int]) -> list[tuple[int, list[dict[str, Any]]]]:
    with session_scope() as session:
        rows = session.execute(
            select(
                FactAdCostEvent.advert_id,
                FactAdCostEvent.campaign_name,
                FactAdCostEvent.nm_id,
            ).where(
                FactAdCostEvent.date >= start,
                FactAdCostEvent.date <= end,
                FactAdCostEvent.nm_id.in_(list(nm_ids)),
                FactAdCostEvent.advert_id.is_not(None),
            )
        ).all()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        advert_id = int(row.advert_id)
        grouped[advert_id].append(
            {
                "advertId": advert_id,
                "campaign_name": row.campaign_name,
                "nm_id": int(row.nm_id),
            }
        )
    return [(advert_id, grouped[advert_id]) for advert_id in sorted(grouped)]


def _target_missing_reason_map(
    *,
    target_nm_ids: Sequence[int],
    failed_chunks: Sequence[Mapping[str, Any]],
    start: date,
    end: date,
) -> dict[str, list[str]]:
    source_sets = _source_sets(start, end, target_nm_ids)
    reasons: dict[str, list[str]] = {}
    for nm_id in target_nm_ids:
        nm_reasons: list[str] = []
        for source_name in ("funnel", "search", "stocks", "fullstats"):
            if nm_id in source_sets[source_name]:
                continue
            matching_failures = [
                failed
                for failed in failed_chunks
                if failed.get("source_name") == source_name and nm_id in {int(value) for value in failed.get("nm_ids", [])}
            ]
            if matching_failures:
                statuses = sorted({str(item.get("error_type") or item.get("status") or "FAILED_CHUNK") for item in matching_failures})
                nm_reasons.append(f"{source_name}: {', '.join(statuses)}")
            else:
                nm_reasons.append(f"{source_name}: no_data")
        if nm_reasons:
            reasons[str(nm_id)] = nm_reasons
    return reasons


def _build_initial_state(
    *,
    date_from: date,
    date_to: date,
    active_nm_ids: Sequence[int],
    target_nm_ids: Sequence[int],
    resume_failed_only: bool,
    before_coverage: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "started_at": _now_utc(),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "active_products_count": len(active_nm_ids),
        "target_products_count": len(target_nm_ids),
        "resume_failed_only": resume_failed_only,
        "before_coverage": before_coverage,
        "source_logs": [],
        "failed_chunks": [],
        "summary_by_source": {},
        "failure_reason_counts": _empty_failure_reason_counts(),
    }


def run_backfill(
    *,
    date_from: date,
    date_to: date,
    funnel_chunk_size: int,
    funnel_window_days: int,
    search_chunk_size: int,
    stock_chunk_size: int,
    fullstats_sleep_seconds: int,
    resume_failed_only: bool,
    sources: Sequence[str] | None,
) -> dict[str, Any]:
    selected_sources = _normalize_sources(sources)
    active_nm_ids = _load_active_nm_ids()
    target_nm_ids = _load_target_nm_ids_from_mart(date_from, date_to)
    if not target_nm_ids:
        raise RuntimeError("Не удалось сформировать target nm_id из mart_total_report.")
    reference_index = _load_reference_index(target_nm_ids)
    before_coverage = _coverage_snapshot(
        start=date_from,
        end=date_to,
        active_nm_ids=active_nm_ids,
        target_nm_ids=target_nm_ids,
    )
    existing_state = _load_runtime_state()
    resume_completed_chunks = (
        not resume_failed_only
        and existing_state is not None
        and not existing_state.get("finished_at")
        and existing_state.get("date_from") == date_from.isoformat()
        and existing_state.get("date_to") == date_to.isoformat()
        and list(existing_state.get("sources_requested") or []) == list(selected_sources)
    )
    failed_chunks_to_resume = _load_failed_chunks() if resume_failed_only else []
    if resume_completed_chunks:
        state = dict(existing_state)
        state["resumed_at"] = _now_utc()
        state["resume_failed_only"] = resume_failed_only
        state["before_coverage"] = before_coverage
        state["active_products_count"] = len(active_nm_ids)
        state["target_products_count"] = len(target_nm_ids)
        state["source_logs"] = list(state.get("source_logs", []))
        state["failed_chunks"] = list(state.get("failed_chunks", []))
        state["summary_by_source"] = dict(state.get("summary_by_source", {}))
        state["failure_reason_counts"] = {
            **_empty_failure_reason_counts(),
            **dict(state.get("failure_reason_counts", {})),
        }
    else:
        state = _build_initial_state(
            date_from=date_from,
            date_to=date_to,
            active_nm_ids=active_nm_ids,
            target_nm_ids=target_nm_ids,
            resume_failed_only=resume_failed_only,
            before_coverage=before_coverage,
        )
        state["sources_requested"] = list(selected_sources)
        if resume_failed_only:
            state["resume_failed_chunks_loaded"] = len(failed_chunks_to_resume)
    _persist_runtime_state(state)

    search_failed = _parse_resume_chunks(failed_chunks_to_resume, "search")
    stocks_failed = _parse_resume_chunks(failed_chunks_to_resume, "stocks")
    funnel_failed = _parse_resume_chunks(failed_chunks_to_resume, "funnel")
    ad_cost_failed = _parse_resume_chunks(failed_chunks_to_resume, "ad_cost")
    fullstats_failed = _parse_resume_chunks(failed_chunks_to_resume, "fullstats")

    if "search" in selected_sources:
        search_plan = search_failed if resume_failed_only else [
            {"report_date": report_date.isoformat(), "chunk_number": index, "nm_ids": chunk}
            for report_date in _daterange(date_from, date_to)
            for index, chunk in enumerate(_chunked(target_nm_ids, search_chunk_size), start=1)
        ]
        if resume_completed_chunks:
            search_plan = _filter_already_completed_plan(
                search_plan,
                source_name="search",
                completed_keys=_completed_chunk_keys(state, "search"),
            )
        for item in search_plan:
            report_date = date.fromisoformat(str(item["report_date"]))
            start_day = report_date - timedelta(days=1)
            chunk_nm_ids = [int(value) for value in item.get("nm_ids", [])]
            result, log_row, failed_record = _run_with_retry(
                source_name="search",
                report_date=report_date.isoformat(),
                chunk_number=int(item.get("chunk_number", 1) or 1),
                nm_ids=chunk_nm_ids,
                advert_id=None,
                loader=lambda start_day=start_day, report_date=report_date, chunk_nm_ids=chunk_nm_ids: load_search_queries_to_db(
                    start_day,
                    report_date,
                    nm_ids=chunk_nm_ids,
                    reference_index={nm_id: reference_index[nm_id] for nm_id in chunk_nm_ids if nm_id in reference_index},
                ),
                rows_fetched_key="rows_fetched",
                rows_upserted_key="rows_upserted",
                max_retries=3,
                retry_sleep_seconds=20,
            )
            _append_log(state, log_row, failed_record)
            _persist_runtime_state(state)
            if failed_record is None and log_row.status == "OK":
                time.sleep(DEFAULT_SEARCH_SLEEP_SECONDS)

    if "stocks" in selected_sources:
        stocks_plan = stocks_failed if resume_failed_only else [
            {"report_date": report_date.isoformat(), "chunk_number": index, "nm_ids": chunk}
            for report_date in _daterange(date_from, date_to)
            for index, chunk in enumerate(_chunked(target_nm_ids, stock_chunk_size), start=1)
        ]
        if resume_completed_chunks:
            stocks_plan = _filter_already_completed_plan(
                stocks_plan,
                source_name="stocks",
                completed_keys=_completed_chunk_keys(state, "stocks"),
            )
        for item in stocks_plan:
            report_date = date.fromisoformat(str(item["report_date"]))
            chunk_nm_ids = [int(value) for value in item.get("nm_ids", [])]
            result, log_row, failed_record = _run_with_retry(
                source_name="stocks",
                report_date=report_date.isoformat(),
                chunk_number=int(item.get("chunk_number", 1) or 1),
                nm_ids=chunk_nm_ids,
                advert_id=None,
                loader=lambda report_date=report_date, chunk_nm_ids=chunk_nm_ids: load_stocks_to_db(report_date, nm_ids=chunk_nm_ids),
                rows_fetched_key="rows_fetched",
                rows_upserted_key="rows_upserted",
                max_retries=3,
                retry_sleep_seconds=15,
            )
            _append_log(state, log_row, failed_record)
            _persist_runtime_state(state)
            if failed_record is None and log_row.status == "OK":
                time.sleep(DEFAULT_STOCK_SLEEP_SECONDS)

    if "funnel" in selected_sources:
        funnel_plan = funnel_failed if resume_failed_only else [
            {
                "report_date": f"{window_start.isoformat()}..{window_end.isoformat()}",
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "chunk_number": index,
                "nm_ids": chunk,
            }
            for window_start, window_end in _split_date_windows(date_from, date_to, funnel_window_days)
            for index, chunk in enumerate(_chunked(target_nm_ids, funnel_chunk_size), start=1)
        ]
        if resume_completed_chunks:
            funnel_plan = _filter_already_completed_plan(
                funnel_plan,
                source_name="funnel",
                completed_keys=_completed_chunk_keys(state, "funnel"),
            )
        for item in funnel_plan:
            window_start, window_end = _resolve_window_bounds(item)
            chunk_nm_ids = [int(value) for value in item.get("nm_ids", [])]
            result, log_row, failed_record = _run_with_retry(
                source_name="funnel",
                report_date=str(item["report_date"]),
                chunk_number=int(item.get("chunk_number", 1) or 1),
                nm_ids=chunk_nm_ids,
                advert_id=None,
                loader=lambda window_start=window_start, window_end=window_end, chunk_nm_ids=chunk_nm_ids: load_funnel_to_db(
                    window_start,
                    window_end,
                    nm_ids=chunk_nm_ids,
                ),
                rows_fetched_key="rows_fetched",
                rows_upserted_key="rows_upserted",
                max_retries=1,
                retry_sleep_seconds=20,
            )
            _append_log(state, log_row, failed_record)
            _persist_runtime_state(state)
            if failed_record is None and log_row.status == "OK":
                time.sleep(DEFAULT_FUNNEL_SLEEP_SECONDS)

    if "ad_cost" in selected_sources:
        ad_cost_plan = ad_cost_failed if resume_failed_only else [
            {"report_date": report_date.isoformat(), "chunk_number": 1, "nm_ids": target_nm_ids}
            for report_date in _daterange(date_from, date_to)
        ]
        if resume_completed_chunks:
            ad_cost_plan = _filter_already_completed_plan(
                ad_cost_plan,
                source_name="ad_cost",
                completed_keys=_completed_chunk_keys(state, "ad_cost"),
            )
        for item in ad_cost_plan:
            report_date = date.fromisoformat(str(item["report_date"]))
            chunk_nm_ids = [int(value) for value in item.get("nm_ids", [])]
            result, log_row, failed_record = _run_with_retry(
                source_name="ad_cost",
                report_date=report_date.isoformat(),
                chunk_number=1,
                nm_ids=chunk_nm_ids,
                advert_id=None,
                loader=lambda report_date=report_date, chunk_nm_ids=chunk_nm_ids: load_ad_costs_to_db(report_date, report_date, nm_ids=chunk_nm_ids),
                rows_fetched_key="event_rows_fetched",
                rows_upserted_key="event_rows_upserted",
                max_retries=3,
                retry_sleep_seconds=15,
            )
            _append_log(state, log_row, failed_record)
            _persist_runtime_state(state)

    safe_fullstats_end = min(date_to, _safe_fullstats_date())
    if "fullstats" in selected_sources:
        windows = _split_date_windows(date_from, safe_fullstats_end, DEFAULT_FULLSTATS_MAX_DAYS) if safe_fullstats_end >= date_from else []
        fullstats_plan = fullstats_failed if resume_failed_only else []
        if not resume_failed_only:
            for window_start, window_end in windows:
                ad_event_groups = _load_ad_event_groups(window_start, window_end, target_nm_ids)
                for index, (advert_id, rows) in enumerate(ad_event_groups, start=1):
                    fullstats_plan.append(
                        {
                            "report_date": f"{window_start.isoformat()}..{window_end.isoformat()}",
                            "window_start": window_start.isoformat(),
                            "window_end": window_end.isoformat(),
                            "chunk_number": index,
                            "advert_id": advert_id,
                            "nm_ids": sorted({int(row['nm_id']) for row in rows if row.get('nm_id') is not None}),
                        }
                    )
        if resume_completed_chunks:
            fullstats_plan = _filter_already_completed_plan(
                fullstats_plan,
                source_name="fullstats",
                completed_keys=_completed_chunk_keys(state, "fullstats"),
            )
        grouped_rows_by_window: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
        if fullstats_plan:
            if resume_failed_only:
                for item in fullstats_plan:
                    window_start_text = str(item.get("window_start") or str(item["report_date"]).split("..", 1)[0])
                    window_end_text = str(item.get("window_end") or str(item["report_date"]).split("..", 1)[1])
                    advert_id = int(item["advert_id"])
                    key = (window_start_text, window_end_text, advert_id)
                    if key in grouped_rows_by_window:
                        continue
                    for loaded_advert_id, rows in _load_ad_event_groups(date.fromisoformat(window_start_text), date.fromisoformat(window_end_text), target_nm_ids):
                        grouped_rows_by_window[(window_start_text, window_end_text, loaded_advert_id)] = rows
            else:
                for window_start, window_end in windows:
                    for advert_id, rows in _load_ad_event_groups(window_start, window_end, target_nm_ids):
                        grouped_rows_by_window[(window_start.isoformat(), window_end.isoformat(), advert_id)] = rows

        for item in fullstats_plan:
            advert_id = int(item["advert_id"])
            window_start_text = str(item.get("window_start") or str(item["report_date"]).split("..", 1)[0])
            window_end_text = str(item.get("window_end") or str(item["report_date"]).split("..", 1)[1])
            window_start = date.fromisoformat(window_start_text)
            window_end = date.fromisoformat(window_end_text)
            chunk_nm_ids = [int(value) for value in item.get("nm_ids", [])]
            ad_event_rows = grouped_rows_by_window.get((window_start.isoformat(), window_end.isoformat(), advert_id), [])
            result, log_row, failed_record = _run_with_retry(
                source_name="fullstats",
                report_date=str(item["report_date"]),
                chunk_number=int(item.get("chunk_number", 1) or 1),
                nm_ids=chunk_nm_ids,
                advert_id=advert_id,
                loader=lambda window_start=window_start, window_end=window_end, chunk_nm_ids=chunk_nm_ids, ad_event_rows=ad_event_rows: load_ad_campaign_stats_to_db(
                    window_start,
                    window_end,
                    nm_ids=chunk_nm_ids,
                    ad_event_rows=ad_event_rows,
                ),
                rows_fetched_key="nm_rows_fetched",
                rows_upserted_key="nm_rows_upserted",
                max_retries=1,
                retry_sleep_seconds=20,
            )
            _append_log(state, log_row, failed_record)
            _persist_runtime_state(state)
            if failed_record is None and log_row.status == "OK":
                time.sleep(fullstats_sleep_seconds)

    mart_summary = build_mart_total_report(date_from, date_to, version="v2")
    streamlit_summary = export_streamlit_v1_dataset(date_from, date_to)
    after_coverage = _coverage_snapshot(
        start=date_from,
        end=date_to,
        active_nm_ids=active_nm_ids,
        target_nm_ids=target_nm_ids,
    )
    unresolved_by_nm = _target_missing_reason_map(
        target_nm_ids=target_nm_ids,
        failed_chunks=state["failed_chunks"],
        start=date_from,
        end=date_to,
    )
    sources_requiring_file = sorted(
        {
            failed.get("source_name")
            for failed in state["failed_chunks"]
            if failed.get("error_type") == "API_DATE_LIMIT"
        }
    )
    state["target_nm_ids"] = target_nm_ids
    state["target_products_processed"] = len(target_nm_ids)
    state["safe_fullstats_end"] = safe_fullstats_end.isoformat() if safe_fullstats_end >= date_from else None
    state["after_coverage"] = after_coverage
    state["mart_summary"] = mart_summary
    state["streamlit_dataset_summary"] = streamlit_summary
    state["nm_ids_not_fully_closed"] = unresolved_by_nm
    state["sources_requiring_file"] = sources_requiring_file
    state["finished_at"] = _now_utc()
    _persist_runtime_state(state)
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill WB API data for target products derived from mart_total_report.")
    parser.add_argument("--date-from", type=_parse_date, default=DEFAULT_DATE_FROM)
    parser.add_argument("--date-to", type=_parse_date, default=DEFAULT_DATE_TO)
    parser.add_argument("--funnel-chunk-size", type=int, default=DEFAULT_FUNNEL_CHUNK_SIZE)
    parser.add_argument("--funnel-window-days", type=int, default=DEFAULT_FUNNEL_WINDOW_DAYS)
    parser.add_argument("--search-chunk-size", type=int, default=DEFAULT_SEARCH_CHUNK_SIZE)
    parser.add_argument("--stock-chunk-size", type=int, default=DEFAULT_STOCK_CHUNK_SIZE)
    parser.add_argument("--fullstats-sleep-seconds", type=int, default=DEFAULT_FULLSTATS_SLEEP_SECONDS)
    parser.add_argument("--resume-failed-only", action="store_true")
    parser.add_argument("--sources", nargs="+", choices=list(SUPPORTED_SOURCES))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.date_from > args.date_to:
        raise SystemExit("--date-from must be <= --date-to")
    summary = run_backfill(
        date_from=args.date_from,
        date_to=args.date_to,
        funnel_chunk_size=args.funnel_chunk_size,
        funnel_window_days=args.funnel_window_days,
        search_chunk_size=args.search_chunk_size,
        stock_chunk_size=args.stock_chunk_size,
        fullstats_sleep_seconds=args.fullstats_sleep_seconds,
        resume_failed_only=args.resume_failed_only,
        sources=args.sources,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary.get("failed_chunks") else 0


if __name__ == "__main__":
    raise SystemExit(main())
