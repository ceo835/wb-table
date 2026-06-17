from __future__ import annotations

from datetime import UTC, datetime

from src.db.advert_metadata_loader import (
    FACT_ADVERT_METADATA_CONFLICT_COLUMNS,
    normalize_advert_metadata_rows,
    prepare_fact_advert_metadata_upsert_rows,
)


def test_fact_advert_metadata_conflict_columns_match_natural_key() -> None:
    assert FACT_ADVERT_METADATA_CONFLICT_COLUMNS == ("advert_id",)


def test_normalize_advert_metadata_rows_extracts_core_fields() -> None:
    loaded_at = datetime(2026, 6, 17, 8, 30, tzinfo=UTC)

    rows = normalize_advert_metadata_rows(
        [
            {
                "advertId": 33285505,
                "name": "WB Campaign",
                "status": 9,
                "paymentType": "cpm",
                "nmSettings": {"nmIds": [197330807, 37320545]},
                "placements": ["catalog", "search"],
            }
        ],
        loaded_at=loaded_at,
    )

    assert rows == [
        {
            "advert_id": 33285505,
            "campaign_name": "WB Campaign",
            "status": "9",
            "payment_type": "cpm",
            "primary_nm_id": 197330807,
            "linked_nm_ids_json": [197330807, 37320545],
            "placements_json": ["catalog", "search"],
            "raw_payload_json": {
                "advertId": 33285505,
                "name": "WB Campaign",
                "status": 9,
                "paymentType": "cpm",
                "nmSettings": {"nmIds": [197330807, 37320545]},
                "placements": ["catalog", "search"],
            },
            "source_status": "REAL_API",
            "loaded_at": loaded_at,
        }
    ]


def test_prepare_fact_advert_metadata_upsert_rows_deduplicates_by_advert_id() -> None:
    loaded_at = datetime(2026, 6, 17, 8, 30, tzinfo=UTC)
    rows = prepare_fact_advert_metadata_upsert_rows(
        [
            {
                "advert_id": 33285505,
                "campaign_name": "First",
                "status": "8",
                "payment_type": "cpc",
                "primary_nm_id": 197330807,
                "linked_nm_ids_json": [197330807],
                "placements_json": ["catalog"],
                "raw_payload_json": {"advertId": 33285505, "name": "First"},
                "source_status": "REAL_API",
                "loaded_at": loaded_at,
            },
            {
                "advert_id": 33285505,
                "campaign_name": "Second",
                "status": "9",
                "payment_type": "cpm",
                "primary_nm_id": 37320545,
                "linked_nm_ids_json": [37320545, 197330807],
                "placements_json": ["search"],
                "raw_payload_json": {"advertId": 33285505, "name": "Second"},
                "source_status": "REAL_API",
                "loaded_at": loaded_at,
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0]["campaign_name"] == "Second"
    assert rows[0]["status"] == "9"
    assert rows[0]["primary_nm_id"] == 37320545
    assert rows[0]["linked_nm_ids_json"] == [37320545, 197330807]
