from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import GoogleDriveSourceFile
from src.db.session import upsert_rows


def load_google_drive_source_file_index(session: Session, source_type: str) -> dict[str, GoogleDriveSourceFile]:
    rows = session.scalars(
        select(GoogleDriveSourceFile).where(GoogleDriveSourceFile.source_type == source_type)
    ).all()
    return {str(row.google_file_id): row for row in rows}


def upsert_google_drive_source_file(session: Session, row: dict) -> int:
    return upsert_rows(
        session=session,
        model=GoogleDriveSourceFile,
        rows=[row],
        conflict_columns=("source_type", "google_file_id"),
    )


def bulk_upsert_google_drive_source_files(session: Session, rows: Sequence[dict]) -> int:
    if not rows:
        return 0
    return upsert_rows(
        session=session,
        model=GoogleDriveSourceFile,
        rows=list(rows),
        conflict_columns=("source_type", "google_file_id"),
    )
