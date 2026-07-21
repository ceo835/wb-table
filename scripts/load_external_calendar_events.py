from __future__ import annotations

import argparse
from datetime import date
import json
import os
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from src.db.connection import create_db_engine
from src.db.models import ExternalContextEvent
from src.services.external_context.calendar_config import calendar_events_for_year


_MUTABLE_FIELDS = (
    "source",
    "event_type",
    "title",
    "description",
    "date_start",
    "date_end",
    "region",
    "category",
    "impact_direction",
    "impact_strength",
    "confidence",
    "is_active",
    "source_reference",
    "metadata_json",
)


def _identity_filter(row: dict[str, Any]):
    conditions = [
        ExternalContextEvent.source == row["source"],
        ExternalContextEvent.event_code == row["event_code"],
        ExternalContextEvent.date_start == row["date_start"],
        ExternalContextEvent.date_end == row["date_end"],
        ExternalContextEvent.region.is_(None) if row.get("region") is None else ExternalContextEvent.region == row["region"],
        ExternalContextEvent.category.is_(None) if row.get("category") is None else ExternalContextEvent.category == row["category"],
    ]
    return and_(*conditions)


def apply_event_rows(session: Session, rows: list[dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "total": len(rows),
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "errors": 0,
        "error_details": [],
    }
    with session.begin():
        for row in rows:
            try:
                existing = session.scalar(select(ExternalContextEvent).where(_identity_filter(row)))
                if existing is None:
                    result["inserted"] += 1
                    if not dry_run:
                        session.add(ExternalContextEvent(**row))
                    continue
                changed = any(getattr(existing, field) != row.get(field) for field in _MUTABLE_FIELDS)
                if not changed:
                    result["unchanged"] += 1
                    continue
                result["updated"] += 1
                if not dry_run:
                    for field in _MUTABLE_FIELDS:
                        setattr(existing, field, row.get(field))
            except Exception as exc:
                result["errors"] += 1
                result["error_details"].append({"event_code": row.get("event_code"), "error": str(exc)})
    return result


def load_events(*, year: int, dry_run: bool, database_url: str | None = None) -> dict[str, Any]:
    rows = calendar_events_for_year(year)
    engine = create_db_engine(database_url=database_url, explicit_env=os.getenv("ENV"))
    with Session(engine) as session:
        result = apply_event_rows(session, rows, dry_run=dry_run)
    return {"year": year, "dry_run": dry_run, **result}


def main() -> int:
    parser = argparse.ArgumentParser(description="Load static external calendar events into external_context_event.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    print(json.dumps(load_events(year=args.year, dry_run=args.dry_run, database_url=args.database_url), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
