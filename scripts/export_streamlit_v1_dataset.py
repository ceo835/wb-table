#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select
from sqlalchemy import func

from src.db.models import FactWbSitePriceSnapshot, MartTotalReport
from src.db.session import session_scope
from src.streamlit_dataset import STREAMLIT_V1_COLUMNS, attach_wb_price_snapshot_fields, enrich_streamlit_row


PROCESSED_DIR = ROOT_DIR / "data" / "processed"
OUTPUT_PATH = PROCESSED_DIR / "streamlit_v1_dataset.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Streamlit-ready dataset from mart_total_report v2.")
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    return parser.parse_args()


def row_to_dict(row: MartTotalReport) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in MartTotalReport.__table__.columns}


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def get_mart_total_report_date_bounds() -> tuple[date | None, date | None]:
    with session_scope() as session:
        min_date, max_date = session.execute(
            select(func.min(MartTotalReport.report_date), func.max(MartTotalReport.report_date))
        ).one()
    return min_date, max_date


def resolve_export_dates(
    date_from_text: str | None,
    date_to_text: str | None,
) -> tuple[date, date]:
    mart_min_date, mart_max_date = get_mart_total_report_date_bounds()
    if mart_min_date is None or mart_max_date is None:
        raise RuntimeError("В mart_total_report нет дат для экспорта dataset.")

    resolved_date_from = date.fromisoformat(date_from_text) if date_from_text else mart_min_date
    resolved_date_to = date.fromisoformat(date_to_text) if date_to_text else mart_max_date
    if resolved_date_from > resolved_date_to:
        raise ValueError("date_from не может быть больше date_to.")
    return resolved_date_from, resolved_date_to


def export_streamlit_v1_dataset(date_from: date, date_to: date) -> dict[str, Any]:
    with session_scope() as session:
        mart_rows = session.execute(
            select(MartTotalReport)
            .where(MartTotalReport.report_date >= date_from, MartTotalReport.report_date <= date_to)
            .order_by(MartTotalReport.supplier_article.asc(), MartTotalReport.nm_id.asc(), MartTotalReport.report_date.asc())
        ).scalars().all()
        wb_price_snapshot_rows = session.execute(
            select(FactWbSitePriceSnapshot).order_by(
                FactWbSitePriceSnapshot.snapshot_date.asc(),
                FactWbSitePriceSnapshot.nm_id.asc(),
            )
        ).scalars().all()
        rows = [row_to_dict(row) for row in mart_rows]
        snapshot_rows = [
            {
                "snapshot_date": row.snapshot_date,
                "snapshot_at": row.snapshot_at,
                "nm_id": row.nm_id,
                "buyer_visible_price": row.buyer_visible_price,
                "fetch_status": row.fetch_status,
            }
            for row in wb_price_snapshot_rows
        ]
    rows = attach_wb_price_snapshot_fields(rows, snapshot_rows)
    rows = [enrich_streamlit_row(row) for row in rows]

    projected_rows = [{column: row.get(column) for column in STREAMLIT_V1_COLUMNS} for row in rows]
    write_csv(OUTPUT_PATH, projected_rows, STREAMLIT_V1_COLUMNS)

    key_counter = Counter((row["report_date"], row["nm_id"]) for row in rows)
    duplicate_keys = sum(1 for count in key_counter.values() if count > 1)

    rows_ok_partial_sources = sum(1 for row in rows if row["data_quality_status"] == "OK_PARTIAL_SOURCES")
    rows_partial = sum(1 for row in rows if row["data_quality_status"] == "PARTIAL")
    rows_no_data = sum(1 for row in rows if row["data_quality_status"] == "NO_DATA")

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "total_rows": len(rows),
        "duplicate_keys": duplicate_keys,
        "rows_ok_partial_sources": rows_ok_partial_sources,
        "rows_partial": rows_partial,
        "rows_no_data": rows_no_data,
        "rows_with_ad_campaign": sum(1 for row in rows if bool(row.get("has_ad_campaign"))),
        "rows_with_search": sum(1 for row in rows if bool(row.get("has_search"))),
        "rows_with_stock": sum(1 for row in rows if bool(row.get("has_stock"))),
        "rows_with_pending_entry_point": sum(
            1 for row in rows if row.get("entry_point_status") == "FILE_IMPORT_PENDING"
        ),
        "rows_with_pending_orders_geography": sum(
            1 for row in rows if row.get("orders_geography_status") == "FILE_IMPORT_PENDING"
        ),
        "rows_with_pending_vbro": sum(1 for row in rows if row.get("vbro_status") == "MANUAL_PENDING"),
        "output_path": str(OUTPUT_PATH),
    }


def main() -> int:
    args = parse_args()
    date_from, date_to = resolve_export_dates(args.date_from, args.date_to)
    summary = export_streamlit_v1_dataset(date_from, date_to)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
