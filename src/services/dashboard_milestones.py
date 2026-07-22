from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import DashboardMilestone
from src.db.session import session_scope

MILESTONE_TYPES: dict[str, str] = {
    "price_discount": "Цена / скидка",
    "advertising": "Реклама",
    "stock_supply": "Поставка / остатки",
    "content": "Карточка / контент",
    "technical": "Техническая проблема",
    "other": "Другое",
}

DEFAULT_MILESTONE_TYPE: str = "price_discount"


def _milestone_to_dict(milestone: DashboardMilestone) -> dict[str, Any]:
    return {
        "id": milestone.id,
        "milestone_date": milestone.milestone_date,
        "milestone_type": milestone.milestone_type,
        "milestone_type_label": MILESTONE_TYPES.get(milestone.milestone_type, milestone.milestone_type),
        "title": milestone.title,
        "comment": milestone.comment,
        "created_at": milestone.created_at,
        "updated_at": milestone.updated_at,
        "is_active": milestone.is_active,
    }


def list_milestones(
    date_from: date | None = None,
    date_to: date | None = None,
    types: list[str] | None = None,
    include_inactive: bool = False,
    session: Session | None = None,
) -> list[dict[str, Any]]:
    def _execute(sess: Session) -> list[dict[str, Any]]:
        stmt = select(DashboardMilestone)
        if not include_inactive:
            stmt = stmt.where(DashboardMilestone.is_active.is_(True))
        if date_from is not None:
            stmt = stmt.where(DashboardMilestone.milestone_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(DashboardMilestone.milestone_date <= date_to)
        if types is not None:
            stmt = stmt.where(DashboardMilestone.milestone_type.in_(types))
        stmt = stmt.order_by(DashboardMilestone.milestone_date.asc(), DashboardMilestone.id.asc())
        records = sess.scalars(stmt).all()
        return [_milestone_to_dict(r) for r in records]

    if session is not None:
        return _execute(session)
    with session_scope() as sess:
        return _execute(sess)


def create_milestone(
    milestone_date: date,
    milestone_type: str,
    title: str,
    comment: str | None = None,
    session: Session | None = None,
) -> dict[str, Any]:
    title_clean = title.strip() if title else ""
    if not title_clean:
        raise ValueError("Название вехи не может быть пустым")
    if milestone_type not in MILESTONE_TYPES:
        raise ValueError(f"Недопустимый тип вехи: {milestone_type}")

    comment_clean = comment.strip() if comment and comment.strip() else None

    def _execute(sess: Session) -> dict[str, Any]:
        item = DashboardMilestone(
            milestone_date=milestone_date,
            milestone_type=milestone_type,
            title=title_clean,
            comment=comment_clean,
            is_active=True,
        )
        sess.add(item)
        sess.flush()
        return _milestone_to_dict(item)

    if session is not None:
        return _execute(session)
    with session_scope() as sess:
        return _execute(sess)


def update_milestone(
    milestone_id: int,
    milestone_date: date | None = None,
    milestone_type: str | None = None,
    title: str | None = None,
    comment: str | None = None,
    is_active: bool | None = None,
    session: Session | None = None,
) -> dict[str, Any] | None:
    def _execute(sess: Session) -> dict[str, Any] | None:
        item = sess.get(DashboardMilestone, milestone_id)
        if item is None:
            return None
        if milestone_date is not None:
            item.milestone_date = milestone_date
        if milestone_type is not None:
            if milestone_type not in MILESTONE_TYPES:
                raise ValueError(f"Недопустимый тип вехи: {milestone_type}")
            item.milestone_type = milestone_type
        if title is not None:
            title_clean = title.strip()
            if not title_clean:
                raise ValueError("Название вехи не может быть пустым")
            item.title = title_clean
        if comment is not None:
            item.comment = comment.strip() if comment and comment.strip() else None
        if is_active is not None:
            item.is_active = is_active
        sess.flush()
        return _milestone_to_dict(item)

    if session is not None:
        return _execute(session)
    with session_scope() as sess:
        return _execute(sess)


def deactivate_milestone(milestone_id: int, session: Session | None = None) -> bool:
    result = update_milestone(milestone_id=milestone_id, is_active=False, session=session)
    return result is not None
