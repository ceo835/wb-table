#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import select


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.backfill_target_products_api_data import _error_type_from_text, _is_retryable_error, _status_from_result
from scripts.export_streamlit_v1_dataset import export_streamlit_v1_dataset
from src.db.funnel_loader import load_funnel_to_db
from src.db.mart_total_report_builder import build_mart_total_report
from src.db.models import FactFunnelDay, MartTotalReport
from src.db.session import session_scope


GAP_DIR = ROOT_DIR / "data" / "manual_gap_reports"
DEFAULT_GAP_FILE = GAP_DIR / "api_gap_funnel_recent_2026-06-05_2026-06-07.csv"
DEFAULT_ORGANIC_FILE = GAP_DIR / "organic_formula_gaps_2026-06-04_2026-06-07.csv"
DEFAULT_FILE_REQUIRED_FILE = GAP_DIR / "file_required_entry_geo_2026-06-04_2026-06-07.csv"
DEFAULT_SUMMARY_FILE = GAP_DIR / "targeted_coverage_gap_summary_2026-06-04_2026-06-07.csv"
DEFAULT_REPORT_DATE_FROM = date(2026, 6, 4)
DEFAULT_REPORT_DATE_TO = date(2026, 6, 7)
DEFAULT_CHUNK_SIZE = 20
DEFAULT_RETRY_COUNT = 1
DEFAULT_RETRY_SLEEP_SECONDS = 20

FUNNEL_FIELD_LABEL_MAP = {
    "Переходы в карточку": "card_clicks",
    "Положили в корзину": "cart_count",
    "Заказы": "order_count",
    "Заказали на сумму": "order_sum",
}
FUNNEL_TARGET_FIELDS = tuple(FUNNEL_FIELD_LABEL_MAP.values())


@dataclass(slots=True)
class FunnelGapRow:
    report_date: date
    supplier_article: str
    nm_id: int
    missing_labels: list[str]
    missing_fields: list[str]
    recommendation: str


@dataclass(slots=True)
class GapRunRowResult:
    report_date: str
    supplier_article: str
    nm_id: int
    requested_fields: str
    status: str
    reason: str
    retries_used: int
    newly_filled_fields: str
    remaining_missing_fields: str
    before_state: str
    after_state: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Targeted funnel API fill based on manual gap CSV.")
    parser.add_argument("--gap-file", type=Path, default=DEFAULT_GAP_FILE)
    parser.add_argument("--organic-file", type=Path, default=DEFAULT_ORGANIC_FILE)
    parser.add_argument("--file-required-file", type=Path, default=DEFAULT_FILE_REQUIRED_FILE)
    parser.add_argument("--summary-file", type=Path, default=DEFAULT_SUMMARY_FILE)
    parser.add_argument("--report-date-from", type=date.fromisoformat, default=DEFAULT_REPORT_DATE_FROM)
    parser.add_argument("--report-date-to", type=date.fromisoformat, default=DEFAULT_REPORT_DATE_TO)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--retry-count", type=int, default=DEFAULT_RETRY_COUNT)
    parser.add_argument("--retry-sleep-seconds", type=int, default=DEFAULT_RETRY_SLEEP_SECONDS)
    return parser.parse_args()


def _chunked(values: list[int], size: int) -> list[list[int]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _normalize_missing_labels(value: object) -> list[str]:
    if value is None or value != value:
        return []
    labels = [part.strip() for part in str(value).split(",")]
    return [label for label in labels if label]


def load_gap_rows(path: Path) -> list[FunnelGapRow]:
    df = pd.read_csv(path)
    rows: list[FunnelGapRow] = []
    seen: set[tuple[date, int]] = set()
    for record in df.to_dict(orient="records"):
        report_date = date.fromisoformat(str(record["Дата"]))
        nm_id = int(record["Артикул WB"])
        key = (report_date, nm_id)
        if key in seen:
            continue
        seen.add(key)
        missing_labels = _normalize_missing_labels(record.get("Что отсутствует"))
        missing_fields = [FUNNEL_FIELD_LABEL_MAP[label] for label in missing_labels if label in FUNNEL_FIELD_LABEL_MAP]
        rows.append(
            FunnelGapRow(
                report_date=report_date,
                supplier_article=str(record.get("Артикул продавца") or ""),
                nm_id=nm_id,
                missing_labels=missing_labels,
                missing_fields=missing_fields,
                recommendation=str(record.get("Рекомендация") or ""),
            )
        )
    return sorted(rows, key=lambda item: (item.report_date, item.nm_id))


def _serialize_state(row: Any | None) -> dict[str, Any]:
    if row is None:
        return {field: None for field in FUNNEL_TARGET_FIELDS}
    return {field: getattr(row, field, None) for field in FUNNEL_TARGET_FIELDS}


def load_funnel_state(report_date: date, nm_ids: list[int]) -> dict[tuple[date, int], dict[str, Any]]:
    with session_scope() as session:
        rows = session.execute(
            select(FactFunnelDay).where(FactFunnelDay.date == report_date, FactFunnelDay.nm_id.in_(nm_ids))
        ).scalars().all()
        return {
            (row.date, int(row.nm_id)): _serialize_state(row)
            for row in rows
            if row.date is not None and row.nm_id is not None
        }


def load_mart_status_map(pairs: list[tuple[date, int]]) -> dict[tuple[date, int], dict[str, Any]]:
    if not pairs:
        return {}
    grouped: dict[date, list[int]] = {}
    for report_date, nm_id in pairs:
        grouped.setdefault(report_date, []).append(nm_id)

    result: dict[tuple[date, int], dict[str, Any]] = {}
    with session_scope() as session:
        for report_date, nm_ids in grouped.items():
            rows = session.execute(
                select(MartTotalReport).where(
                    MartTotalReport.report_date == report_date,
                    MartTotalReport.nm_id.in_(sorted(set(nm_ids))),
                )
            ).scalars().all()
            for row in rows:
                if row.report_date is None or row.nm_id is None:
                    continue
                result[(row.report_date, int(row.nm_id))] = {
                    "cart_count": row.cart_count,
                    "order_count": row.order_count,
                    "organic_cart_share_status": row.organic_cart_share_status,
                }
    return result


def build_scoped_mart_snapshot(pairs: list[tuple[date, int]]) -> dict[str, int]:
    mart_map = load_mart_status_map(pairs)
    return {
        "rows_total": len(pairs),
        "rows_with_cart_count": sum(1 for pair in pairs if mart_map.get(pair, {}).get("cart_count") is not None),
        "rows_with_order_count": sum(1 for pair in pairs if mart_map.get(pair, {}).get("order_count") is not None),
        "organic_ok": sum(
            1 for pair in pairs if mart_map.get(pair, {}).get("organic_cart_share_status") == "OK"
        ),
        "organic_missing_source": sum(
            1 for pair in pairs if mart_map.get(pair, {}).get("organic_cart_share_status") == "MISSING_SOURCE"
        ),
    }


def _format_state(state: dict[str, Any], fields: list[str]) -> str:
    return ", ".join(f"{field}={state.get(field)!r}" for field in fields)


def classify_row_result(
    gap_row: FunnelGapRow,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    status: str,
    reason: str,
    retries_used: int,
) -> GapRunRowResult:
    target_fields = gap_row.missing_fields or list(FUNNEL_TARGET_FIELDS)
    newly_filled = [field for field in target_fields if before_state.get(field) is None and after_state.get(field) is not None]
    remaining_missing = [field for field in target_fields if after_state.get(field) is None]

    final_status = status
    final_reason = reason
    if status == "OK":
        if newly_filled and not remaining_missing:
            final_status = "FILLED"
            final_reason = "FILLED"
        elif newly_filled:
            final_status = "PARTIAL"
            final_reason = "PARTIAL"
        else:
            final_status = "NO_DATA"
            final_reason = "NO_DATA"

    return GapRunRowResult(
        report_date=gap_row.report_date.isoformat(),
        supplier_article=gap_row.supplier_article,
        nm_id=gap_row.nm_id,
        requested_fields=",".join(target_fields),
        status=final_status,
        reason=final_reason,
        retries_used=retries_used,
        newly_filled_fields=",".join(newly_filled),
        remaining_missing_fields=",".join(remaining_missing),
        before_state=_format_state(before_state, target_fields),
        after_state=_format_state(after_state, target_fields),
    )


def run_chunk_with_retry(
    *,
    report_date: date,
    nm_ids: list[int],
    retry_count: int,
    retry_sleep_seconds: int,
) -> tuple[dict[str, Any], str, str, int]:
    attempts = 0
    last_error = ""
    while True:
        try:
            result = load_funnel_to_db(report_date, report_date, nm_ids=nm_ids)
            status, reason = _status_from_result("funnel", result, "")
            return result, status, reason, attempts
        except Exception as exc:
            last_error = str(exc)
            error_type = _error_type_from_text(last_error)
            if attempts >= retry_count or not _is_retryable_error(error_type):
                return {}, "FAILED_CHUNK", error_type or "FAILED_CHUNK", attempts
            attempts += 1
            time.sleep(retry_sleep_seconds)


def read_csv_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(pd.read_csv(path))


def build_file_required_blocks(path: Path) -> list[str]:
    if not path.exists():
        return []
    df = pd.read_csv(path)
    if "Блок" not in df.columns:
        return []
    return sorted({str(value) for value in df["Блок"].dropna().tolist() if str(value).strip()})


def persist_results(result_rows: list[GapRunRowResult], gap_file: Path) -> Path:
    output_path = gap_file.with_name(gap_file.stem + "_result.csv")
    df = pd.DataFrame([asdict(row) for row in result_rows])
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    return output_path


def run_targeted_funnel_gap_fill(
    *,
    gap_file: Path,
    organic_file: Path,
    file_required_file: Path,
    summary_file: Path,
    report_date_from: date,
    report_date_to: date,
    chunk_size: int,
    retry_count: int,
    retry_sleep_seconds: int,
) -> dict[str, Any]:
    gap_rows = load_gap_rows(gap_file)
    target_pairs = [(row.report_date, row.nm_id) for row in gap_rows]
    before_scope = build_scoped_mart_snapshot(target_pairs)

    grouped_rows: dict[date, list[FunnelGapRow]] = {}
    for row in gap_rows:
        grouped_rows.setdefault(row.report_date, []).append(row)

    result_rows: list[GapRunRowResult] = []
    chunk_summaries: list[dict[str, Any]] = []

    for report_date in sorted(grouped_rows):
        rows_for_date = grouped_rows[report_date]
        nm_ids_for_date = sorted({row.nm_id for row in rows_for_date})
        before_state_map = load_funnel_state(report_date, nm_ids_for_date)
        row_lookup = {row.nm_id: row for row in rows_for_date}

        for chunk_number, chunk_nm_ids in enumerate(_chunked(nm_ids_for_date, chunk_size), start=1):
            result, status, reason, retries_used = run_chunk_with_retry(
                report_date=report_date,
                nm_ids=chunk_nm_ids,
                retry_count=retry_count,
                retry_sleep_seconds=retry_sleep_seconds,
            )
            after_state_map = load_funnel_state(report_date, chunk_nm_ids)
            chunk_summaries.append(
                {
                    "report_date": report_date.isoformat(),
                    "chunk_number": chunk_number,
                    "nm_ids": chunk_nm_ids,
                    "status": status,
                    "reason": reason,
                    "retries_used": retries_used,
                    "rows_fetched": int(result.get("rows_fetched", 0) or 0),
                    "rows_upserted": int(result.get("rows_upserted", 0) or 0),
                }
            )
            for nm_id in chunk_nm_ids:
                gap_row = row_lookup[nm_id]
                before_state = before_state_map.get((report_date, nm_id), _serialize_state(None))
                after_state = after_state_map.get((report_date, nm_id), _serialize_state(None))
                result_rows.append(
                    classify_row_result(
                        gap_row=gap_row,
                        before_state=before_state,
                        after_state=after_state,
                        status=status,
                        reason=reason,
                        retries_used=retries_used,
                    )
                )

    mart_summary = build_mart_total_report(report_date_from, report_date_to, version="v2")
    export_summary = export_streamlit_v1_dataset(report_date_from, report_date_to)
    after_scope = build_scoped_mart_snapshot(target_pairs)

    result_path = persist_results(result_rows, gap_file)
    file_required_blocks = build_file_required_blocks(file_required_file)

    status_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for row in result_rows:
        status_counts[row.status] = status_counts.get(row.status, 0) + 1
        reason_counts[row.reason] = reason_counts.get(row.reason, 0) + 1

    summary = {
        "gap_file": str(gap_file),
        "report_date_from": report_date_from.isoformat(),
        "report_date_to": report_date_to.isoformat(),
        "target_rows_total": len(gap_rows),
        "target_unique_nm_ids": len({row.nm_id for row in gap_rows}),
        "before_scope": before_scope,
        "after_scope": after_scope,
        "rows_filled_or_partial": sum(1 for row in result_rows if row.status in {"FILLED", "PARTIAL"}),
        "rows_no_data": sum(1 for row in result_rows if row.reason == "NO_DATA"),
        "rows_api_date_limit": sum(1 for row in result_rows if row.reason == "API_DATE_LIMIT"),
        "rows_error": sum(1 for row in result_rows if row.status == "FAILED_CHUNK"),
        "status_counts": status_counts,
        "reason_counts": reason_counts,
        "chunk_summaries": chunk_summaries,
        "result_csv_path": str(result_path),
        "mart_summary": mart_summary,
        "export_summary": export_summary,
        "organic_gap_rows": read_csv_count(organic_file),
        "file_required_rows": read_csv_count(file_required_file),
        "gap_summary_rows": read_csv_count(summary_file),
        "file_required_blocks": file_required_blocks,
        "still_file_required_blocks": file_required_blocks,
        "remaining_no_data_nm_id_dates": [
            {"report_date": row.report_date, "nm_id": row.nm_id, "supplier_article": row.supplier_article}
            for row in result_rows
            if row.reason in {"NO_DATA", "API_DATE_LIMIT"} or row.status == "FAILED_CHUNK"
        ],
    }
    summary_path = gap_file.with_name(gap_file.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["summary_json_path"] = str(summary_path)
    return summary


def main() -> int:
    args = parse_args()
    summary = run_targeted_funnel_gap_fill(
        gap_file=args.gap_file,
        organic_file=args.organic_file,
        file_required_file=args.file_required_file,
        summary_file=args.summary_file,
        report_date_from=args.report_date_from,
        report_date_to=args.report_date_to,
        chunk_size=args.chunk_size,
        retry_count=args.retry_count,
        retry_sleep_seconds=args.retry_sleep_seconds,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
