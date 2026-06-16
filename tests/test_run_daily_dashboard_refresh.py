from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import scripts.run_daily_dashboard_refresh as daily_refresh_script
import scripts.load_stock_warehouse_snapshot as stock_snapshot_script
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scripts.run_daily_dashboard_refresh import (
    DEFAULT_DASHBOARD_START_DATE,
    run_daily_dashboard_refresh,
)
from src.db.app_job_runs import run_guarded_job
from src.db.base import Base
from src.db.models import AppJobRun
from src.scheduler.daily_refresh_scheduler import (
    DAILY_REFRESH_JOB_NAME,
    build_next_run_at,
    should_autostart_daily_refresh,
    should_run_startup_catchup,
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
    monkeypatch.setattr(daily_refresh_script.settings, "wb_site_price_monitor_enabled", True, raising=False)

    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_wb_site_price_snapshot",
        lambda **kwargs: {
            "success": True,
            "requested_nm_ids_count": 59,
            "success_count": 52,
            "failed_count": 7,
            "alerts_count": 3,
        },
    )
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
    assert saved_summary["api_statuses"] == {"wb_site_price_monitor": "success", "warehouse_snapshot": "200"}
    assert "warehouse_snapshot" in md_path.read_text(encoding="utf-8")


def test_run_daily_dashboard_refresh_persists_failure_summary(monkeypatch, tmp_path: Path) -> None:
    run_date = date(2026, 6, 18)
    monkeypatch.setattr(daily_refresh_script.settings, "wb_site_price_monitor_enabled", True, raising=False)

    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_wb_site_price_snapshot",
        lambda **kwargs: {
            "success": True,
            "requested_nm_ids_count": 59,
            "success_count": 52,
            "failed_count": 7,
            "alerts_count": 3,
        },
    )

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


def test_run_daily_dashboard_refresh_skips_price_monitor_when_disabled(monkeypatch, tmp_path: Path) -> None:
    run_date = date(2026, 6, 18)
    monkeypatch.setattr(daily_refresh_script.settings, "wb_site_price_monitor_enabled", False, raising=False)
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_wb_site_price_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("price monitor should not run when disabled")),
    )
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
    assert summary["wb_site_price_monitor_status"] == "skipped_disabled"
    assert summary["api_statuses"]["wb_site_price_monitor"] == "skipped_disabled"


def test_run_daily_dashboard_refresh_continues_when_price_monitor_fails_optionally(
    monkeypatch, tmp_path: Path
) -> None:
    run_date = date(2026, 6, 18)
    monkeypatch.setattr(daily_refresh_script.settings, "wb_site_price_monitor_enabled", True, raising=False)
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_wb_site_price_snapshot",
        lambda **kwargs: {
            "success": False,
            "error": "proxy timeout",
            "requested_nm_ids_count": 3,
            "success_count": 0,
            "failed_count": 3,
            "alerts_count": 0,
        },
    )
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
    assert summary["failed_steps"] == []
    assert summary["wb_site_price_monitor_status"] == "failed_optional"
    assert summary["wb_site_price_monitor_error"] == "proxy timeout"
    assert summary["api_statuses"]["wb_site_price_monitor"] == "failed_optional"


def test_app_job_runs_enforces_unique_job_name_and_run_date() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[AppJobRun.__table__])

    with Session(engine) as session:
        session.add(
            AppJobRun(
                id=1,
                job_name=DAILY_REFRESH_JOB_NAME,
                run_date=date(2026, 6, 16),
                status="success",
            )
        )
        session.commit()
        session.add(
            AppJobRun(
                id=2,
                job_name=DAILY_REFRESH_JOB_NAME,
                run_date=date(2026, 6, 16),
                status="failed",
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("Expected unique constraint violation for duplicate job_name + run_date")


def test_run_guarded_job_skips_when_success_exists(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    monkeypatch.setattr("src.db.app_job_runs.try_acquire_job_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("src.db.app_job_runs.release_job_lock", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("src.db.app_job_runs.has_successful_job_run", lambda *_args, **_kwargs: True)

    runner_called = {"value": False}

    result = run_guarded_job(
        job_name=DAILY_REFRESH_JOB_NAME,
        run_date=date(2026, 6, 16),
        runner=lambda: runner_called.__setitem__("value", True),
        engine=engine,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "already_completed"
    assert runner_called["value"] is False


def test_run_guarded_job_skips_when_advisory_lock_not_acquired(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    monkeypatch.setattr("src.db.app_job_runs.try_acquire_job_lock", lambda *_args, **_kwargs: False)

    runner_called = {"value": False}

    result = run_guarded_job(
        job_name=DAILY_REFRESH_JOB_NAME,
        run_date=date(2026, 6, 16),
        runner=lambda: runner_called.__setitem__("value", True),
        engine=engine,
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "lock_not_acquired"
    assert runner_called["value"] is False


def test_scheduler_local_default_is_disabled() -> None:
    assert should_autostart_daily_refresh(env={}) is False


def test_scheduler_enables_on_railway_environment() -> None:
    assert should_autostart_daily_refresh(env={"RAILWAY_ENVIRONMENT": "production"}) is True


def test_scheduler_env_override_false_disables_railway_autostart() -> None:
    assert should_autostart_daily_refresh(
        env={
            "RAILWAY_ENVIRONMENT": "production",
            "DASHBOARD_DAILY_REFRESH_AUTOSTART": "false",
        }
    ) is False


def test_scheduler_runs_startup_catchup_after_0800_utc_without_success_today() -> None:
    now = datetime(2026, 6, 16, 8, 15, tzinfo=UTC)

    assert should_run_startup_catchup(now=now, has_success_today=False) is True


def test_scheduler_does_not_run_startup_catchup_when_success_exists_today() -> None:
    now = datetime(2026, 6, 16, 8, 15, tzinfo=UTC)

    assert should_run_startup_catchup(now=now, has_success_today=True) is False


def test_build_next_run_at_returns_same_day_before_cutoff() -> None:
    now = datetime(2026, 6, 16, 7, 30, tzinfo=UTC)

    assert build_next_run_at(now) == datetime(2026, 6, 16, 8, 0, tzinfo=UTC)
