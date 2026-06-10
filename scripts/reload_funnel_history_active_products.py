#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import func, select

from src.db.funnel_loader import load_funnel_to_db
from src.db.models import FactFunnelDay, SettingsProducts
from src.db.session import session_scope


DEFAULT_DATE_FROM = date(2026, 5, 31)
DEFAULT_DATE_TO = date(2026, 6, 7)
DEFAULT_CHUNK_SIZE = 20
DEFAULT_SLEEP_SECONDS = 20
DEFAULT_MAX_RETRIES = 2


@dataclass(slots=True)
class ChunkLogRow:
    report_date: str
    chunk_number: int
    nm_count: int
    rows_fetched: int
    rows_upserted: int
    status: str
    error: str
    retry_count: int
    skipped_by_resume: bool


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


def _load_active_nm_ids() -> list[int]:
    with session_scope() as session:
        rows = session.execute(
            select(SettingsProducts.nm_id)
            .where(SettingsProducts.active.is_(True))
            .order_by(SettingsProducts.nm_id)
        ).all()
    return [int(row[0]) for row in rows if row[0] is not None]


def _chunk_already_loaded(report_date: date, nm_ids: Sequence[int]) -> bool:
    with session_scope() as session:
        loaded_count = int(
            session.execute(
                select(func.count())
                .select_from(FactFunnelDay)
                .where(
                    FactFunnelDay.date == report_date,
                    FactFunnelDay.nm_id.in_(list(nm_ids)),
                    FactFunnelDay.card_clicks.is_not(None),
                )
            ).scalar_one()
        )
    return loaded_count == len(nm_ids)


def _count_rows_with_field(
    start: date,
    end: date,
    field_name: str,
) -> int:
    column = getattr(FactFunnelDay, field_name)
    with session_scope() as session:
        return int(
            session.execute(
                select(func.count())
                .select_from(FactFunnelDay)
                .where(
                    FactFunnelDay.date >= start,
                    FactFunnelDay.date <= end,
                    column.is_not(None),
                )
            ).scalar_one()
        )


def _count_suspicious_equal_clicks_impressions(start: date, end: date) -> int:
    with session_scope() as session:
        return int(
            session.execute(
                select(func.count())
                .select_from(FactFunnelDay)
                .where(
                    FactFunnelDay.date >= start,
                    FactFunnelDay.date <= end,
                    FactFunnelDay.card_clicks.is_not(None),
                    FactFunnelDay.impressions.is_not(None),
                    FactFunnelDay.card_clicks == FactFunnelDay.impressions,
                )
            ).scalar_one()
        )


def _count_mass_ctr_100(start: date, end: date) -> int:
    with session_scope() as session:
        return int(
            session.execute(
                select(func.count())
                .select_from(FactFunnelDay)
                .where(
                    FactFunnelDay.date >= start,
                    FactFunnelDay.date <= end,
                    FactFunnelDay.ctr == 100,
                )
            ).scalar_one()
        )


def _safe_percent(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator in (None, Decimal("0")):
        return None
    return (numerator / denominator) * Decimal("100")


def _recover_existing_open_count_rows(report_date: date, nm_ids: Sequence[int]) -> int:
    with session_scope() as session:
        rows = session.execute(
            select(FactFunnelDay)
            .where(
                FactFunnelDay.date == report_date,
                FactFunnelDay.nm_id.in_(list(nm_ids)),
                FactFunnelDay.impressions.is_not(None),
                FactFunnelDay.card_clicks.is_(None),
            )
        ).scalars().all()

        updated = 0
        for row in rows:
            open_count = row.impressions
            if open_count is None:
                continue
            row.card_clicks = open_count
            row.impressions = None
            row.ctr = None
            row.add_to_cart_conversion = _safe_percent(row.cart_count, open_count)
            if row.cart_to_order_conversion is None:
                row.cart_to_order_conversion = _safe_percent(row.order_count, row.cart_count)
            updated += 1

    return updated


def run_reload(
    *,
    date_from: date,
    date_to: date,
    chunk_size: int,
    sleep_seconds: int,
    max_retries: int,
    resume: bool,
) -> dict[str, Any]:
    active_nm_ids = _load_active_nm_ids()
    chunk_logs: list[ChunkLogRow] = []
    http_error_counts = {"429": 0, "500": 0}
    failed_chunks: list[dict[str, Any]] = []
    summary_by_date: dict[str, dict[str, int]] = defaultdict(lambda: {"rows_fetched": 0, "rows_upserted": 0, "chunks": 0})
    dates = _daterange(date_from, date_to)
    all_chunks_count = len(dates) * len(_chunked(active_nm_ids, chunk_size))

    processed_chunks = 0
    for report_date in dates:
        chunks = _chunked(active_nm_ids, chunk_size)
        for chunk_number, chunk in enumerate(chunks, start=1):
            processed_chunks += 1
            if resume and _chunk_already_loaded(report_date, chunk):
                chunk_logs.append(
                    ChunkLogRow(
                        report_date=report_date.isoformat(),
                        chunk_number=chunk_number,
                        nm_count=len(chunk),
                        rows_fetched=0,
                        rows_upserted=0,
                        status="SKIPPED",
                        error="already loaded with non-null card_clicks",
                        retry_count=0,
                        skipped_by_resume=True,
                    )
                )
                continue

            result: dict[str, Any] = {}
            last_error = ""
            retry_count = 0
            status = "FAIL"
            while True:
                try:
                    result = load_funnel_to_db(report_date, report_date, nm_ids=chunk)
                    status = str(result.get("history_status") or "OK")
                    last_error = ""
                    break
                except Exception as exc:
                    last_error = str(exc)
                    if "invalid start day: excess limit on days" in last_error:
                        recovered_rows = _recover_existing_open_count_rows(report_date, chunk)
                        result = {
                            "rows_fetched": recovered_rows,
                            "rows_upserted": recovered_rows,
                        }
                        status = "RECOVERED_FROM_EXISTING_OPENCOUNT"
                        last_error = ""
                        break
                    if "429" in last_error:
                        http_error_counts["429"] += 1
                        if retry_count < max_retries:
                            retry_count += 1
                            time.sleep(sleep_seconds * (retry_count + 1))
                            continue
                    elif "500" in last_error:
                        http_error_counts["500"] += 1
                    break

            rows_fetched = int(result.get("rows_fetched", 0) or 0)
            rows_upserted = int(result.get("rows_upserted", 0) or 0)
            chunk_logs.append(
                ChunkLogRow(
                    report_date=report_date.isoformat(),
                    chunk_number=chunk_number,
                    nm_count=len(chunk),
                    rows_fetched=rows_fetched,
                    rows_upserted=rows_upserted,
                    status=status,
                    error=last_error,
                    retry_count=retry_count,
                    skipped_by_resume=False,
                )
            )
            summary_by_date[report_date.isoformat()]["rows_fetched"] += rows_fetched
            summary_by_date[report_date.isoformat()]["rows_upserted"] += rows_upserted
            summary_by_date[report_date.isoformat()]["chunks"] += 1
            if last_error:
                failed_chunks.append(
                    {
                        "report_date": report_date.isoformat(),
                        "chunk_number": chunk_number,
                        "nm_ids": chunk,
                        "error": last_error,
                    }
                )

            is_last_chunk = processed_chunks == all_chunks_count
            if not is_last_chunk:
                time.sleep(sleep_seconds)

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "active_products_count": len(active_nm_ids),
        "chunk_size": chunk_size,
        "chunks_total": all_chunks_count,
        "chunks_processed": len(chunk_logs),
        "failed_chunks": failed_chunks,
        "http_error_counts": http_error_counts,
        "summary_by_date": dict(summary_by_date),
        "non_null_card_clicks": _count_rows_with_field(date_from, date_to, "card_clicks"),
        "non_null_ctr": _count_rows_with_field(date_from, date_to, "ctr"),
        "non_null_add_to_cart_conversion": _count_rows_with_field(date_from, date_to, "add_to_cart_conversion"),
        "non_null_cart_to_order_conversion": _count_rows_with_field(date_from, date_to, "cart_to_order_conversion"),
        "suspicious_equal_clicks_impressions": _count_suspicious_equal_clicks_impressions(date_from, date_to),
        "mass_ctr_100_rows": _count_mass_ctr_100(date_from, date_to),
        "chunk_logs": [asdict(row) for row in chunk_logs],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reload WB sales funnel history for all active products.")
    parser.add_argument("--date-from", type=_parse_date, default=DEFAULT_DATE_FROM)
    parser.add_argument("--date-to", type=_parse_date, default=DEFAULT_DATE_TO)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--sleep-seconds", type=int, default=DEFAULT_SLEEP_SECONDS)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument("--resume", action="store_true", help="Skip chunks already loaded with non-null card_clicks.")
    args = parser.parse_args()

    summary = run_reload(
        date_from=args.date_from,
        date_to=args.date_to,
        chunk_size=args.chunk_size,
        sleep_seconds=args.sleep_seconds,
        max_retries=args.max_retries,
        resume=args.resume,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["failed_chunks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
