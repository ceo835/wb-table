from __future__ import annotations

import os
import threading
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from scripts.run_daily_dashboard_refresh import DEFAULT_DASHBOARD_START_DATE, resolve_default_target_date, run_daily_dashboard_refresh
from src.db.app_job_runs import JOB_STATUS_FAILED, JOB_STATUS_SKIPPED, JOB_STATUS_SUCCESS, has_successful_job_run, run_guarded_job
from src.db.connection import create_db_engine


DAILY_REFRESH_JOB_NAME = "dashboard_daily_refresh"
DAILY_REFRESH_HOUR_UTC = 8
WORKER_TIMEZONE_NAME = "Europe/Moscow"
VVBROMO_JOB_NAME = "vvbromo_sync"
IVAN_STOCK_JOB_NAME = "ivan_stock_sync"
OZON_PRICE_SNAPSHOT_JOB_NAME = "ozon_price_snapshot_sync"
VVBROMO_MORNING_GUARD_JOB_NAME = "vvbromo_sync__0900_msk"
OZON_PRICE_SNAPSHOT_GUARD_JOB_NAME = "ozon_price_snapshot_sync__1000_msk"
IVAN_STOCK_GUARD_JOB_NAME = "ivan_stock_sync__2200_msk"
WORKER_SUMMARY_DIR = Path(__file__).resolve().parents[2] / "data" / "processed" / "scheduler_runs"
_SCHEDULER_THREAD: threading.Thread | None = None
_SCHEDULER_STOP_EVENT: threading.Event | None = None
_SCHEDULER_LOCK = threading.Lock()


@dataclass(frozen=True)
class WorkerJobSlot:
    guard_job_name: str
    job_name: str
    slot_label: str
    hour_msk: int
    minute_msk: int
    run_date_mode: str
    runner: Callable[[date], dict[str, Any]]


def utc_now() -> datetime:
    return datetime.now(UTC)


def log_scheduler(message: str) -> None:
    print(f"[daily-refresh-scheduler] {message}", flush=True)


def moscow_now() -> datetime:
    return datetime.now(ZoneInfo(WORKER_TIMEZONE_NAME))


def _persist_worker_job_summary(
    *,
    job_name: str,
    slot_label: str,
    run_date: date,
    summary: dict[str, Any],
) -> str:
    WORKER_SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    output_path = WORKER_SUMMARY_DIR / f"{job_name}_{slot_label}_{run_date.isoformat()}.json"
    payload = {
        "job_name": job_name,
        "slot_label": slot_label,
        "run_date": run_date.isoformat(),
        **summary,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(output_path)


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
    log_scheduler(f"Launching daily refresh for target_date={run_date.isoformat()} include_core_refresh=True")
    return run_daily_dashboard_refresh(run_date=run_date, include_core_refresh=True)


def _run_vvbromo_sync(run_date: date) -> dict[str, Any]:
    from src.config.settings import settings

    if settings.vvbromo_google_drive_folder_id:
        from src.services.google_drive_daily_sync import sync_vvbromo_from_google_drive

        return sync_vvbromo_from_google_drive(run_date=run_date, write_db=True)

    from scripts.parse_vvbromo_sheet import run_loader

    summary = run_loader(year=run_date.year, apply=True, dry_run=False)
    summary = dict(summary)
    summary["success"] = True
    return summary


def _run_ivan_stock_sync(run_date: date) -> dict[str, Any]:
    from src.config.settings import settings

    if settings.ivan_stock_google_drive_folder_id:
        from src.services.google_drive_daily_sync import sync_ivan_stock_from_google_drive

        return sync_ivan_stock_from_google_drive(run_date=run_date, write_db=True)

    from src.db.ivan_stock_sheet_loader import load_ivan_stock_sheet

    summary = load_ivan_stock_sheet(write_db=True)
    summary = dict(summary)
    summary["success"] = bool(summary.get("success", True))
    return summary


def _run_ozon_price_snapshot_sync(_run_date: date) -> dict[str, Any]:
    from src.db.ozon_price_snapshot_loader import collect_and_load_ozon_snapshots

    summary = collect_and_load_ozon_snapshots(headless=True, connect_cdp_url="", dry_run=False)
    summary = dict(summary)
    summary["success"] = summary.get("status") == "success"
    return summary


def execute_daily_refresh_once(
    *,
    run_date: date | None = None,
    runner: Callable[[date], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_run_date = run_date or resolve_default_target_date(utc_now())
    resolved_runner = runner or _default_runner
    result = run_guarded_job(
        job_name=DAILY_REFRESH_JOB_NAME,
        run_date=resolved_run_date,
        runner=lambda: resolved_runner(resolved_run_date),
    )
    if result["status"] == JOB_STATUS_SKIPPED:
        reason = result.get("reason", "unknown")
        if reason == "already_completed":
            log_scheduler(f"Daily refresh skipped: already completed for {resolved_run_date.isoformat()}")
        elif reason == "lock_not_acquired":
            log_scheduler("Daily refresh skipped: advisory lock not acquired")
        else:
            log_scheduler(f"Daily refresh skipped: {reason}")
    elif result["status"] == JOB_STATUS_SUCCESS:
        log_scheduler("Daily refresh finished")
    elif result["status"] == JOB_STATUS_FAILED:
        log_scheduler(f"Daily refresh failed: {result.get('error') or result.get('reason')}")
    return result


def build_worker_job_slots(
    *,
    dashboard_runner: Callable[[date], dict[str, Any]] | None = None,
    vvbromo_runner: Callable[[date], dict[str, Any]] | None = None,
    ivan_stock_runner: Callable[[date], dict[str, Any]] | None = None,
    ozon_runner: Callable[[date], dict[str, Any]] | None = None,
) -> list[WorkerJobSlot]:
    return [
        WorkerJobSlot(
            guard_job_name=VVBROMO_MORNING_GUARD_JOB_NAME,
            job_name=VVBROMO_JOB_NAME,
            slot_label="0900_msk",
            hour_msk=9,
            minute_msk=0,
            run_date_mode="today_msk",
            runner=vvbromo_runner or _run_vvbromo_sync,
        ),
        WorkerJobSlot(
            guard_job_name=OZON_PRICE_SNAPSHOT_GUARD_JOB_NAME,
            job_name=OZON_PRICE_SNAPSHOT_JOB_NAME,
            slot_label="1000_msk",
            hour_msk=10,
            minute_msk=0,
            run_date_mode="today_msk",
            runner=ozon_runner or _run_ozon_price_snapshot_sync,
        ),
        WorkerJobSlot(
            guard_job_name=DAILY_REFRESH_JOB_NAME,
            job_name=DAILY_REFRESH_JOB_NAME,
            slot_label="1100_msk",
            hour_msk=11,
            minute_msk=0,
            run_date_mode="yesterday_msk",
            runner=dashboard_runner or _default_runner,
        ),
        WorkerJobSlot(
            guard_job_name=IVAN_STOCK_GUARD_JOB_NAME,
            job_name=IVAN_STOCK_JOB_NAME,
            slot_label="2200_msk",
            hour_msk=22,
            minute_msk=0,
            run_date_mode="today_msk",
            runner=ivan_stock_runner or _run_ivan_stock_sync,
        ),
    ]


def resolve_worker_job_run_date(slot: WorkerJobSlot, now: datetime) -> date:
    local_now = now.astimezone(ZoneInfo(WORKER_TIMEZONE_NAME))
    if slot.run_date_mode == "yesterday_msk":
        return local_now.date() - timedelta(days=1)
    return local_now.date()


def build_next_worker_run_at(now: datetime, job_slots: list[WorkerJobSlot]) -> datetime:
    local_now = now.astimezone(ZoneInfo(WORKER_TIMEZONE_NAME))
    next_runs: list[datetime] = []
    for slot in job_slots:
        scheduled_today = datetime.combine(
            local_now.date(),
            time(hour=slot.hour_msk, minute=slot.minute_msk, tzinfo=local_now.tzinfo),
        )
        next_runs.append(scheduled_today if local_now < scheduled_today else scheduled_today + timedelta(days=1))
    return min(next_runs)


def _has_success_for_job_date(job_name: str, run_date: date) -> bool:
    engine = create_db_engine()
    with engine.connect() as connection:
        return has_successful_job_run(connection, job_name, run_date)


def collect_due_worker_job_slots(
    now: datetime,
    job_slots: list[WorkerJobSlot],
    *,
    has_success_checker: Callable[[str, date], bool] | None = None,
) -> list[tuple[WorkerJobSlot, date]]:
    local_now = now.astimezone(ZoneInfo(WORKER_TIMEZONE_NAME))
    checker = has_success_checker or _has_success_for_job_date
    due_slots: list[tuple[WorkerJobSlot, date]] = []
    for slot in job_slots:
        scheduled_today = datetime.combine(
            local_now.date(),
            time(hour=slot.hour_msk, minute=slot.minute_msk, tzinfo=local_now.tzinfo),
        )
        run_date = resolve_worker_job_run_date(slot, local_now)
        if local_now >= scheduled_today and not checker(slot.guard_job_name, run_date):
            due_slots.append((slot, run_date))
    due_slots.sort(key=lambda item: (item[0].hour_msk, item[0].minute_msk, item[0].guard_job_name))
    return due_slots


def execute_worker_job_slot_once(
    slot: WorkerJobSlot,
    *,
    run_date: date,
) -> dict[str, Any]:
    result = run_guarded_job(
        job_name=slot.guard_job_name,
        run_date=run_date,
        runner=lambda: _finalize_worker_job_summary(slot=slot, run_date=run_date, summary=slot.runner(run_date)),
    )
    if result["status"] == JOB_STATUS_SUCCESS:
        log_scheduler(f"{slot.job_name} [{slot.slot_label}] finished for run_date={run_date.isoformat()}")
    elif result["status"] == JOB_STATUS_SKIPPED:
        log_scheduler(
            f"{slot.job_name} [{slot.slot_label}] skipped for run_date={run_date.isoformat()}: {result.get('reason')}"
        )
    else:
        log_scheduler(
            f"{slot.job_name} [{slot.slot_label}] failed for run_date={run_date.isoformat()}: "
            f"{result.get('error') or result.get('reason')}"
        )
    return result


def _finalize_worker_job_summary(
    *,
    slot: WorkerJobSlot,
    run_date: date,
    summary: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(summary)
    normalized.setdefault("success", True)
    normalized["job_name"] = slot.job_name
    normalized["guard_job_name"] = slot.guard_job_name
    normalized["slot_label"] = slot.slot_label
    normalized["run_date"] = run_date.isoformat()
    normalized["summary_path"] = _persist_worker_job_summary(
        job_name=slot.job_name,
        slot_label=slot.slot_label,
        run_date=run_date,
        summary=normalized,
    )
    return normalized


def run_due_worker_job_slots(
    now: datetime,
    job_slots: list[WorkerJobSlot],
    *,
    has_success_checker: Callable[[str, date], bool] | None = None,
    executor: Callable[[WorkerJobSlot, date], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    resolved_executor = executor or (lambda slot, run_date: execute_worker_job_slot_once(slot, run_date=run_date))
    results: list[dict[str, Any]] = []
    for slot, run_date in collect_due_worker_job_slots(now, job_slots, has_success_checker=has_success_checker):
        try:
            results.append(resolved_executor(slot, run_date))
        except Exception as exc:
            log_scheduler(
                f"{slot.job_name} [{slot.slot_label}] crashed for run_date={run_date.isoformat()}: {exc}"
            )
            results.append(
                {
                    "status": JOB_STATUS_FAILED,
                    "job_name": slot.job_name,
                    "guard_job_name": slot.guard_job_name,
                    "slot_label": slot.slot_label,
                    "run_date": run_date.isoformat(),
                    "error": str(exc),
                }
            )
    return results


def run_scheduler_worker_once(
    *,
    now: datetime | None = None,
    job_slots: list[WorkerJobSlot] | None = None,
    has_success_checker: Callable[[str, date], bool] | None = None,
    executor: Callable[[WorkerJobSlot, date], dict[str, Any]] | None = None,
    include_startup_catchup: bool = True,
) -> list[dict[str, Any]]:
    local_now = (now or moscow_now()).astimezone(ZoneInfo(WORKER_TIMEZONE_NAME))
    slots = job_slots or build_worker_job_slots()
    checker = has_success_checker or _has_success_for_job_date
    resolved_executor = executor or (lambda slot, run_date: execute_worker_job_slot_once(slot, run_date=run_date))
    results: list[dict[str, Any]] = []

    if include_startup_catchup:
        dashboard_slots = [slot for slot in slots if slot.job_name == DAILY_REFRESH_JOB_NAME]
        if dashboard_slots:
            dashboard_slot = dashboard_slots[0]
            yesterday = resolve_default_target_date(local_now.astimezone(UTC))
            start_catchup = max(DEFAULT_DASHBOARD_START_DATE, yesterday - timedelta(days=7))
            current_date = start_catchup
            while current_date <= yesterday:
                if not checker(dashboard_slot.guard_job_name, current_date):
                    try:
                        results.append(resolved_executor(dashboard_slot, current_date))
                    except Exception as exc:
                        log_scheduler(f"{dashboard_slot.job_name} catchup crashed for {current_date.isoformat()}: {exc}")
                        results.append(
                            {
                                "status": JOB_STATUS_FAILED,
                                "job_name": dashboard_slot.job_name,
                                "guard_job_name": dashboard_slot.guard_job_name,
                                "slot_label": dashboard_slot.slot_label,
                                "run_date": current_date.isoformat(),
                                "error": str(exc),
                            }
                        )
                current_date += timedelta(days=1)

    results.extend(run_due_worker_job_slots(local_now, slots, has_success_checker=checker, executor=resolved_executor))
    return results


def run_scheduler_worker_loop(
    *,
    stop_event: threading.Event | None = None,
    job_slots: list[WorkerJobSlot] | None = None,
) -> None:
    slots = job_slots or build_worker_job_slots()
    local_stop_event = stop_event or threading.Event()
    first_iteration = True
    log_scheduler("Unified scheduler worker enabled")
    while not local_stop_event.is_set():
        run_scheduler_worker_once(
            now=moscow_now(),
            job_slots=slots,
            include_startup_catchup=first_iteration,
        )
        first_iteration = False
        next_run_at = build_next_worker_run_at(moscow_now(), slots)
        log_scheduler(f"Next unified worker run at {next_run_at.isoformat()}")
        wait_seconds = max((next_run_at - moscow_now()).total_seconds(), 0.0)
        if local_stop_event.wait(wait_seconds):
            break


def _has_success_for_date(run_date: date) -> bool:
    return _has_success_for_job_date(DAILY_REFRESH_JOB_NAME, run_date)


def _scheduler_loop(stop_event: threading.Event, runner: Callable[[date], dict[str, Any]] | None) -> None:
    log_scheduler("Daily refresh scheduler enabled")

    now = utc_now()
    yesterday = resolve_default_target_date(now)
    # Check last 7 days for any missing daily refreshes
    start_catchup = max(DEFAULT_DASHBOARD_START_DATE, yesterday - timedelta(days=7))
    current_date = start_catchup
    while current_date <= yesterday:
        if not _has_success_for_date(current_date):
            log_scheduler(f"Catchup: Daily refresh started for {current_date.isoformat()}")
            execute_daily_refresh_once(run_date=current_date, runner=runner)
        current_date += timedelta(days=1)

    while not stop_event.is_set():
        next_run = build_next_run_at(utc_now())
        log_scheduler(f"Next run at {next_run.isoformat()}")
        wait_seconds = max((next_run - utc_now()).total_seconds(), 0.0)
        if stop_event.wait(wait_seconds):
            break
        log_scheduler("Daily refresh started")
        execute_daily_refresh_once(run_date=resolve_default_target_date(utc_now()), runner=runner)


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
