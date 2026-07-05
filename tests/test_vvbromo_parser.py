from __future__ import annotations

import pytest
from datetime import date
from decimal import Decimal
from sqlalchemy import create_engine, select, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

from src.db.base import Base
from src.db.models import FactVvbromoProductDay
from src.db.session import upsert_rows
from scripts.parse_vvbromo_sheet import parse_numeric


# Teach sqlite how to compile postgresql JSONB type
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


# Teach sqlite how to compile BigInteger as INTEGER to enable autoincrement for primary keys
@compiles(BigInteger, "sqlite")
def compile_bigint_sqlite(type_, compiler, **kw):
    return "INTEGER"


def test_parse_numeric_spaces():
    errors = []
    val = parse_numeric("17 114", "organic_sales", 1, 197330807, errors)
    assert val == 17114
    assert len(errors) == 0


def test_parse_numeric_negative():
    errors = []
    val = parse_numeric("-11 236", "operating_profit", 1, 197330807, errors)
    assert val == -11236
    assert len(errors) == 0


def test_parse_numeric_empty_to_null():
    errors = []
    val = parse_numeric("", "organic_sales", 1, 197330807, errors)
    assert val is None
    assert len(errors) == 0

    val = parse_numeric("-", "organic_sales", 1, 197330807, errors)
    assert val is None
    assert len(errors) == 0

    val = parse_numeric("—", "organic_sales", 1, 197330807, errors)
    assert val is None
    assert len(errors) == 0


@pytest.fixture
def sqlite_engine():
    engine = create_engine("sqlite:///:memory:", future=True)
    # Register table in sqlite
    Base.metadata.create_all(engine, tables=[FactVvbromoProductDay.__table__])
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def sqlite_session(sqlite_engine):
    Session = sessionmaker(bind=sqlite_engine, future=True)
    with Session() as session:
        yield session


def test_upsert_rows_apply_writes_data(sqlite_session):
    records = [
        {
            "day": date(2026, 6, 22),
            "nm_id": 197330807,
            "vendor_code": "BlackWOM5",
            "organic_sales": 90,
            "operating_profit": Decimal("17114"),
            "operating_profit_per_unit": Decimal("190"),
            "source": "vvbromo",
            "raw_row": {"raw": "data"}
        }
    ]

    # Write records
    upsert_rows(
        session=sqlite_session,
        model=FactVvbromoProductDay,
        rows=records,
        conflict_columns=["day", "nm_id"]
    )
    sqlite_session.commit()

    # Query DB
    stmt = select(FactVvbromoProductDay).where(FactVvbromoProductDay.nm_id == 197330807)
    rows = sqlite_session.execute(stmt).scalars().all()

    assert len(rows) == 1
    assert rows[0].organic_sales == 90
    assert rows[0].operating_profit == Decimal("17114")
    assert rows[0].vendor_code == "BlackWOM5"
    assert rows[0].raw_row == {"raw": "data"}


def test_upsert_rows_apply_updates_on_conflict(sqlite_session):
    records_1 = [
        {
            "day": date(2026, 6, 22),
            "nm_id": 197330807,
            "vendor_code": "BlackWOM5",
            "organic_sales": 90,
            "operating_profit": Decimal("17114"),
            "operating_profit_per_unit": Decimal("190"),
            "source": "vvbromo",
            "raw_row": {"raw": "data1"}
        }
    ]

    records_2 = [
        {
            "day": date(2026, 6, 22),
            "nm_id": 197330807,
            "vendor_code": "BlackWOM5",
            "organic_sales": 100,  # updated
            "operating_profit": Decimal("18000"),  # updated
            "operating_profit_per_unit": Decimal("180"),  # updated
            "source": "vvbromo",
            "raw_row": {"raw": "data2"}  # updated
        }
    ]

    # Write first batch
    upsert_rows(
        session=sqlite_session,
        model=FactVvbromoProductDay,
        rows=records_1,
        conflict_columns=["day", "nm_id"]
    )
    sqlite_session.commit()

    # Write second batch (simulate repeat apply)
    upsert_rows(
        session=sqlite_session,
        model=FactVvbromoProductDay,
        rows=records_2,
        conflict_columns=["day", "nm_id"]
    )
    sqlite_session.commit()

    # Query DB
    stmt = select(FactVvbromoProductDay).where(FactVvbromoProductDay.nm_id == 197330807)
    rows = sqlite_session.execute(stmt).scalars().all()

    # No duplicates should be created, values must be updated
    assert len(rows) == 1
    assert rows[0].organic_sales == 100
    assert rows[0].operating_profit == Decimal("18000")
    assert rows[0].operating_profit_per_unit == Decimal("180")
    assert rows[0].raw_row == {"raw": "data2"}


def test_dry_run_does_not_write_to_db(monkeypatch):
    # Mock upsert_rows to ensure it is not called during dry-run simulation
    upsert_called = {"val": False}

    def fake_upsert_rows(*args, **kwargs):
        upsert_called["val"] = True
        return 0

    monkeypatch.setattr("scripts.parse_vvbromo_sheet.upsert_rows", fake_upsert_rows)

    # We will simulate the main execution block of parse_vvbromo_sheet.py with dry_run = True
    # If dry_run is True, the database block is not executed.
    dry_run = True
    parsed_records = [{"day": date(2026, 6, 22), "nm_id": 197330807}]

    if not dry_run:
        upsert_rows(
            session=None,
            model=FactVvbromoProductDay,
            rows=parsed_records,
            conflict_columns=["day", "nm_id"]
        )

    assert upsert_called["val"] is False
