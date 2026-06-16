from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Any, Callable

from sqlalchemy import Engine, func, select, text

from src.db.connection import create_db_engine
from src.db.models import AppJobRun


JOB_STATUS_RUNNING = "running"
JOB_STATUS_SUCCESS = "success"
JOB_STATUS_FAILED = "failed"
JOB_STATUS_SKIPPED = "skipped"


def utc_now() -> datetime:
    return datetime.now(UTC)


def advisory_lock_key(job_name: str) -> int:
    digest = hashlib.sha256(job_name.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, byteorder="big", signed=True)


def try_acquire_job_lock(connection, job_name: str) -> bool:
    if connection.dialect.name != "postgresql":
        return True
    lock_key = advisory_lock_key(job_name)
    return bool(connection.execute(text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": lock_key}).scalar())


def release_job_lock(connection, job_name: str) -> None:
    if connection.dialect.name != "postgresql":
        return
    lock_key = advisory_lock_key(job_name)
    connection.execute(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": lock_key})


def has_successful_job_run(connection, job_name: str, run_date: date) -> bool:
    result = connection.execute(
        select(AppJobRun.id).where(
            AppJobRun.job_name == job_name,
            AppJobRun.run_date == run_date,
            AppJobRun.status == JOB_STATUS_SUCCESS,
        )
    ).first()
    return result is not None


def mark_job_running(connection, job_name: str, run_date: date, started_at: datetime) -> int | None:
    existing = connection.execute(
        select(AppJobRun.id).where(
            AppJobRun.job_name == job_name,
            AppJobRun.run_date == run_date,
        )
    ).first()

    values = {
        "job_name": job_name,
        "run_date": run_date,
        "started_at": started_at,
        "finished_at": None,
        "status": JOB_STATUS_RUNNING,
        "summary_path": None,
        "error": None,
        "updated_at": func.now(),
    }
    table = AppJobRun.__table__
    if existing is None:
        result = connection.execute(table.insert().values(**values, created_at=func.now()))
        primary_key = result.inserted_primary_key
        return int(primary_key[0]) if primary_key else None

    job_run_id = int(existing[0])
    connection.execute(
        table.update()
        .where(table.c.id == job_run_id)
        .values(**values)
    )
    return job_run_id


def finalize_job_run(
    connection,
    *,
    job_name: str,
    run_date: date,
    status: str,
    finished_at: datetime,
    summary_path: str | None = None,
    error: str | None = None,
) -> None:
    table = AppJobRun.__table__
    connection.execute(
        table.update()
        .where(
            table.c.job_name == job_name,
            table.c.run_date == run_date,
        )
        .values(
            finished_at=finished_at,
            status=status,
            summary_path=summary_path,
            error=error,
            updated_at=func.now(),
        )
    )


def extract_summary_path(summary: Any) -> str | None:
    if not isinstance(summary, dict):
        return None
    artifacts = summary.get("artifacts")
    if isinstance(artifacts, dict):
        json_path = artifacts.get("json_path")
        if isinstance(json_path, str) and json_path.strip():
            return json_path
    summary_path = summary.get("summary_path")
    if isinstance(summary_path, str) and summary_path.strip():
        return summary_path
    return None


def run_guarded_job(
    *,
    job_name: str,
    run_date: date,
    runner: Callable[[], Any],
    engine: Engine | None = None,
) -> dict[str, Any]:
    resolved_engine = engine or create_db_engine()
    with resolved_engine.connect() as connection:
        if not try_acquire_job_lock(connection, job_name):
            return {
                "status": JOB_STATUS_SKIPPED,
                "reason": "lock_not_acquired",
                "job_name": job_name,
                "run_date": run_date.isoformat(),
            }

        try:
            if has_successful_job_run(connection, job_name, run_date):
                return {
                    "status": JOB_STATUS_SKIPPED,
                    "reason": "already_completed",
                    "job_name": job_name,
                    "run_date": run_date.isoformat(),
                }

            started_at = utc_now()
            job_run_id = mark_job_running(connection, job_name, run_date, started_at)
            connection.commit()

            try:
                summary = runner()
            except Exception as exc:
                finalize_job_run(
                    connection,
                    job_name=job_name,
                    run_date=run_date,
                    status=JOB_STATUS_FAILED,
                    finished_at=utc_now(),
                    error=str(exc),
                )
                connection.commit()
                return {
                    "status": JOB_STATUS_FAILED,
                    "reason": "exception",
                    "error": str(exc),
                    "job_name": job_name,
                    "run_date": run_date.isoformat(),
                    "job_run_id": job_run_id,
                }

            success = True
            if isinstance(summary, dict) and summary.get("success") is False:
                success = False
            status = JOB_STATUS_SUCCESS if success else JOB_STATUS_FAILED
            error = None
            if isinstance(summary, dict) and not success:
                error = str(summary.get("error_message") or "runner_reported_failure")
            finalize_job_run(
                connection,
                job_name=job_name,
                run_date=run_date,
                status=status,
                finished_at=utc_now(),
                summary_path=extract_summary_path(summary),
                error=error,
            )
            connection.commit()
            return {
                "status": status,
                "reason": "completed" if success else "runner_reported_failure",
                "job_name": job_name,
                "run_date": run_date.isoformat(),
                "job_run_id": job_run_id,
                "summary": summary,
            }
        finally:
            release_job_lock(connection, job_name)
            connection.commit()
