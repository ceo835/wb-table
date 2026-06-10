from __future__ import annotations

from contextlib import contextmanager
from typing import Iterable, Iterator, Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.db.connection import create_db_engine


def build_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    resolved_engine = engine or create_db_engine()
    return sessionmaker(bind=resolved_engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    session_factory = build_session_factory(engine=engine)
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def build_postgres_upsert_statement(
    model,
    rows: Sequence[dict],
    conflict_columns: Sequence[str],
    update_columns: Sequence[str] | None = None,
):
    if not rows:
        raise ValueError("rows не могут быть пустыми для upsert")

    table = model.__table__
    stmt = pg_insert(table).values(list(rows))
    if update_columns is None:
        update_columns = [
            column.name
            for column in table.columns
            if column.name not in set(conflict_columns) and not column.primary_key
        ]

    set_map = {column_name: getattr(stmt.excluded, column_name) for column_name in update_columns}
    return stmt.on_conflict_do_update(
        index_elements=[table.c[column_name] for column_name in conflict_columns],
        set_=set_map,
    )


def upsert_rows(
    session: Session,
    model,
    rows: Sequence[dict],
    conflict_columns: Sequence[str],
    update_columns: Sequence[str] | None = None,
    batch_size: int | None = None,
) -> int:
    if not rows:
        return 0
    if batch_size is None or batch_size <= 0 or len(rows) <= batch_size:
        stmt = build_postgres_upsert_statement(
            model=model,
            rows=rows,
            conflict_columns=conflict_columns,
            update_columns=update_columns,
        )
        result = session.execute(stmt)
        return result.rowcount or 0

    total_rowcount = 0
    for index in range(0, len(rows), batch_size):
        chunk = rows[index:index + batch_size]
        stmt = build_postgres_upsert_statement(
            model=model,
            rows=chunk,
            conflict_columns=conflict_columns,
            update_columns=update_columns,
        )
        result = session.execute(stmt)
        total_rowcount += result.rowcount or 0
    return total_rowcount
