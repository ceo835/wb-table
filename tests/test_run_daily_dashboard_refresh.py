from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import scripts.run_daily_dashboard_refresh as daily_refresh_script
import scripts.load_stock_warehouse_snapshot as stock_snapshot_script
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
import pytest

from scripts.run_daily_dashboard_refresh import (
    DEFAULT_DASHBOARD_START_DATE,
    resolve_default_target_date,
    run_daily_dashboard_refresh,
)
from src.db.app_job_runs import run_guarded_job
from src.db.base import Base
from src.db.models import AppJobRun
from src.scheduler.daily_refresh_scheduler import (
    DAILY_REFRESH_JOB_NAME,
    build_next_run_at,
    execute_daily_refresh_once,
    should_autostart_daily_refresh,
    should_run_startup_catchup,
    _scheduler_loop,
)


@pytest.fixture(autouse=True)
def mock_search_query_loader(monkeypatch):
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_search_scope_products",
        lambda **kwargs: [{"nm_id": 100, "query_group": "test"}],
    )
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_search_text_rows",
        lambda **kwargs: {
            "api_status": "200",
            "rows_loaded": 10,
            "rows_in_db": 10,
        },
    )
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_wb_seller_price_snapshot",
        lambda **kwargs: {
            "success": True,
            "resolved_date": kwargs["snapshot_date"].isoformat(),
            "nm_ids_count": 59,
            "success_count": 59,
            "failed_count": 0,
            "rows_inserted": 59,
        },
    )


def test_run_daily_dashboard_refresh_search_queries_success_and_failure(monkeypatch, tmp_path: Path) -> None:
    run_date = date(2026, 6, 18)
    monkeypatch.setattr(daily_refresh_script.settings, "wb_site_price_monitor_enabled", False, raising=False)
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_stock_warehouse_snapshot",
        lambda **kwargs: {
            "snapshot_date": kwargs["snapshot_date"].isoformat(),
            "api_status": "200",
            "rows_in_db_for_snapshot": 100,
            "unique_nm_ids": 10,
            "unique_chrt_ids": 10,
            "unique_warehouses": 2,
            "request_attempts": [{"status": "200"}],
        },
    )
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.build_mart_total_report",
        lambda date_from, date_to, version="v2": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "rows_built": 10,
            "rows_in_db": 10,
            "version": version,
        },
    )
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.export_streamlit_v1_dataset",
        lambda date_from, date_to: {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "total_rows": 10,
            "output_path": "data/processed/streamlit_v1_dataset.csv",
        },
    )

    # 1. Test success scenario
    captured_args = {}
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_search_text_rows",
        lambda **kwargs: captured_args.update(kwargs) or {
            "api_status": "200",
            "rows_loaded": 15,
            "rows_in_db": 15,
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
    assert summary["search_queries_rows_loaded"] == 15
    assert summary["api_statuses"]["search_queries"] == "200"
    assert captured_args == {
        "target_day": run_date,
        "products": [{"nm_id": 100, "query_group": "test"}],
        "apply": True,
        "nm_batch_size": 50,
        "request_sleep_seconds": 5.0,
        "max_retries": 2,
    }

    # 2. Test failure scenario (e.g. 429 error)
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_search_text_rows",
        lambda **kwargs: {
            "api_status": "429",
            "api_error": "Too Many Requests",
            "rows_loaded": 0,
            "rows_in_db": 0,
        },
    )

    summary_fail = run_daily_dashboard_refresh(
        run_date=run_date,
        date_from=DEFAULT_DASHBOARD_START_DATE,
        output_dir=tmp_path,
        include_core_refresh=False,
    )

    assert summary_fail["success"] is False
    assert summary_fail["failed_steps"] == ["search_queries"]
    assert "Too Many Requests" in summary_fail["error_message"]


def test_load_stock_warehouse_default_snapshot_date_uses_yesterday_in_project_timezone(monkeypatch) -> None:
    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None) -> "FakeDateTime":
            base = cls(2026, 6, 21, 0, 30, tzinfo=UTC)
            return base if tz is None else base.astimezone(tz)

    monkeypatch.setattr(stock_snapshot_script, "datetime", FakeDateTime)

    assert stock_snapshot_script.default_snapshot_date() == "2026-06-20"


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
    assert saved_summary["api_statuses"] == {
        "wb_site_price_monitor": "success",
        "warehouse_snapshot": "200",
        "search_queries": "200",
        "wb_seller_price": "success",
    }
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


def test_resolve_default_target_date_uses_yesterday_in_project_timezone() -> None:
    now = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)

    assert resolve_default_target_date(now) == date(2026, 6, 20)


def test_resolve_default_target_date_uses_project_timezone_not_raw_utc_date() -> None:
    now = datetime(2026, 6, 20, 21, 30, tzinfo=UTC)

    assert resolve_default_target_date(now) == date(2026, 6, 20)


def test_run_daily_dashboard_refresh_uses_manual_run_date_override(monkeypatch, tmp_path: Path) -> None:
    run_date = date(2026, 6, 19)
    monkeypatch.setattr(daily_refresh_script.settings, "wb_site_price_monitor_enabled", False, raising=False)
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_stock_warehouse_snapshot",
        lambda **kwargs: {
            "snapshot_date": kwargs["snapshot_date"].isoformat(),
            "api_status": "200",
            "rows_in_db_for_snapshot": 100,
            "unique_nm_ids": 10,
            "unique_chrt_ids": 10,
            "unique_warehouses": 2,
            "request_attempts": [{"status": "200"}],
        },
    )
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.build_mart_total_report",
        lambda date_from, date_to, version="v2": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "rows_built": 10,
            "rows_in_db": 10,
            "version": version,
        },
    )
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.export_streamlit_v1_dataset",
        lambda date_from, date_to: {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "total_rows": 10,
            "output_path": "data/processed/streamlit_v1_dataset.csv",
        },
    )

    summary = run_daily_dashboard_refresh(
        run_date=run_date,
        date_from=run_date,
        output_dir=tmp_path,
        include_core_refresh=False,
    )

    assert summary["snapshot_date"] == "2026-06-19"
    assert summary["date_to"] == "2026-06-19"
    assert summary["mart_summary"]["date_to"] == "2026-06-19"
    assert summary["streamlit_dataset_summary"]["date_to"] == "2026-06-19"


def test_run_daily_dashboard_refresh_default_uses_yesterday_for_core_mart_and_export(
    monkeypatch, tmp_path: Path
) -> None:
    target_date = date(2026, 6, 20)
    monkeypatch.setattr(daily_refresh_script, "resolve_default_target_date", lambda now=None, timezone_name="Europe/Moscow": target_date)
    monkeypatch.setattr(daily_refresh_script.settings, "wb_site_price_monitor_enabled", False, raising=False)

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_stock_warehouse_snapshot",
        lambda **kwargs: {
            "snapshot_date": kwargs["snapshot_date"].isoformat(),
            "api_status": "200",
            "rows_in_db_for_snapshot": 100,
            "unique_nm_ids": 10,
            "unique_chrt_ids": 10,
            "unique_warehouses": 2,
            "request_attempts": [{"status": "200"}],
        },
    )

    def fake_run_missing_core_dates_load(**kwargs):
        captured["core_refresh"] = kwargs
        return {"failed_chunks": []}

    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.run_missing_core_dates_load",
        fake_run_missing_core_dates_load,
    )
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.build_mart_total_report",
        lambda date_from, date_to, version="v2": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "rows_built": 10,
            "rows_in_db": 10,
            "version": version,
        },
    )
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.export_streamlit_v1_dataset",
        lambda date_from, date_to: {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "total_rows": 10,
            "output_path": "data/processed/streamlit_v1_dataset.csv",
        },
    )

    summary = run_daily_dashboard_refresh(
        run_date=None,
        date_from=target_date,
        output_dir=tmp_path,
        include_core_refresh=True,
    )

    assert summary["snapshot_date"] == "2026-06-20"
    assert captured["core_refresh"] == {
        "date_from": target_date,
        "date_to": target_date,
        "full_range_from": target_date,
        "full_range_to": target_date,
        "fullstats_sleep_seconds": 20,
        "use_tracked_products": True,
    }
    assert summary["mart_summary"]["date_to"] == "2026-06-20"
    assert summary["streamlit_dataset_summary"]["date_to"] == "2026-06-20"


def test_run_daily_dashboard_refresh_limits_core_refresh_to_target_date(monkeypatch, tmp_path: Path) -> None:
    run_date = date(2026, 6, 21)
    captured: dict[str, object] = {}
    monkeypatch.setattr(daily_refresh_script.settings, "wb_site_price_monitor_enabled", False, raising=False)
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.load_stock_warehouse_snapshot",
        lambda **kwargs: {
            "snapshot_date": kwargs["snapshot_date"].isoformat(),
            "api_status": "200",
            "rows_in_db_for_snapshot": 100,
            "unique_nm_ids": 10,
            "unique_chrt_ids": 10,
            "unique_warehouses": 2,
            "request_attempts": [{"status": "200"}],
        },
    )

    def fake_run_missing_core_dates_load(**kwargs):
        captured["core_refresh"] = kwargs
        return {"failed_chunks": []}

    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.run_missing_core_dates_load",
        fake_run_missing_core_dates_load,
    )
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.build_mart_total_report",
        lambda date_from, date_to, version="v2": {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "rows_built": 10,
            "rows_in_db": 10,
            "version": version,
        },
    )
    monkeypatch.setattr(
        "scripts.run_daily_dashboard_refresh.export_streamlit_v1_dataset",
        lambda date_from, date_to: {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "total_rows": 10,
            "output_path": "data/processed/streamlit_v1_dataset.csv",
        },
    )

    run_daily_dashboard_refresh(
        run_date=run_date,
        date_from=DEFAULT_DASHBOARD_START_DATE,
        output_dir=tmp_path,
        include_core_refresh=True,
    )

    assert captured["core_refresh"] == {
        "date_from": run_date,
        "date_to": run_date,
        "full_range_from": run_date,
        "full_range_to": run_date,
        "fullstats_sleep_seconds": 20,
        "use_tracked_products": True,
    }


def test_execute_daily_refresh_once_uses_yesterday_as_default_run_date(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.scheduler.daily_refresh_scheduler.utc_now",
        lambda: datetime(2026, 6, 20, 21, 30, tzinfo=UTC),
    )

    captured: dict[str, object] = {}

    def fake_run_guarded_job(*, job_name, run_date, runner):
        captured["job_name"] = job_name
        captured["run_date"] = run_date
        captured["runner_result"] = runner()
        return {"status": "success"}

    monkeypatch.setattr("src.scheduler.daily_refresh_scheduler.run_guarded_job", fake_run_guarded_job)

    result = execute_daily_refresh_once(runner=lambda run_date: {"run_date": run_date.isoformat()})

    assert result["status"] == "success"
    assert captured["job_name"] == DAILY_REFRESH_JOB_NAME
    assert captured["run_date"] == date(2026, 6, 20)
    assert captured["runner_result"] == {"run_date": "2026-06-20"}


def test_scheduler_startup_catchup_uses_yesterday_target_date(monkeypatch) -> None:
    now = datetime(2026, 6, 20, 21, 30, tzinfo=UTC)
    startup_calls: list[date] = []

    monkeypatch.setattr("src.scheduler.daily_refresh_scheduler.utc_now", lambda: now)
    monkeypatch.setattr("src.scheduler.daily_refresh_scheduler._has_success_for_date", lambda run_date: False)
    monkeypatch.setattr(
        "src.scheduler.daily_refresh_scheduler.execute_daily_refresh_once",
        lambda *, run_date=None, runner=None: startup_calls.append(run_date),
    )
    monkeypatch.setattr(
        "src.scheduler.daily_refresh_scheduler.build_next_run_at",
        lambda _now: now + timedelta(days=1),
    )

    class StopAfterStartup:
        def is_set(self) -> bool:
            return False

        def wait(self, _seconds: float) -> bool:
            return True

    _scheduler_loop(StopAfterStartup(), runner=None)

    assert startup_calls == [
        date(2026, 6, 13),
        date(2026, 6, 14),
        date(2026, 6, 15),
        date(2026, 6, 16),
        date(2026, 6, 17),
        date(2026, 6, 18),
        date(2026, 6, 19),
        date(2026, 6, 20),
    ]


def test_scheduler_scheduled_run_uses_yesterday_target_date(monkeypatch) -> None:
    now = datetime(2026, 6, 21, 8, 0, tzinfo=UTC)
    scheduled_calls: list[date] = []

    monkeypatch.setattr("src.scheduler.daily_refresh_scheduler.utc_now", lambda: now)
    monkeypatch.setattr("src.scheduler.daily_refresh_scheduler._has_success_for_date", lambda run_date: True)
    monkeypatch.setattr(
        "src.scheduler.daily_refresh_scheduler.execute_daily_refresh_once",
        lambda *, run_date=None, runner=None: scheduled_calls.append(run_date),
    )
    monkeypatch.setattr("src.scheduler.daily_refresh_scheduler.build_next_run_at", lambda _now: now)

    class StopAfterScheduledRun:
        def __init__(self) -> None:
            self.calls = 0

        def is_set(self) -> bool:
            return False

        def wait(self, _seconds: float) -> bool:
            self.calls += 1
            return self.calls > 1

    _scheduler_loop(StopAfterScheduledRun(), runner=None)

    assert scheduled_calls == [date(2026, 6, 20)]


def test_default_runner_enables_core_refresh(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run_daily_dashboard_refresh(*, run_date, include_core_refresh):
        captured["run_date"] = run_date
        captured["include_core_refresh"] = include_core_refresh
        return {"ok": True}

    monkeypatch.setattr(
        "src.scheduler.daily_refresh_scheduler.run_daily_dashboard_refresh",
        fake_run_daily_dashboard_refresh,
    )

    scheduler_module = __import__("src.scheduler.daily_refresh_scheduler", fromlist=["_default_runner"])
    response = scheduler_module._default_runner(date(2026, 6, 21))

    assert response == {"ok": True}
    assert captured == {
        "run_date": date(2026, 6, 21),
        "include_core_refresh": True,
    }


def test_parse_args_uses_core_refresh_by_default_and_supports_explicit_skip(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_daily_dashboard_refresh.py"])
    args = daily_refresh_script.parse_args()

    assert args.include_core_refresh is True
    assert args.skip_core_refresh is False

    monkeypatch.setattr(sys, "argv", ["run_daily_dashboard_refresh.py", "--skip-core-refresh"])
    args = daily_refresh_script.parse_args()

    assert args.include_core_refresh is True
    assert args.skip_core_refresh is True
