from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import text

from src.db.ad_campaign_loader import collect_ad_campaign_rows
from src.db.ad_cost_loader import collect_ad_cost_rows
from src.db.funnel_loader import collect_funnel_rows
from src.db.search_query_loader import collect_search_query_rows
from src.db.session import session_scope
from src.db.stock_loader import collect_stock_rows
from src.pipelines.mvp_real_run import MvpRealRun
from src.tracked_products import get_tracked_nm_ids


DEFAULT_PROJECT_TIMEZONE = "Europe/Moscow"


@dataclass(slots=True)
class SourceAvailability:
    source_name: str
    target_date: str
    checked_at_msk: str
    api_rows_returned: int
    api_products_count: int
    api_has_nonzero_metrics: bool
    status: str
    error_message: str = ""
    nonzero_metric_fields: list[str] | None = None
    expected_products_count: int | None = None
    db_rows_current: int | None = None
    db_products_current: int | None = None


def resolve_target_date(*, target_date: date | None = None, now: datetime | None = None, timezone_name: str = DEFAULT_PROJECT_TIMEZONE) -> date:
    if target_date is not None:
        return target_date
    resolved_now = now or datetime.now(UTC)
    today_in_tz = resolved_now.astimezone(ZoneInfo(timezone_name)).date()
    return today_in_tz - timedelta(days=1)


def summarize_metric_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    product_field: str = "nm_id",
    metric_fields: Sequence[str],
) -> dict[str, Any]:
    unique_products = {
        int(value)
        for row in rows
        if (value := row.get(product_field)) not in (None, "", [])
    }
    nonzero_metric_fields: list[str] = []
    for field_name in metric_fields:
        for row in rows:
            raw_value = row.get(field_name)
            if raw_value in (None, "", []):
                continue
            try:
                if float(raw_value) != 0:
                    nonzero_metric_fields.append(field_name)
                    break
            except (TypeError, ValueError):
                continue
    return {
        "rows_count": len(rows),
        "products_count": len(unique_products),
        "has_nonzero_metrics": bool(nonzero_metric_fields),
        "nonzero_metric_fields": nonzero_metric_fields,
    }


def classify_source_status(
    *,
    rows_count: int,
    products_count: int,
    expected_products_count: int | None,
    has_nonzero_metrics: bool,
    error_message: str = "",
) -> str:
    if error_message:
        return "ERROR"
    if rows_count <= 0:
        return "EMPTY"
    if expected_products_count and products_count < expected_products_count:
        return "PARTIAL"
    if not has_nonzero_metrics:
        return "PARTIAL"
    return "AVAILABLE"


def _chunked(values: Sequence[int], size: int) -> list[list[int]]:
    return [list(values[index:index + size]) for index in range(0, len(values), size)]


def _collect_rows_chunked(
    *,
    nm_ids: Sequence[int],
    chunk_size: int,
    collector: Callable[[Sequence[int]], Sequence[Mapping[str, Any]]],
) -> list[Mapping[str, Any]]:
    collected: list[Mapping[str, Any]] = []
    for chunk_nm_ids in _chunked(list(nm_ids), chunk_size):
        collected.extend(list(collector(chunk_nm_ids)))
    return collected


def _fetch_source_summary(
    *,
    collector: Callable[[], Sequence[Mapping[str, Any]]],
    metric_fields: Sequence[str],
) -> tuple[dict[str, Any] | None, str]:
    try:
        rows = collector()
    except Exception as exc:  # pragma: no cover - integration path
        return None, str(exc)
    return summarize_metric_rows(rows, metric_fields=metric_fields), ""


def _build_source_result(
    *,
    source_name: str,
    target_date: date,
    checked_at: datetime,
    summary: Mapping[str, Any] | None,
    expected_products_count: int,
    error_message: str = "",
    db_rows_current: int | None = None,
    db_products_current: int | None = None,
) -> SourceAvailability:
    rows_count = int(summary.get("rows_count", 0) or 0) if summary else 0
    products_count = int(summary.get("products_count", 0) or 0) if summary else 0
    has_nonzero_metrics = bool(summary.get("has_nonzero_metrics", False)) if summary else False
    return SourceAvailability(
        source_name=source_name,
        target_date=target_date.isoformat(),
        checked_at_msk=checked_at.isoformat(timespec="seconds"),
        api_rows_returned=rows_count,
        api_products_count=products_count,
        api_has_nonzero_metrics=has_nonzero_metrics,
        status=classify_source_status(
            rows_count=rows_count,
            products_count=products_count,
            expected_products_count=expected_products_count,
            has_nonzero_metrics=has_nonzero_metrics,
            error_message=error_message,
        ),
        error_message=error_message,
        nonzero_metric_fields=list(summary.get("nonzero_metric_fields", [])) if summary else [],
        expected_products_count=expected_products_count,
        db_rows_current=db_rows_current,
        db_products_current=db_products_current,
    )


def _probe_source(
    *,
    source_name: str,
    target_date: date,
    checked_at: datetime,
    collector: Callable[[], Sequence[Mapping[str, Any]]],
    metric_fields: Sequence[str],
    expected_products_count: int,
    db_rows_current: int | None = None,
    db_products_current: int | None = None,
) -> SourceAvailability:
    summary, error_message = _fetch_source_summary(
        collector=collector,
        metric_fields=metric_fields,
    )
    return _build_source_result(
        source_name=source_name,
        target_date=target_date,
        checked_at=checked_at,
        summary=summary,
        expected_products_count=expected_products_count,
        error_message=error_message,
        db_rows_current=db_rows_current,
        db_products_current=db_products_current,
    )


def load_db_snapshot(*, target_date: date) -> dict[str, Any]:
    queries = {
        "fact_funnel_day": """
            select count(*) as rows_count, count(distinct nm_id) as products_count
            from fact_funnel_day
            where date = :target_date
        """,
        "fact_ad_campaign_nm_day": """
            select count(*) as rows_count, count(distinct nm_id) as products_count
            from fact_ad_campaign_nm_day
            where date = :target_date
        """,
        "fact_ad_cost_day": """
            select count(*) as rows_count, count(distinct nm_id) as products_count
            from fact_ad_cost_day
            where date = :target_date
        """,
        "fact_search_query_metric": """
            select count(*) as rows_count, count(distinct nm_id) as products_count
            from fact_search_query_metric
            where date = :target_date
        """,
        "fact_stock_snapshot": """
            select count(*) as rows_count, count(distinct nm_id) as products_count
            from fact_stock_snapshot
            where snapshot_date = :target_date
        """,
        "mart_total_report": """
            select
                count(*) as rows_count,
                count(distinct nm_id) as products_count,
                count(card_clicks) as card_clicks_rows,
                count(cart_count) as cart_rows,
                count(order_count) as order_rows,
                count(order_sum) as order_sum_rows,
                count(ad_atbs_total) as ad_atbs_rows,
                count(ad_campaign_spend_total) as ad_spend_rows,
                count(search_queries_count) as search_rows,
                count(current_stock_qty) as stock_rows
            from mart_total_report
            where report_date = :target_date
        """,
    }
    snapshot: dict[str, Any] = {}
    with session_scope() as session:
        for key, sql in queries.items():
            row = session.execute(text(sql), {"target_date": target_date}).mappings().one()
            snapshot[key] = dict(row)
    return snapshot


def build_recommendation(
    *,
    source_results: Sequence[SourceAvailability],
    db_snapshot: Mapping[str, Any],
    scheduler_runs_core_refresh: bool,
) -> dict[str, Any]:
    available_sources = [row.source_name for row in source_results if row.status == "AVAILABLE"]
    partial_sources = [row.source_name for row in source_results if row.status == "PARTIAL"]
    error_sources = [row.source_name for row in source_results if row.status == "ERROR"]
    empty_sources = [row.source_name for row in source_results if row.status == "EMPTY"]
    mart_rows = int(db_snapshot.get("mart_total_report", {}).get("rows_count", 0) or 0)
    mart_core_rows = {
        "card_clicks_rows": int(db_snapshot.get("mart_total_report", {}).get("card_clicks_rows", 0) or 0),
        "ad_spend_rows": int(db_snapshot.get("mart_total_report", {}).get("ad_spend_rows", 0) or 0),
        "search_rows": int(db_snapshot.get("mart_total_report", {}).get("search_rows", 0) or 0),
    }
    if available_sources and not scheduler_runs_core_refresh:
        conclusion = "scheduler_missing_core_refresh"
        message = (
            "API already returns at least part of yesterday data, "
            "but the current daily scheduler does not run core refresh."
        )
    elif partial_sources and not scheduler_runs_core_refresh and mart_rows > 0:
        conclusion = "combined_scheduler_gap_and_api_latency"
        message = (
            "Yesterday API data is only partially available right now, "
            "and the current daily scheduler does not run core refresh. "
            "The issue is combined: WB latency plus orchestration gap."
        )
    elif available_sources:
        conclusion = "api_available_check_loader_or_write_path"
        message = "API responds for target_date. Investigate loader/write path or cron orchestration."
    elif partial_sources and not available_sources:
        conclusion = "api_partial_recommend_later_retry"
        message = "Yesterday API data is partial. Run a later retry in Moscow time and keep rolling backfill."
    elif error_sources:
        conclusion = "probe_errors"
        message = "Some availability probes failed. Stabilize the read-only probe first."
    else:
        conclusion = "api_not_ready_yet"
        message = "Yesterday API data still looks empty. WB source latency is likely, especially for advertising."
    return {
        "conclusion": conclusion,
        "message": message,
        "available_sources": available_sources,
        "partial_sources": partial_sources,
        "empty_sources": empty_sources,
        "error_sources": error_sources,
        "scheduler_runs_core_refresh": scheduler_runs_core_refresh,
        "mart_rows_current": mart_rows,
        "mart_core_rows_current": mart_core_rows,
        "recommended_window_msk": "13:00-15:00 primary, 18:00-21:00 retry, rolling backfill last 3 days",
    }


def run_availability_probe(*, target_date: date | None = None, timezone_name: str = DEFAULT_PROJECT_TIMEZONE) -> dict[str, Any]:
    resolved_target_date = resolve_target_date(target_date=target_date, timezone_name=timezone_name)
    checked_at_msk = datetime.now(UTC).astimezone(ZoneInfo(timezone_name))
    tracked_nm_ids = get_tracked_nm_ids()
    runner = MvpRealRun()
    runner.date_from = resolved_target_date
    runner.date_to = resolved_target_date
    runner.nm_ids = list(tracked_nm_ids)

    db_snapshot = load_db_snapshot(target_date=resolved_target_date)

    ad_cost_summary: dict[str, Any] | None = None
    ad_cost_error = ""
    ad_event_rows: list[Mapping[str, Any]] = []
    try:
        ad_event_rows_raw, ad_day_rows, _ad_cost_meta = collect_ad_cost_rows(
            runner,
            resolved_target_date,
            resolved_target_date,
            nm_ids=tracked_nm_ids,
        )
        ad_event_rows = list(ad_event_rows_raw)
        ad_cost_summary = summarize_metric_rows(
            ad_day_rows,
            metric_fields=("total_spend", "events_count"),
        )
    except Exception as exc:
        ad_cost_error = str(exc)

    source_results = [
        _probe_source(
            source_name="funnel",
            target_date=resolved_target_date,
            checked_at=checked_at_msk,
            expected_products_count=len(tracked_nm_ids),
            collector=lambda: _collect_rows_chunked(
                nm_ids=tracked_nm_ids,
                chunk_size=20,
                collector=lambda chunk_nm_ids: collect_funnel_rows(
                    runner,
                    resolved_target_date,
                    resolved_target_date,
                    nm_ids=chunk_nm_ids,
                )[0],
            ),
            metric_fields=("impressions", "card_clicks", "cartCount", "orderCount", "orderSum"),
            db_rows_current=int(db_snapshot["fact_funnel_day"]["rows_count"] or 0),
            db_products_current=int(db_snapshot["fact_funnel_day"]["products_count"] or 0),
        ),
        _build_source_result(
            source_name="ad_cost",
            target_date=resolved_target_date,
            checked_at=checked_at_msk,
            summary=ad_cost_summary,
            expected_products_count=len(tracked_nm_ids),
            error_message=ad_cost_error,
            db_rows_current=int(db_snapshot["fact_ad_cost_day"]["rows_count"] or 0),
            db_products_current=int(db_snapshot["fact_ad_cost_day"]["products_count"] or 0),
        ),
        _probe_source(
            source_name="ad_campaign_nm",
            target_date=resolved_target_date,
            checked_at=checked_at_msk,
            expected_products_count=len(tracked_nm_ids),
            collector=lambda: collect_ad_campaign_rows(
                runner,
                resolved_target_date,
                resolved_target_date,
                nm_ids=tracked_nm_ids,
                ad_event_rows=ad_event_rows or None,
            )[1],
            metric_fields=("ad_spend", "ad_views", "ad_clicks", "ad_atbs", "ad_orders"),
            db_rows_current=int(db_snapshot["fact_ad_campaign_nm_day"]["rows_count"] or 0),
            db_products_current=int(db_snapshot["fact_ad_campaign_nm_day"]["products_count"] or 0),
        ),
        _probe_source(
            source_name="search_query",
            target_date=resolved_target_date,
            checked_at=checked_at_msk,
            expected_products_count=len(tracked_nm_ids),
            collector=lambda: _collect_rows_chunked(
                nm_ids=tracked_nm_ids,
                chunk_size=50,
                collector=lambda chunk_nm_ids: collect_search_query_rows(
                    runner,
                    resolved_target_date - timedelta(days=1),
                    resolved_target_date,
                    nm_ids=chunk_nm_ids,
                    reference_index={},
                )[0],
            ),
            metric_fields=("query_count", "search_clicks", "search_cart", "search_orders"),
            db_rows_current=int(db_snapshot["fact_search_query_metric"]["rows_count"] or 0),
            db_products_current=int(db_snapshot["fact_search_query_metric"]["products_count"] or 0),
        ),
        _probe_source(
            source_name="stock_snapshot",
            target_date=resolved_target_date,
            checked_at=checked_at_msk,
            expected_products_count=len(tracked_nm_ids),
            collector=lambda: collect_stock_rows(runner, resolved_target_date, nm_ids=tracked_nm_ids)[0],
            metric_fields=("wb_stock_qty", "stock_total_qty", "stock_total_sum", "availability"),
            db_rows_current=int(db_snapshot["fact_stock_snapshot"]["rows_count"] or 0),
            db_products_current=int(db_snapshot["fact_stock_snapshot"]["products_count"] or 0),
        ),
    ]

    scheduler_info = {
        "current_daily_run_time_msk": "11:00",
        "current_target_date_logic": "yesterday_in_Europe/Moscow",
        "daily_scheduler_runs_core_refresh": False,
    }
    recommendation = build_recommendation(
        source_results=source_results,
        db_snapshot=db_snapshot,
        scheduler_runs_core_refresh=scheduler_info["daily_scheduler_runs_core_refresh"],
    )

    return {
        "today_msk": checked_at_msk.date().isoformat(),
        "target_date": resolved_target_date.isoformat(),
        "checked_at_msk": checked_at_msk.isoformat(timespec="seconds"),
        "tracked_products_count": len(tracked_nm_ids),
        "db_current": db_snapshot,
        "api_sources": [asdict(item) for item in source_results],
        "mart_current": db_snapshot["mart_total_report"],
        "current_schedule": scheduler_info,
        "recommendation": recommendation,
    }
