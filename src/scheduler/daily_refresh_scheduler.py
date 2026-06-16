from __future__ import annotations

import os
import threading
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Callable, Mapping

from scripts.run_daily_dashboard_refresh import run_daily_dashboard_refresh
from src.db.app_job_runs import JOB_STATUS_FAILED, JOB_STATUS_SKIPPED, JOB_STATUS_SUCCESS, has_successful_job_run, run_guarded_job
from src.db.connection import create_db_engine


DAILY_REFRESH_JOB_NAME = "dashboard_daily_refresh"
DAILY_REFRESH_HOUR_UTC = 8
_SCHEDULER_THREAD: threading.Thread | None = None
_SCHEDULER_STOP_EVENT: threading.Event | None = None
_SCHEDULER_LOCK = threading.Lock()


def utc_now() -> datetime:
    return datetime.now(UTC)


def log_scheduler(message: str) -> None:
    print(f"[daily-refresh-scheduler] {message}", flush=True)


def is_railway_environment(env: Mapping[str, str] | None = None) -> bool:
    runtime_env = env or os.environ
    return bool(runtime_env.get("RAILWAY_ENVIRONMENT") or runtime_env.get("RAILWAY_PROJECT_ID"))


def should_autostart_daily_refresh(env: Mapping[str, str] | None = None) -> bool:
    runtime_env = env or os.environ
    explicit = runtime_env.get("DASHBOARD_DAILY_REFRESH_AUTOSTART")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}
    return is_railway_environment(runtime_env)


def build_next_run_at(now: datetime) -> datetime:
    normalized_now = now.astimezone(UTC)
    scheduled_today = datetime.combine(
        normalized_now.date(),
        time(hour=DAILY_REFRESH_HOUR_UTC, minute=0, tzinfo=UTC),
    )
    if normalized_now < scheduled_today:
        return scheduled_today
    return scheduled_today + timedelta(days=1)


def should_run_startup_catchup(*, now: datetime, has_success_today: bool) -> bool:
    normalized_now = now.astimezone(UTC)
    scheduled_today = datetime.combine(
        normalized_now.date(),
        time(hour=DAILY_REFRESH_HOUR_UTC, minute=0, tzinfo=UTC),
    )
    return normalized_now >= scheduled_today and not has_success_today


def _default_runner(run_date: date) -> dict[str, Any]:
    return run_daily_dashboard_refresh(run_date=run_date, include_core_refresh=False)


def execute_daily_refresh_once(
    *,
    run_date: date | None = None,
    runner: Callable[[date], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_run_date = run_date or utc_now().date()
    resolved_runner = runner or _default_runner
    result = run_guarded_job(
        job_name=DAILY_REFRESH_JOB_NAME,
        run_date=resolved_run_date,
        runner=lambda: resolved_runner(resolved_run_date),
    )
    if result["status"] == JOB_STATUS_SKIPPED:
        reason = result.get("reason", "unknown")
        if reason == "already_completed":
            log_scheduler("Daily refresh skipped: already completed today")
        elif reason == "lock_not_acquired":
            log_scheduler("Daily refresh skipped: advisory lock not acquired")
        else:
            log_scheduler(f"Daily refresh skipped: {reason}")
    elif result["status"] == JOB_STATUS_SUCCESS:
        log_scheduler("Daily refresh finished")
    elif result["status"] == JOB_STATUS_FAILED:
        log_scheduler(f"Daily refresh failed: {result.get('error') or result.get('reason')}")
    return result


def _has_success_for_date(run_date: date) -> bool:
    engine = create_db_engine()
    with engine.connect() as connection:
        return has_successful_job_run(connection, DAILY_REFRESH_JOB_NAME, run_date)


def _scheduler_loop(stop_event: threading.Event, runner: Callable[[date], dict[str, Any]] | None) -> None:
    log_scheduler("Daily refresh scheduler enabled")

    now = utc_now()
    if should_run_startup_catchup(now=now, has_success_today=_has_success_for_date(now.date())):
        log_scheduler("Daily refresh started")
        execute_daily_refresh_once(run_date=now.date(), runner=runner)

    while not stop_event.is_set():
        next_run = build_next_run_at(utc_now())
        log_scheduler(f"Next run at {next_run.isoformat()}")
        wait_seconds = max((next_run - utc_now()).total_seconds(), 0.0)
        if stop_event.wait(wait_seconds):
            break
        log_scheduler("Daily refresh started")
        execute_daily_refresh_once(run_date=utc_now().date(), runner=runner)


def start_daily_refresh_scheduler_once(
    *,
    env: Mapping[str, str] | None = None,
    runner: Callable[[date], dict[str, Any]] | None = None,
) -> bool:
    global _SCHEDULER_THREAD, _SCHEDULER_STOP_EVENT

    if not should_autostart_daily_refresh(env):
        return False

    with _SCHEDULER_LOCK:
        if _SCHEDULER_THREAD is not None and _SCHEDULER_THREAD.is_alive():
            return True

        _SCHEDULER_STOP_EVENT = threading.Event()
        _SCHEDULER_THREAD = threading.Thread(
            target=_scheduler_loop,
            args=(_SCHEDULER_STOP_EVENT, runner),
            name="dashboard-daily-refresh-scheduler",
            daemon=True,
        )
        _SCHEDULER_THREAD.start()
        return True
