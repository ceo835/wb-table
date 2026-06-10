from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from sqlalchemy import distinct, func, select

from src.db.ad_campaign_loader import load_ad_campaign_stats_to_db
from src.db.ad_cost_loader import (
    count_fact_ad_cost_day_duplicates,
    count_fact_ad_cost_day_rows,
    count_fact_ad_cost_event_duplicates,
    count_fact_ad_cost_event_rows,
    load_ad_costs_to_db,
)
from src.db.funnel_loader import count_fact_funnel_day_duplicates, count_fact_funnel_day_rows, load_funnel_to_db
from src.db.localization_loader import (
    count_fact_localization_region_day_duplicates,
    count_fact_localization_region_day_rows,
    load_localization_to_db,
)
from src.db.models import (
    FactAdCampaignDay,
    FactAdCampaignNmDay,
    FactAdCostDay,
    FactAdCostEvent,
    FactFunnelDay,
    FactLocalizationRegionDay,
    FactSearchQueryMetric,
    FactStockSnapshot,
    SettingsProducts,
)
from src.db.search_query_loader import (
    count_fact_search_query_metric_duplicates,
    count_fact_search_query_metric_rows,
    load_search_queries_to_db,
)
from src.db.session import session_scope
from src.db.stock_loader import count_fact_stock_snapshot_duplicates, count_fact_stock_snapshot_rows, load_stocks_to_db


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data" / "processed"
LOG_CSV_PATH = DATA_DIR / "backfill_active_products_2days_log.csv"
SUMMARY_JSON_PATH = DATA_DIR / "backfill_active_products_2days_summary.json"

DATE_FROM = date(2026, 5, 31)
DATE_TO = date(2026, 6, 1)
CHUNK_SIZE = 100
FUNNEL_CHUNK_SIZE = 20
SEARCH_CHUNK_SIZE = 50
STOCK_CHUNK_SIZE = 100
FUNNEL_CHUNK_SLEEP_SECONDS = 8
SEARCH_CHUNK_SLEEP_SECONDS = 8
AD_CAMPAIGN_SOURCE_COOLDOWN_SECONDS = 15


@dataclass(slots=True)
class BackfillLogRow:
    source_name: str
    date_from: str
    date_to: str
    chunk_number: int
    nm_count: int
    rows_fetched: int
    rows_upserted: int
    status: str
    error: str
    retry_count: int
    started_at: str
    finished_at: str


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _chunked(values: Sequence[int], size: int) -> list[list[int]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
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


def _build_reference_indexes(active_products: Sequence[dict[str, Any]]) -> tuple[dict[int, dict[str, str]], dict[str, dict[str, str]]]:
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


def _load_ad_event_rows_from_db(start: date, end: date, nm_ids: Sequence[int]) -> list[dict[str, Any]]:
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
            )
        ).all()
    return [
        {
            "advertId": row.advert_id,
            "campaign_name": row.campaign_name,
            "nm_id": row.nm_id,
        }
        for row in rows
        if row.advert_id is not None and row.nm_id is not None
    ]


def _run_logged(
    *,
    source_name: str,
    chunk_number: int,
    nm_ids: Sequence[int],
    loader: Callable[[], dict[str, Any]],
    rows_fetched_key: str,
    rows_upserted_key: str,
    status_key: str | None = None,
    max_retries: int = 0,
    retry_sleep_seconds: int = 5,
) -> tuple[dict[str, Any], BackfillLogRow]:
    started_at = _now_utc()
    retry_count = 0
    result: dict[str, Any] = {}
    status = "FAIL"
    error = ""
    while True:
        try:
            result = loader()
            status = str(result.get(status_key or "status") or "OK")
            error = ""
            break
        except Exception as exc:
            error = str(exc)
            if retry_count >= max_retries:
                result = {}
                status = "FAIL"
                break
            retry_count += 1
            time.sleep(retry_sleep_seconds * retry_count)
    finished_at = _now_utc()
    log_row = BackfillLogRow(
        source_name=source_name,
        date_from=DATE_FROM.isoformat(),
        date_to=DATE_TO.isoformat(),
        chunk_number=chunk_number,
        nm_count=len(nm_ids),
        rows_fetched=int(result.get(rows_fetched_key, 0) or 0),
        rows_upserted=int(result.get(rows_upserted_key, 0) or 0),
        status=status,
        error=error,
        retry_count=retry_count,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
    )
    return result, log_row


def _distinct_nm_ids(
    model,
    column,
    *conditions: Any,
) -> set[int]:
    with session_scope() as session:
        rows = session.execute(select(distinct(column)).where(*conditions)).all()
    return {int(row[0]) for row in rows if row[0] is not None}


def _count_table_rows(model, *conditions: Any) -> int:
    with session_scope() as session:
        stmt = select(func.count()).select_from(model).where(*conditions)
        return int(session.execute(stmt).scalar_one())


def _coverage_summary(active_nm_ids: Sequence[int]) -> dict[str, Any]:
    active_set = set(active_nm_ids)
    funnel_nm_ids = _distinct_nm_ids(
        FactFunnelDay,
        FactFunnelDay.nm_id,
        FactFunnelDay.date >= DATE_FROM,
        FactFunnelDay.date <= DATE_TO,
        FactFunnelDay.nm_id.in_(list(active_set)),
    )
    stock_nm_ids = _distinct_nm_ids(
        FactStockSnapshot,
        FactStockSnapshot.nm_id,
        FactStockSnapshot.snapshot_date == DATE_TO,
        FactStockSnapshot.nm_id.in_(list(active_set)),
    )
    ad_cost_nm_ids = _distinct_nm_ids(
        FactAdCostDay,
        FactAdCostDay.nm_id,
        FactAdCostDay.date >= DATE_FROM,
        FactAdCostDay.date <= DATE_TO,
        FactAdCostDay.nm_id.in_(list(active_set)),
    )
    ad_campaign_nm_ids = _distinct_nm_ids(
        FactAdCampaignNmDay,
        FactAdCampaignNmDay.nm_id,
        FactAdCampaignNmDay.date >= DATE_FROM,
        FactAdCampaignNmDay.date <= DATE_TO,
        FactAdCampaignNmDay.nm_id.in_(list(active_set)),
    )
    search_nm_ids = _distinct_nm_ids(
        FactSearchQueryMetric,
        FactSearchQueryMetric.nm_id,
        FactSearchQueryMetric.period_start >= DATE_FROM,
        FactSearchQueryMetric.period_end <= DATE_TO,
        FactSearchQueryMetric.nm_id.in_(list(active_set)),
    )
    localization_nm_ids = _distinct_nm_ids(
        FactLocalizationRegionDay,
        FactLocalizationRegionDay.nm_id,
        FactLocalizationRegionDay.period_start == DATE_FROM,
        FactLocalizationRegionDay.period_end == DATE_TO,
        FactLocalizationRegionDay.nm_id.in_(list(active_set)),
    )

    any_data_nm_ids = funnel_nm_ids | stock_nm_ids | ad_cost_nm_ids | ad_campaign_nm_ids | search_nm_ids | localization_nm_ids
    products_without_any_data = sorted(active_set - any_data_nm_ids)
    products_with_only_stock = sorted(stock_nm_ids - (funnel_nm_ids | ad_cost_nm_ids | ad_campaign_nm_ids | search_nm_ids | localization_nm_ids))
    products_with_ads_but_without_funnel = sorted((ad_cost_nm_ids | ad_campaign_nm_ids) - funnel_nm_ids)

    with session_scope() as session:
        without_supplier_article = int(
            session.execute(
                select(func.count())
                .select_from(SettingsProducts)
                .where(SettingsProducts.active.is_(True), SettingsProducts.supplier_article.is_(None))
            ).scalar_one()
        )
        without_title = int(
            session.execute(
                select(func.count())
                .select_from(SettingsProducts)
                .where(SettingsProducts.active.is_(True), SettingsProducts.title.is_(None))
            ).scalar_one()
        )

    return {
        "active_products_count": len(active_set),
        "period_days_count": 2,
        "expected_product_day_rows": len(active_set) * 2,
        "source_coverage": {
            "funnel": len(funnel_nm_ids),
            "stock": len(stock_nm_ids),
            "ad_cost": len(ad_cost_nm_ids),
            "ad_campaign": len(ad_campaign_nm_ids),
            "search": len(search_nm_ids),
            "localization": len(localization_nm_ids),
        },
        "products_without_any_data_count": len(products_without_any_data),
        "products_without_any_data_nm_ids": products_without_any_data,
        "products_with_only_stock_count": len(products_with_only_stock),
        "products_with_only_stock_nm_ids": products_with_only_stock,
        "products_with_ads_but_without_funnel_count": len(products_with_ads_but_without_funnel),
        "products_with_ads_but_without_funnel_nm_ids": products_with_ads_but_without_funnel,
        "without_supplier_article": without_supplier_article,
        "without_title": without_title,
    }


def _duplicate_summary(active_nm_ids: Sequence[int]) -> dict[str, int]:
    return {
        "fact_funnel_day": _count_duplicates_by_query(lambda session: count_fact_funnel_day_duplicates),
        "fact_stock_snapshot": _count_duplicates_by_query(lambda session: count_fact_stock_snapshot_duplicates),
        "fact_ad_cost_event": _count_duplicates_by_query(lambda session: count_fact_ad_cost_event_duplicates),
        "fact_ad_cost_day": _count_duplicates_by_query(lambda session: count_fact_ad_cost_day_duplicates),
        "fact_search_query_metric": _count_duplicates_by_query(lambda session: count_fact_search_query_metric_duplicates),
        "fact_localization_region_day": _count_duplicates_by_query(lambda session: count_fact_localization_region_day_duplicates),
    }


def _write_log_csv(rows: Sequence[BackfillLogRow]) -> None:
    LOG_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "source_name",
                "date_from",
                "date_to",
                "chunk_number",
                "nm_count",
                "rows_fetched",
                "rows_upserted",
                "status",
                "error",
                "retry_count",
                "started_at",
                "finished_at",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _write_summary_json(summary: dict[str, Any]) -> None:
    SUMMARY_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_JSON_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def run_backfill_active_products_2days(chunk_size: int = CHUNK_SIZE) -> dict[str, Any]:
    active_products = _load_active_products()
    active_nm_ids = [int(row["nm_id"]) for row in active_products]
    if not active_nm_ids:
        summary = {
            "date_from": DATE_FROM.isoformat(),
            "date_to": DATE_TO.isoformat(),
            "active_products_count": 0,
            "chunks_count": 0,
            "logs_path": str(LOG_CSV_PATH),
            "summary_path": str(SUMMARY_JSON_PATH),
        }
        _write_log_csv([])
        _write_summary_json(summary)
        return summary

    reference_index_int, reference_index_str = _build_reference_indexes(active_products)
    chunks = _chunked(active_nm_ids, chunk_size)
    funnel_chunks = _chunked(active_nm_ids, FUNNEL_CHUNK_SIZE)
    search_chunks = _chunked(active_nm_ids, SEARCH_CHUNK_SIZE)
    stock_chunks = _chunked(active_nm_ids, STOCK_CHUNK_SIZE)
    logs: list[BackfillLogRow] = []
    results: dict[str, list[dict[str, Any]]] = {
        "fact_funnel_day": [],
        "fact_stock_snapshot": [],
        "fact_search_query_metric": [],
        "fact_ad_cost_event": [],
        "fact_ad_cost_day": [],
        "fact_ad_campaign_day": [],
        "fact_ad_campaign_nm_day": [],
        "fact_localization_region_day": [],
    }

    for index, chunk in enumerate(funnel_chunks, start=1):
        funnel_result, funnel_log = _run_logged(
            source_name="fact_funnel_day",
            chunk_number=index,
            nm_ids=chunk,
            loader=lambda chunk=chunk: load_funnel_to_db(DATE_FROM, DATE_TO, nm_ids=chunk),
            rows_fetched_key="rows_fetched",
            rows_upserted_key="rows_upserted",
            status_key="history_status",
            max_retries=2,
            retry_sleep_seconds=12,
        )
        results["fact_funnel_day"].append(funnel_result)
        logs.append(funnel_log)
        if index < len(funnel_chunks):
            time.sleep(FUNNEL_CHUNK_SLEEP_SECONDS)

    for index, chunk in enumerate(stock_chunks, start=1):
        stock_result, stock_log = _run_logged(
            source_name="fact_stock_snapshot",
            chunk_number=index,
            nm_ids=chunk,
            loader=lambda chunk=chunk: load_stocks_to_db(DATE_TO, nm_ids=chunk),
            rows_fetched_key="rows_fetched",
            rows_upserted_key="rows_upserted",
        )
        results["fact_stock_snapshot"].append(stock_result)
        logs.append(stock_log)

    for index, chunk in enumerate(search_chunks, start=1):
        search_result, search_log = _run_logged(
            source_name="fact_search_query_metric",
            chunk_number=index,
            nm_ids=chunk,
            loader=lambda chunk=chunk: load_search_queries_to_db(
                DATE_FROM,
                DATE_TO,
                nm_ids=chunk,
                reference_index={nm_id: reference_index_int[nm_id] for nm_id in chunk if nm_id in reference_index_int},
            ),
            rows_fetched_key="rows_fetched",
            rows_upserted_key="rows_upserted",
            status_key="current_status",
            max_retries=3,
            retry_sleep_seconds=15,
        )
        results["fact_search_query_metric"].append(search_result)
        logs.append(search_log)
        if index < len(search_chunks):
            time.sleep(SEARCH_CHUNK_SLEEP_SECONDS)

    ad_cost_result, ad_cost_log = _run_logged(
        source_name="fact_ad_cost_event",
        chunk_number=1,
        nm_ids=active_nm_ids,
        loader=lambda: load_ad_costs_to_db(DATE_FROM, DATE_TO, nm_ids=active_nm_ids),
        rows_fetched_key="event_rows_fetched",
        rows_upserted_key="event_rows_upserted",
    )
    results["fact_ad_cost_event"].append(ad_cost_result)
    logs.append(ad_cost_log)
    logs.append(
        BackfillLogRow(
            source_name="fact_ad_cost_day",
            date_from=ad_cost_log.date_from,
            date_to=ad_cost_log.date_to,
            chunk_number=1,
            nm_count=len(active_nm_ids),
            rows_fetched=int(ad_cost_result.get("day_rows_built", 0) or 0),
            rows_upserted=int(ad_cost_result.get("day_rows_upserted", 0) or 0),
            status=ad_cost_log.status,
            error=ad_cost_log.error,
            retry_count=ad_cost_log.retry_count,
            started_at=ad_cost_log.started_at,
            finished_at=ad_cost_log.finished_at,
        )
    )
    results["fact_ad_cost_day"].append(ad_cost_result)
    ad_event_rows = _load_ad_event_rows_from_db(DATE_FROM, DATE_TO, active_nm_ids)

    time.sleep(AD_CAMPAIGN_SOURCE_COOLDOWN_SECONDS)

    ad_campaign_result, ad_campaign_log = _run_logged(
        source_name="fact_ad_campaign_day",
        chunk_number=1,
        nm_ids=active_nm_ids,
        loader=lambda: load_ad_campaign_stats_to_db(
            DATE_FROM,
            DATE_TO,
            nm_ids=active_nm_ids,
            ad_event_rows=ad_event_rows,
        ),
        rows_fetched_key="campaign_rows_fetched",
        rows_upserted_key="campaign_rows_upserted",
        status_key="fullstats_status",
        max_retries=3,
        retry_sleep_seconds=20,
    )
    results["fact_ad_campaign_day"].append(ad_campaign_result)
    logs.append(ad_campaign_log)
    logs.append(
        BackfillLogRow(
            source_name="fact_ad_campaign_nm_day",
            date_from=ad_campaign_log.date_from,
            date_to=ad_campaign_log.date_to,
            chunk_number=1,
            nm_count=len(active_nm_ids),
            rows_fetched=int(ad_campaign_result.get("nm_rows_fetched", 0) or 0),
            rows_upserted=int(ad_campaign_result.get("nm_rows_upserted", 0) or 0),
            status=ad_campaign_log.status,
            error=ad_campaign_log.error,
            retry_count=ad_campaign_log.retry_count,
            started_at=ad_campaign_log.started_at,
            finished_at=ad_campaign_log.finished_at,
        )
    )
    results["fact_ad_campaign_nm_day"].append(ad_campaign_result)

    localization_result, localization_log = _run_logged(
        source_name="fact_localization_region_day",
        chunk_number=1,
        nm_ids=active_nm_ids,
        loader=lambda: load_localization_to_db(
            DATE_FROM,
            DATE_TO,
            nm_ids=active_nm_ids,
            reference_index=reference_index_str,
        ),
        rows_fetched_key="rows_fetched",
        rows_upserted_key="rows_upserted",
    )
    results["fact_localization_region_day"].append(localization_result)
    logs.append(localization_log)

    duplicate_counts = {
        "fact_funnel_day": 0,
        "fact_stock_snapshot": 0,
        "fact_ad_cost_event": 0,
        "fact_ad_cost_day": 0,
        "fact_ad_campaign_day": 0,
        "fact_ad_campaign_nm_day": 0,
        "fact_search_query_metric": 0,
        "fact_localization_region_day": 0,
    }
    with session_scope() as session:
        duplicate_counts["fact_funnel_day"] = count_fact_funnel_day_duplicates(session, DATE_FROM, DATE_TO, active_nm_ids)
        duplicate_counts["fact_stock_snapshot"] = count_fact_stock_snapshot_duplicates(session, DATE_TO, active_nm_ids)
        duplicate_counts["fact_ad_cost_event"] = count_fact_ad_cost_event_duplicates(session, DATE_FROM, DATE_TO, active_nm_ids)
        duplicate_counts["fact_ad_cost_day"] = count_fact_ad_cost_day_duplicates(session, DATE_FROM, DATE_TO, active_nm_ids)
        duplicate_counts["fact_search_query_metric"] = count_fact_search_query_metric_duplicates(session, DATE_FROM, DATE_TO, active_nm_ids)
        duplicate_counts["fact_localization_region_day"] = count_fact_localization_region_day_duplicates(session, DATE_FROM, DATE_TO, active_nm_ids)

        ad_campaign_day_duplicates = session.execute(
            select(FactAdCampaignDay.date, FactAdCampaignDay.advert_id, FactAdCampaignDay.row_type)
            .where(FactAdCampaignDay.date >= DATE_FROM, FactAdCampaignDay.date <= DATE_TO)
            .group_by(FactAdCampaignDay.date, FactAdCampaignDay.advert_id, FactAdCampaignDay.row_type)
            .having(func.count() > 1)
        ).all()
        ad_campaign_nm_duplicates = session.execute(
            select(
                FactAdCampaignNmDay.date,
                FactAdCampaignNmDay.advert_id,
                FactAdCampaignNmDay.row_type,
                FactAdCampaignNmDay.conversion_type_raw,
                FactAdCampaignNmDay.nm_id,
            )
            .where(
                FactAdCampaignNmDay.date >= DATE_FROM,
                FactAdCampaignNmDay.date <= DATE_TO,
                FactAdCampaignNmDay.nm_id.in_(active_nm_ids),
            )
            .group_by(
                FactAdCampaignNmDay.date,
                FactAdCampaignNmDay.advert_id,
                FactAdCampaignNmDay.row_type,
                FactAdCampaignNmDay.conversion_type_raw,
                FactAdCampaignNmDay.nm_id,
            )
            .having(func.count() > 1)
        ).all()
        duplicate_counts["fact_ad_campaign_day"] = len(ad_campaign_day_duplicates)
        duplicate_counts["fact_ad_campaign_nm_day"] = len(ad_campaign_nm_duplicates)

    coverage = _coverage_summary(active_nm_ids)
    rows_in_tables = {
        "fact_funnel_day": _count_table_rows(
            FactFunnelDay,
            FactFunnelDay.date >= DATE_FROM,
            FactFunnelDay.date <= DATE_TO,
            FactFunnelDay.nm_id.in_(active_nm_ids),
        ),
        "fact_stock_snapshot": _count_table_rows(
            FactStockSnapshot,
            FactStockSnapshot.snapshot_date == DATE_TO,
            FactStockSnapshot.nm_id.in_(active_nm_ids),
        ),
        "fact_ad_cost_event": _count_table_rows(
            FactAdCostEvent,
            FactAdCostEvent.date >= DATE_FROM,
            FactAdCostEvent.date <= DATE_TO,
            FactAdCostEvent.nm_id.in_(active_nm_ids),
        ),
        "fact_ad_cost_day": _count_table_rows(
            FactAdCostDay,
            FactAdCostDay.date >= DATE_FROM,
            FactAdCostDay.date <= DATE_TO,
            FactAdCostDay.nm_id.in_(active_nm_ids),
        ),
        "fact_ad_campaign_day": _count_table_rows(
            FactAdCampaignDay,
            FactAdCampaignDay.date >= DATE_FROM,
            FactAdCampaignDay.date <= DATE_TO,
        ),
        "fact_ad_campaign_nm_day": _count_table_rows(
            FactAdCampaignNmDay,
            FactAdCampaignNmDay.date >= DATE_FROM,
            FactAdCampaignNmDay.date <= DATE_TO,
            FactAdCampaignNmDay.nm_id.in_(active_nm_ids),
        ),
        "fact_search_query_metric": _count_table_rows(
            FactSearchQueryMetric,
            FactSearchQueryMetric.period_start >= DATE_FROM,
            FactSearchQueryMetric.period_end <= DATE_TO,
            FactSearchQueryMetric.nm_id.in_(active_nm_ids),
        ),
        "fact_localization_region_day": _count_table_rows(
            FactLocalizationRegionDay,
            FactLocalizationRegionDay.period_start == DATE_FROM,
            FactLocalizationRegionDay.period_end == DATE_TO,
            FactLocalizationRegionDay.nm_id.in_(active_nm_ids),
        ),
    }

    summary = {
        "date_from": DATE_FROM.isoformat(),
        "date_to": DATE_TO.isoformat(),
        "active_products_count": len(active_nm_ids),
        "chunks_count": len(chunks),
        "chunk_size": chunk_size,
        "source_chunk_sizes": {
            "funnel": FUNNEL_CHUNK_SIZE,
            "stock": STOCK_CHUNK_SIZE,
            "search": SEARCH_CHUNK_SIZE,
        },
        "failed_sources": [row.source_name for row in logs if row.status == "FAIL"],
        "rows_in_tables": rows_in_tables,
        "results_by_source": results,
        "duplicate_counts": duplicate_counts,
        "coverage": coverage,
        "logs_path": str(LOG_CSV_PATH),
        "summary_path": str(SUMMARY_JSON_PATH),
    }
    _write_log_csv(logs)
    _write_summary_json(summary)
    return summary
