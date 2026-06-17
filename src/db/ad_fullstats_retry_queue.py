from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from src.db.models import AdFullstatsFailedGroup
from src.db.session import upsert_rows


AD_FULLSTATS_FAILED_GROUP_CONFLICT_COLUMNS = ("date_from", "date_to", "advert_id", "group_key")


def classify_fullstats_error_type(error_text: str) -> str:
    error_upper = (error_text or "").upper()
    if "429" in error_upper or "TOO MANY REQUESTS" in error_upper:
        return "RATE_LIMIT"
    if "500" in error_upper or "502" in error_upper or "503" in error_upper or "504" in error_upper:
        return "API_ERROR"
    if not (error_text or "").strip():
        return "EMPTY"
    return "API_ERROR"


def schedule_next_retry_at(
    attempted_at: datetime,
    *,
    attempts_count: int,
    retry_delay_seconds: int = 25,
) -> datetime:
    multiplier = max(int(attempts_count), 1)
    return attempted_at + timedelta(seconds=retry_delay_seconds * multiplier)


def build_failed_group_row(
    *,
    date_from: date,
    date_to: date,
    advert_id: int,
    group_key: str,
    campaign_name: str | None,
    nm_ids: Sequence[int] | None,
    error_type: str | None = None,
    last_error: str,
    attempted_at: datetime,
    attempts_count: int,
    retry_delay_seconds: int = 25,
) -> dict[str, Any]:
    resolved_error_type = error_type or classify_fullstats_error_type(last_error)
    return {
        "date_from": date_from,
        "date_to": date_to,
        "advert_id": int(advert_id),
        "group_key": group_key,
        "campaign_name": campaign_name or None,
        "nm_ids_json": [int(nm_id) for nm_id in (nm_ids or [])],
        "error_type": resolved_error_type,
        "attempts_count": int(attempts_count),
        "last_error": last_error or None,
        "last_attempt_at": attempted_at,
        "next_retry_at": schedule_next_retry_at(
            attempted_at,
            attempts_count=attempts_count,
            retry_delay_seconds=retry_delay_seconds,
        ),
        "status": "pending",
        "updated_at": attempted_at,
    }


def prepare_failed_group_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: dict[tuple[date, date, int, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("date_from"),
            row.get("date_to"),
            int(row.get("advert_id")),
            str(row.get("group_key")),
        )
        deduplicated[key] = {
            "date_from": row.get("date_from"),
            "date_to": row.get("date_to"),
            "advert_id": int(row.get("advert_id")),
            "group_key": str(row.get("group_key")),
            "campaign_name": row.get("campaign_name") or None,
            "nm_ids_json": row.get("nm_ids_json") or None,
            "error_type": row.get("error_type") or None,
            "attempts_count": int(row.get("attempts_count") or 0),
            "last_error": row.get("last_error") or None,
            "last_attempt_at": row.get("last_attempt_at"),
            "next_retry_at": row.get("next_retry_at"),
            "status": row.get("status") or "pending",
            "updated_at": row.get("updated_at") or row.get("last_attempt_at"),
        }
    return list(deduplicated.values())


def upsert_failed_groups(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_failed_group_upsert_rows(rows)
    return upsert_rows(
        session=session,
        model=AdFullstatsFailedGroup,
        rows=prepared_rows,
        conflict_columns=AD_FULLSTATS_FAILED_GROUP_CONFLICT_COLUMNS,
    )


def get_failed_group_attempts_count(
    session: Session,
    *,
    date_from: date,
    date_to: date,
    advert_id: int,
    group_key: str,
) -> int:
    stmt = (
        select(AdFullstatsFailedGroup.attempts_count)
        .where(
            AdFullstatsFailedGroup.date_from == date_from,
            AdFullstatsFailedGroup.date_to == date_to,
            AdFullstatsFailedGroup.advert_id == advert_id,
            AdFullstatsFailedGroup.group_key == group_key,
        )
        .limit(1)
    )
    value = session.execute(stmt).scalar_one_or_none()
    return int(value or 0)


def mark_failed_group_success(
    session: Session,
    *,
    date_from: date,
    date_to: date,
    advert_id: int,
    group_key: str,
    attempted_at: datetime,
) -> int:
    stmt = (
        update(AdFullstatsFailedGroup)
        .where(
            AdFullstatsFailedGroup.date_from == date_from,
            AdFullstatsFailedGroup.date_to == date_to,
            AdFullstatsFailedGroup.advert_id == advert_id,
            AdFullstatsFailedGroup.group_key == group_key,
        )
        .values(
            status="success",
            last_error=None,
            last_attempt_at=attempted_at,
            next_retry_at=None,
            updated_at=attempted_at,
        )
    )
    result = session.execute(stmt)
    return result.rowcount or 0


def load_due_failed_group_rows(
    session: Session,
    *,
    date_from: date,
    date_to: date,
    due_at: datetime | None = None,
) -> list[AdFullstatsFailedGroup]:
    effective_due_at = due_at or datetime.now().astimezone()
    stmt = (
        select(AdFullstatsFailedGroup)
        .where(
            AdFullstatsFailedGroup.date_from == date_from,
            AdFullstatsFailedGroup.date_to == date_to,
            AdFullstatsFailedGroup.status == "pending",
            or_(
                and_(
                    AdFullstatsFailedGroup.next_retry_at.is_(None),
                    AdFullstatsFailedGroup.last_attempt_at.is_(None),
                ),
                AdFullstatsFailedGroup.next_retry_at <= effective_due_at,
            ),
        )
        .order_by(AdFullstatsFailedGroup.next_retry_at.asc().nullsfirst(), AdFullstatsFailedGroup.advert_id.asc())
    )
    return list(session.execute(stmt).scalars())
