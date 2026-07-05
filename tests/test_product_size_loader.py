from __future__ import annotations

from src.db.product_size_loader import normalize_wb_content_size_rows


def test_normalize_wb_content_size_rows_extracts_nm_chrt_barcode_and_sizes() -> None:
    cards = [
        {
            "nmID": 197330807,
            "vendorCode": "BlackWOM5",
            "title": "Трусы комплект",
            "sizes": [
                {
                    "chrtID": 101,
                    "techSize": "42-44",
                    "wbSize": "M",
                    "skus": ["2037074255720"],
                },
                {
                    "chrtID": 102,
                    "techSize": "46-48",
                    "wbSize": "L",
                    "skus": ["2037074255721"],
                },
            ],
        }
    ]

    rows = normalize_wb_content_size_rows(cards)

    assert rows == [
        {
            "nm_id": 197330807,
            "chrt_id": 101,
            "barcode": "2037074255720",
            "size_name": "M",
            "tech_size": "42-44",
            "source_status": "WB_CONTENT_API",
        },
        {
            "nm_id": 197330807,
            "chrt_id": 102,
            "barcode": "2037074255721",
            "size_name": "L",
            "tech_size": "46-48",
            "source_status": "WB_CONTENT_API",
        },
    ]


def test_normalize_wb_content_size_rows_keeps_row_without_barcode_when_size_exists() -> None:
    cards = [
        {
            "nmID": 91470767,
            "sizes": [
                {
                    "chrtID": 501,
                    "techSize": "86-92",
                    "wbSize": "92",
                    "skus": [],
                }
            ],
        }
    ]

    rows = normalize_wb_content_size_rows(cards)

    assert rows == [
        {
            "nm_id": 91470767,
            "chrt_id": 501,
            "barcode": None,
            "size_name": "92",
            "tech_size": "86-92",
            "source_status": "WB_CONTENT_API",
        }
    ]
