from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from src.db.ad_cost_loader import (
    FACT_AD_COST_DAY_CONFLICT_COLUMNS,
    FACT_AD_COST_EVENT_CONFLICT_COLUMNS,
    build_fact_ad_cost_day_db_row,
    build_fact_ad_cost_event_db_row,
    prepare_fact_ad_cost_day_upsert_rows,
    prepare_fact_ad_cost_event_upsert_rows,
)


def test_fact_ad_cost_event_conflict_columns_match_natural_key():
    assert FACT_AD_COST_EVENT_CONFLICT_COLUMNS == ("date", "advert_id", "writeoff_datetime", "document_number", "spend")


def test_fact_ad_cost_day_conflict_columns_match_natural_key():
    assert FACT_AD_COST_DAY_CONFLICT_COLUMNS == ("date", "advert_id", "nm_id")


def test_build_fact_ad_cost_event_db_row_preserves_datetime_and_sum():
    row = build_fact_ad_cost_event_db_row(
        {
            "date": "2026-06-01",
            "advertId": 123,
            "campaign_name": "Поиск Арт. 335760311",
            "section_raw": "9",
            "writeoff_datetime": "2026-06-01T23:59:00",
            "writeoff_source": "writeoff",
            "spend": 123.45,
            "document_number": "DOC-1",
            "nm_id_from_section": "",
            "nm_id_from_campaign_name": 335760311,
            "nm_id": 335760311,
            "nm_id_parse_status": "FROM_CAMPAIGN_NAME",
            "campaign_type": "Поиск",
            "currency": "RUB",
            "data_status": "REAL_API",
            "source_status": "REAL_API",
            "loaded_at": "2026-06-04T10:00:00+05:00",
        }
    )
    assert row["date"] == date(2026, 6, 1)
    assert row["writeoff_datetime"] == datetime.fromisoformat("2026-06-01T23:59:00")
    assert row["spend"] == Decimal("123.45")
    assert row["nm_id"] == 335760311


def test_prepare_fact_ad_cost_event_upsert_rows_deduplicates_by_natural_key():
    rows = prepare_fact_ad_cost_event_upsert_rows(
        [
            {
                "date": "2026-06-01",
                "advertId": 123,
                "writeoff_datetime": "2026-06-01T23:59:00",
                "document_number": "DOC-1",
                "spend": 10,
                "data_status": "REAL_API",
                "source_status": "REAL_API",
                "loaded_at": "2026-06-04T10:00:00+05:00",
            },
            {
                "date": "2026-06-01",
                "advertId": 123,
                "writeoff_datetime": "2026-06-01T23:59:00",
                "document_number": "DOC-1",
                "spend": 10,
                "data_status": "REAL_API",
                "source_status": "REAL_API",
                "loaded_at": "2026-06-04T10:00:00+05:00",
            },
        ]
    )
    assert len(rows) == 1


def test_build_fact_ad_cost_day_db_row_preserves_aggregate_fields():
    row = build_fact_ad_cost_day_db_row(
        {
            "date": "2026-06-01",
            "advertId": 123,
            "campaign_name": "Поиск Арт. 335760311",
            "nm_id": 335760311,
            "total_spend": 321.5,
            "events_count": 3,
            "allocation_status": "ALLOCATED",
            "data_status": "REAL_API",
            "source_status": "REAL_API",
            "loaded_at": "2026-06-04T10:00:00+05:00",
        }
    )
    assert row["date"] == date(2026, 6, 1)
    assert row["total_spend"] == Decimal("321.5")
    assert row["events_count"] == 3
    assert row["allocation_status"] == "ALLOCATED"


def test_prepare_fact_ad_cost_day_upsert_rows_deduplicates_by_natural_key():
    rows = prepare_fact_ad_cost_day_upsert_rows(
        [
            {
                "date": "2026-06-01",
                "advertId": 123,
                "nm_id": 335760311,
                "total_spend": 100,
                "events_count": 1,
                "allocation_status": "ALLOCATED",
                "data_status": "REAL_API",
                "source_status": "REAL_API",
                "loaded_at": "2026-06-04T10:00:00+05:00",
            },
            {
                "date": "2026-06-01",
                "advertId": 123,
                "nm_id": 335760311,
                "total_spend": 200,
                "events_count": 2,
                "allocation_status": "ALLOCATED",
                "data_status": "REAL_API",
                "source_status": "REAL_API",
                "loaded_at": "2026-06-04T10:00:00+05:00",
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["total_spend"] == Decimal("200")
