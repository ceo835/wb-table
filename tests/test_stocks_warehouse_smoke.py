from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from scripts.stocks_warehouse_smoke import (
    MAIN_WAREHOUSE_NAMES,
    build_request_payload,
    build_smoke_summary,
    extract_office_rows,
    load_tracked_targets,
)


def test_load_tracked_targets_returns_unique_nm_ids_and_counts(tmp_path: Path) -> None:
    path = tmp_path / "tracked_products.csv"
    pd.DataFrame(
        [
            {
                "nm_id": 197330807,
                "item_label": "чёрные 5 шт",
                "is_tracked": True,
                "lifecycle_status": "active",
                "source": "ivan_2026-06-15_v2",
            },
            {
                "nm_id": 197330807,
                "item_label": "чёрные 5 шт дубль",
                "is_tracked": True,
                "lifecycle_status": "active",
                "source": "ivan_2026-06-15_v2",
            },
            {
                "nm_id": 37320545,
                "item_label": "классика ЧББ",
                "is_tracked": True,
                "lifecycle_status": "sellout",
                "source": "ivan_2026-06-15_v2",
            },
        ]
    ).to_csv(path, index=False)

    targets = load_tracked_targets(path)

    assert targets["nm_ids"] == [37320545, 197330807]
    assert targets["tracked_total"] == 2
    assert targets["tracked_active_count"] == 1
    assert targets["tracked_sellout_count"] == 1


def test_build_request_payload_can_include_nmids() -> None:
    payload = build_request_payload(
        snapshot_date=date(2026, 6, 15),
        nm_ids=[1, 2, 3],
        limit=100,
        offset=0,
        include_nm_ids=True,
    )

    assert payload["currentPeriod"] == {"start": "2026-06-15", "end": "2026-06-15"}
    assert payload["limit"] == 100
    assert payload["offset"] == 0
    assert payload["nmIDs"] == [1, 2, 3]


def test_extract_office_rows_flattens_nested_offices_payload() -> None:
    payload = {
        "data": {
            "items": [
                {
                    "nmID": 197330807,
                    "vendorCode": "BlackWOM5",
                    "name": "Трусы",
                    "brandName": "PALEY",
                    "subjectName": "Трусы",
                    "offices": [
                        {
                            "officeID": 10,
                            "officeName": "Тула",
                            "quantity": 0,
                        },
                        {
                            "officeID": 11,
                            "officeName": "Казань",
                            "quantity": 12,
                        },
                    ],
                }
            ]
        }
    }

    rows = extract_office_rows(payload, snapshot_date=date(2026, 6, 15))

    assert rows == [
        {
            "snapshot_date": "2026-06-15",
            "nm_id": 197330807,
            "supplier_article": "BlackWOM5",
            "title": "Трусы",
            "brand": "PALEY",
            "subject": "Трусы",
            "warehouse_id": 10,
            "warehouse_name": "Тула",
            "office_name": "Тула",
            "warehouse_type": None,
            "stock_qty": 0,
        },
        {
            "snapshot_date": "2026-06-15",
            "nm_id": 197330807,
            "supplier_article": "BlackWOM5",
            "title": "Трусы",
            "brand": "PALEY",
            "subject": "Трусы",
            "warehouse_id": 11,
            "warehouse_name": "Казань",
            "office_name": "Казань",
            "warehouse_type": None,
            "stock_qty": 12,
        },
    ]


def test_extract_office_rows_supports_region_office_aggregate_payload() -> None:
    payload = {
        "data": {
            "regions": [
                {
                    "regionName": "Центральный",
                    "offices": [
                        {
                            "officeID": 301981,
                            "officeName": "Владимир WB",
                            "metrics": {"stockCount": 19031},
                        }
                    ],
                }
            ]
        }
    }

    rows = extract_office_rows(payload, snapshot_date=date(2026, 6, 15))

    assert rows == [
        {
            "snapshot_date": "2026-06-15",
            "nm_id": None,
            "supplier_article": None,
            "title": None,
            "brand": None,
            "subject": None,
            "warehouse_id": 301981,
            "warehouse_name": "Владимир WB",
            "office_name": "Владимир WB",
            "warehouse_type": "Центральный",
            "stock_qty": 19031,
        }
    ]


def test_build_smoke_summary_counts_main_warehouses_and_sample_rows() -> None:
    normalized = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 197330807,
                "supplier_article": "BlackWOM5",
                "warehouse_id": 10,
                "warehouse_name": "Тула",
                "office_name": "Тула",
                "warehouse_type": None,
                "stock_qty": 0,
            },
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 197330807,
                "supplier_article": "BlackWOM5",
                "warehouse_id": 11,
                "warehouse_name": "Казань",
                "office_name": "Казань",
                "warehouse_type": None,
                "stock_qty": 12,
            },
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 37320545,
                "supplier_article": "ЧББ",
                "warehouse_id": 12,
                "warehouse_name": "Владимир WB",
                "office_name": "Владимир WB",
                "warehouse_type": None,
                "stock_qty": 5,
            },
        ]
    )

    summary = build_smoke_summary(
        snapshot_date=date(2026, 6, 15),
        tracked_total=59,
        tracked_nm_ids=[197330807, 37320545, 111],
        request_variant="with_nmids",
        http_status="200",
        normalized_df=normalized,
        request_attempts=[],
        raw_payload={"data": {"items": []}},
    )

    assert summary["endpoint_works"] is True
    assert summary["tracked_nm_ids_sent"] == 3
    assert summary["returned_nm_ids_count"] == 2
    assert summary["returned_warehouses_count"] == 3
    assert summary["can_build_warehouse_table"] is True
    assert summary["found_main_warehouses"] == ["Владимир WB", "Казань", "Тула"]
    assert "Краснодар" in summary["missing_main_warehouses"]
    assert summary["normalized_sample"][0]["warehouse_name"] in MAIN_WAREHOUSE_NAMES
