#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.export_streamlit_v1_dataset import export_streamlit_v1_dataset
from scripts.load_wb_site_price_snapshot import load_wb_site_price_snapshot
from scripts.load_missing_core_dates import run_missing_core_dates_load
from sqlalchemy import select
from src.config.settings import settings
from src.db.models import FactStockWarehouseSnapshot
from src.db.mart_total_report_builder import build_mart_total_report
from src.db.session import session_scope
from src.db.stock_warehouse_loader import TRACKED_PRODUCTS_PATH, get_tracked_nm_ids, load_stock_warehouse_snapshot


DEFAULT_DASHBOARD_START_DATE = date(2026, 6, 7)
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "processed" / "daily_runs"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def build_summary_paths(output_dir: Path, run_date: date) -> dict[str, Path]:
    slug = run_date.strftime("%Y_%m_%d")
    return {
        "json_path": output_dir / f"dashboard_refresh_{slug}.json",
        "md_path": output_dir / f"dashboard_refresh_{slug}.md",
    }


def build_markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Daily Dashboard Refresh",
        "",
        f"- Status: {'SUCCESS' if summary.get('success') else 'FAILED'}",
        f"- Run started at: {summary.get('run_started_at', '')}",
        f"- Run finished at: {summary.get('run_finished_at', '')}",
        f"- Snapshot date: {summary.get('snapshot_date', '')}",
        f"- Date range: {summary.get('date_from', '')} .. {summary.get('date_to', '')}",
        f"- Warehouse snapshot rows: {summary.get('warehouse_snapshot_rows', '')}",
        f"- Warehouse unique nm_id: {summary.get('warehouse_unique_nm_id', '')}",
        f"- Warehouse unique chrt_id: {summary.get('warehouse_unique_chrt_id', '')}",
        f"- Warehouse unique warehouses: {summary.get('warehouse_unique_warehouses', '')}",
        f"- WB site price monitor: {summary.get('wb_site_price_monitor_status', '')}",
        f"- WB site price requested nm_id: {summary.get('wb_site_price_requested_nm_ids', '')}",
        f"- WB site price success count: {summary.get('wb_site_price_success_count', '')}",
        f"- WB site price failed count: {summary.get('wb_site_price_failed_count', '')}",
        f"- WB site price alerts count: {summary.get('wb_site_price_alerts_count', '')}",
        f"- Missing tracked nm_id: {', '.join(str(item) for item in summary.get('missing_tracked_nm_id', [])) or 'none'}",
        f"- Mart rows: {summary.get('mart_total_report_rows', '')}",
        f"- Streamlit dataset rows: {summary.get('streamlit_dataset_rows', '')}",
        f"- API statuses: {json.dumps(summary.get('api_statuses', {}), ensure_ascii=False)}",
        f"- Failed steps: {', '.join(summary.get('failed_steps', [])) or 'none'}",
    ]
    if summary.get("error_message"):
        lines.extend(["", "## Error", "", summary["error_message"]])
    if summary.get("wb_site_price_monitor_error"):
        lines.extend(["", "## WB Site Price Monitor Error", "", summary["wb_site_price_monitor_error"]])
    return "\n".join(lines) + "\n"


def persist_run_summary(output_dir: Path, run_date: date, summary: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = build_summary_paths(output_dir, run_date)
    paths["json_path"].write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["md_path"].write_text(build_markdown_summary(summary), encoding="utf-8")
    return {name: str(path) for name, path in paths.items()}


def load_present_snapshot_nm_ids(snapshot_date: date) -> set[int]:
    with session_scope() as session:
        rows = session.execute(
            select(FactStockWarehouseSnapshot.nm_id)
            .where(FactStockWarehouseSnapshot.snapshot_date == snapshot_date)
            .distinct()
        ).all()
    return {int(row[0]) for row in rows if row[0] is not None}


def run_daily_dashboard_refresh(
    *,
    run_date: date | None = None,
    date_from: date = DEFAULT_DASHBOARD_START_DATE,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    include_core_refresh: bool = False,
    mart_version: str = "v2",
) -> dict[str, Any]:
    resolved_run_date = run_date or date.today()
    current_step = "validation"
    summary: dict[str, Any] = {
        "run_started_at": utc_now_iso(),
        "run_finished_at": "",
        "success": False,
        "snapshot_date": resolved_run_date.isoformat(),
        "date_from": date_from.isoformat(),
        "date_to": resolved_run_date.isoformat(),
        "include_core_refresh": include_core_refresh,
        "failed_steps": [],
        "api_statuses": {},
        "warehouse_snapshot_rows": None,
        "warehouse_unique_nm_id": None,
        "warehouse_unique_chrt_id": None,
        "warehouse_unique_warehouses": None,
        "wb_site_price_monitor_status": "",
        "wb_site_price_monitor_error": "",
        "wb_site_price_requested_nm_ids": None,
        "wb_site_price_success_count": None,
        "wb_site_price_failed_count": None,
        "wb_site_price_alerts_count": None,
        "missing_tracked_nm_id": [],
        "mart_total_report_rows": None,
        "streamlit_dataset_rows": None,
        "error_message": "",
        "traceback": "",
    }
    summary["artifacts"] = persist_run_summary(output_dir, resolved_run_date, summary)

    try:
        if resolved_run_date < date_from:
            raise ValueError("run_date не может быть раньше date_from.")

        if settings.wb_site_price_monitor_enabled:
            current_step = "wb_site_price_monitor"
            try:
                site_price_summary = load_wb_site_price_snapshot(
                    snapshot_date=resolved_run_date,
                    tracked_products=True,
                    write_db=True,
                )
                summary["wb_site_price_summary"] = site_price_summary
                summary["wb_site_price_requested_nm_ids"] = site_price_summary.get("requested_nm_ids_count")
                summary["wb_site_price_success_count"] = site_price_summary.get("success_count")
                summary["wb_site_price_failed_count"] = site_price_summary.get("failed_count")
                summary["wb_site_price_alerts_count"] = site_price_summary.get("alerts_count")
                if site_price_summary.get("success"):
                    summary["wb_site_price_monitor_status"] = "success"
                    summary["api_statuses"]["wb_site_price_monitor"] = "success"
                else:
                    summary["wb_site_price_monitor_status"] = "failed_optional"
                    summary["wb_site_price_monitor_error"] = (
                        site_price_summary.get("error") or "wb site price snapshot failed"
                    )
                    summary["api_statuses"]["wb_site_price_monitor"] = "failed_optional"
            except Exception as exc:
                summary["wb_site_price_monitor_status"] = "failed_optional"
                summary["wb_site_price_monitor_error"] = str(exc)
                summary["api_statuses"]["wb_site_price_monitor"] = "failed_optional"
        else:
            summary["wb_site_price_monitor_status"] = "skipped_disabled"
            summary["api_statuses"]["wb_site_price_monitor"] = "skipped_disabled"
        summary["artifacts"] = persist_run_summary(output_dir, resolved_run_date, summary)

        current_step = "warehouse_snapshot"
        warehouse_summary = load_stock_warehouse_snapshot(
            snapshot_date=resolved_run_date,
            tracked_products=True,
            write_db=True,
        )
        summary["warehouse_snapshot"] = warehouse_summary
        summary["api_statuses"]["warehouse_snapshot"] = warehouse_summary.get("api_status")
        summary["warehouse_snapshot_rows"] = warehouse_summary.get("rows_in_db_for_snapshot")
        summary["warehouse_unique_nm_id"] = warehouse_summary.get("unique_nm_ids")
        summary["warehouse_unique_chrt_id"] = warehouse_summary.get("unique_chrt_ids")
        summary["warehouse_unique_warehouses"] = warehouse_summary.get("unique_warehouses")
        requested = int(warehouse_summary.get("requested_nm_ids_count", 0) or 0)
        actual = int(warehouse_summary.get("unique_nm_ids", 0) or 0)
        tracked_nm_ids = get_tracked_nm_ids(TRACKED_PRODUCTS_PATH)
        if warehouse_summary.get("api_status") != "200" or warehouse_summary.get("api_error"):
            raise RuntimeError(
                warehouse_summary.get("api_error")
                or f"warehouse snapshot API status {warehouse_summary.get('api_status')}"
            )
        if requested > actual:
            present_nm_ids = load_present_snapshot_nm_ids(resolved_run_date)
            summary["missing_tracked_nm_id"] = sorted(nm_id for nm_id in tracked_nm_ids if nm_id not in present_nm_ids)
        summary["artifacts"] = persist_run_summary(output_dir, resolved_run_date, summary)

        if include_core_refresh:
            current_step = "core_refresh"
            core_summary = run_missing_core_dates_load(
                date_from=date_from,
                date_to=resolved_run_date,
                full_range_from=date_from,
                full_range_to=resolved_run_date,
                fullstats_sleep_seconds=20,
                use_tracked_products=True,
            )
            summary["core_refresh"] = core_summary
            summary["api_statuses"]["core_refresh"] = "FAILED" if core_summary.get("failed_chunks") else "OK"
            if core_summary.get("failed_chunks"):
                summary["failed_steps"].append("core_refresh")
            summary["artifacts"] = persist_run_summary(output_dir, resolved_run_date, summary)

        current_step = "mart_refresh"
        mart_summary = build_mart_total_report(date_from, resolved_run_date, version=mart_version)
        summary["mart_summary"] = mart_summary
        summary["mart_total_report_rows"] = mart_summary.get("rows_in_db")
        summary["artifacts"] = persist_run_summary(output_dir, resolved_run_date, summary)

        current_step = "streamlit_export"
        dataset_summary = export_streamlit_v1_dataset(date_from, resolved_run_date)
        summary["streamlit_dataset_summary"] = dataset_summary
        summary["streamlit_dataset_rows"] = dataset_summary.get("total_rows")
        summary["success"] = not summary["failed_steps"]
    except Exception as exc:
        if not summary["failed_steps"]:
            summary["failed_steps"].append(current_step)
        summary["error_message"] = str(exc)
        summary["traceback"] = traceback.format_exc()
    finally:
        summary["run_finished_at"] = utc_now_iso()
        summary["artifacts"] = persist_run_summary(output_dir, resolved_run_date, summary)

    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily warehouse snapshot + mart rebuild + Streamlit export.")
    parser.add_argument("--run-date", default=date.today().isoformat(), help="Run date in YYYY-MM-DD. Default: today.")
    parser.add_argument(
        "--date-from",
        default=DEFAULT_DASHBOARD_START_DATE.isoformat(),
        help="Left boundary for mart/export rebuild. Default: 2026-06-07.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Where to save JSON/MD run summaries.",
    )
    parser.add_argument(
        "--include-core-refresh",
        action="store_true",
        help="Also run tracked core facts refresh before mart/export rebuild.",
    )
    parser.add_argument("--version", default="v2", choices=["v1", "v2"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_daily_dashboard_refresh(
        run_date=date.fromisoformat(args.run_date),
        date_from=date.fromisoformat(args.date_from),
        output_dir=Path(args.output_dir),
        include_core_refresh=bool(args.include_core_refresh),
        mart_version=args.version,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
