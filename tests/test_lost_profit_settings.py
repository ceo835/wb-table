from __future__ import annotations

from decimal import Decimal

from src.db.lost_profit_settings import (
    INITIAL_MARKET_AREAS,
    INITIAL_WAREHOUSE_AREAS,
    MARKET_AREA_CONFLICT_COLUMNS,
    WAREHOUSE_AREA_CONFLICT_COLUMNS,
    prepare_market_area_upsert_rows,
    prepare_warehouse_area_upsert_rows,
)


def test_market_area_conflict_columns_match_natural_key() -> None:
    assert MARKET_AREA_CONFLICT_COLUMNS == ("market_area_code",)


def test_warehouse_area_conflict_columns_match_natural_key() -> None:
    assert WAREHOUSE_AREA_CONFLICT_COLUMNS == ("warehouse_name",)


def test_prepare_market_area_upsert_rows_deduplicates_and_keeps_numeric_share() -> None:
    rows = prepare_market_area_upsert_rows(
        [
            {
                "market_area_code": "vladimir_area",
                "market_area_name": "Владимир / городской округ",
                "population_people": 344242,
                "population_share_pct": "0.236",
                "source": "seed_v1",
                "approval_status": "pending_ivan_review",
                "comment": "first",
            },
            {
                "market_area_code": "vladimir_area",
                "market_area_name": "Владимир / городской округ",
                "population_people": 344242,
                "population_share_pct": 0.236,
                "source": "seed_v2",
                "approval_status": "pending_ivan_review",
                "comment": "second",
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0]["source"] == "seed_v2"
    assert rows[0]["comment"] == "second"
    assert rows[0]["population_share_pct"] == Decimal("0.236")


def test_prepare_warehouse_area_upsert_rows_deduplicates_by_warehouse_name() -> None:
    rows = prepare_warehouse_area_upsert_rows(
        [
            {
                "warehouse_name": "Тула",
                "market_area_code": "tula_novomoskovsk_agglomeration",
                "approval_status": "pending_ivan_review",
                "comment": "first",
            },
            {
                "warehouse_name": "Тула",
                "market_area_code": "tula_novomoskovsk_agglomeration",
                "approval_status": "pending_ivan_review",
                "comment": "second",
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0]["comment"] == "second"


def test_initial_seed_contains_all_8_warehouses_and_valid_market_area_links() -> None:
    market_codes = {row["market_area_code"] for row in INITIAL_MARKET_AREAS}
    warehouse_names = {row["warehouse_name"] for row in INITIAL_WAREHOUSE_AREAS}

    assert len(INITIAL_MARKET_AREAS) == 8
    assert len(INITIAL_WAREHOUSE_AREAS) == 8
    assert len(warehouse_names) == 8
    assert {row["market_area_code"] for row in INITIAL_WAREHOUSE_AREAS}.issubset(market_codes)


def test_initial_market_area_population_share_pct_is_numeric() -> None:
    rows = prepare_market_area_upsert_rows(INITIAL_MARKET_AREAS)

    assert all(isinstance(row["population_share_pct"], Decimal) for row in rows)
