from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import scripts.load_stock_warehouse_snapshot as stock_snapshot_script
from scripts.run_daily_dashboard_refresh import (
    DEFAULT_DASHBOARD_START_DATE,
    run_daily_dashboard_refresh,
)


def test_load_stock_warehouse_default_snapshot_date_uses_today(monkeypatch) -> None:
    class FakeDate(date):
        @classmethod
        def today(cls) -> "FakeDate":
            return cls(2026, 6, 18)

    monkeypatch.setattr(stock_snapshot_script, "date", FakeDate)

    assert stock_snapshot_script.default_snapshot_date() == "2026-06-18"


def test_run_daily_dashboard_refresh_writes_summary_files(monkeypatch, tmp_path: Path) -> None:
    run_date = date(2026, 6, 18)

    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_stock_warehouse_snapshot",
        lambda **kwargs: {
            "snapshot_date": kwargs["snapshot_date"].isoformat(),
            "api_status": "200",
            "rows_in_db_for_snapshot": 2999,
            "unique_nm_ids": 58,
            "unique_chrt_ids": 429,
            "unique_warehouses": 83,
            "request_attempts": [{"status": "200"}],
        },
    )
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.build_mart_total_report",
        lambda date_from, date_to, version="v2": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "rows_built": 2470,
            "rows_in_db": 2470,
            "version": version,
        },
    )
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.export_streamlit_v1_dataset",
        lambda date_from, date_to: {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "total_rows": 2470,
            "output_path": "data/processed/streamlit_v1_dataset.csv",
        },
    )

    summary = run_daily_dashboard_refresh(
        run_date=run_date,
        date_from=DEFAULT_DASHBOARD_START_DATE,
        output_dir=tmp_path,
        include_core_refresh=False,
    )

    assert summary["success"] is True
    assert summary["snapshot_date"] == "2026-06-18"
    assert summary["warehouse_snapshot_rows"] == 2999
    assert summary["mart_total_report_rows"] == 2470
    assert summary["streamlit_dataset_rows"] == 2470
    assert summary["failed_steps"] == []
    assert summary["artifacts"]["json_path"].endswith("dashboard_refresh_2026_06_18.json")
    assert summary["artifacts"]["md_path"].endswith("dashboard_refresh_2026_06_18.md")

    json_path = Path(summary["artifacts"]["json_path"])
    md_path = Path(summary["artifacts"]["md_path"])
    assert json_path.exists()
    assert md_path.exists()

    saved_summary = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved_summary["success"] is True
    assert saved_summary["api_statuses"] == {"warehouse_snapshot": "200"}
    assert "warehouse_snapshot" in md_path.read_text(encoding="utf-8")


def test_run_daily_dashboard_refresh_persists_failure_summary(monkeypatch, tmp_path: Path) -> None:
    run_date = date(2026, 6, 18)

    def fail_snapshot(**_: object) -> dict[str, object]:
        raise RuntimeError("warehouse snapshot failed")

    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_stock_warehouse_snapshot",
        fail_snapshot,
    )

    summary = run_daily_dashboard_refresh(
        run_date=run_date,
        date_from=DEFAULT_DASHBOARD_START_DATE,
        output_dir=tmp_path,
        include_core_refresh=False,
    )

    assert summary["success"] is False
    assert summary["failed_steps"] == ["warehouse_snapshot"]
    assert summary["error_message"] == "warehouse snapshot failed"

    json_path = Path(summary["artifacts"]["json_path"])
    assert json_path.exists()
    saved_summary = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved_summary["success"] is False
    assert saved_summary["failed_steps"] == ["warehouse_snapshot"]
