from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.db.models import FactOzonPriceSnapshot
from src.db.ozon_price_snapshot_loader import (
    _to_decimal_or_none,
    prepare_fact_ozon_price_snapshot_upsert_rows,
    save_ozon_price_snapshots,
    collect_and_load_ozon_snapshots,
)
from src.ozon.models import OzonBrowserCardResult



def test_to_decimal_or_none() -> None:
    assert _to_decimal_or_none(None) is None
    assert _to_decimal_or_none("") is None
    assert _to_decimal_or_none("invalid") is None
    assert _to_decimal_or_none(123) == Decimal("123")
    assert _to_decimal_or_none("1471.50") == Decimal("1471.50")


def test_prepare_fact_ozon_price_snapshot_upsert_rows() -> None:
    snapshot_at = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
    items = [
        {
            "offer_id": "AvokaDo744-46",
            "product_id": 914491367,
            "sku": 1456494260,
            "name": "Product slipy 7-sht",
            "seller_price_api": 2711.0,
            "buyer_visible_price_web": 1471.0,
            "old_price_web": 1634.0,
            "other_bank_price_web": 1634.0,
            "stock": 32.0,
            "status_api": "active",
            "status_web": "ok",
            "error": None,
            "final_url": "https://www.ozon.ru/product/1456494260",
            "raw_json": {"some_key": "some_value"},
        }
    ]

    rows = prepare_fact_ozon_price_snapshot_upsert_rows(snapshot_at, items)

    assert len(rows) == 1
    row = rows[0]
    assert row["snapshot_at"] == snapshot_at
    assert row["snapshot_date"] == date(2026, 7, 9)
    assert row["offer_id"] == "AvokaDo744-46"
    assert row["product_id"] == 914491367
    assert row["sku"] == 1456494260
    assert row["name"] == "Product slipy 7-sht"
    assert row["seller_status"] == "active"
    assert row["stock_total"] == Decimal("32")
    assert row["seller_price_api"] == Decimal("2711")
    assert row["buyer_visible_price_web"] == Decimal("1471")
    assert row["old_price_web"] == Decimal("1634")
    assert row["status_api"] == "active"
    assert row["status_web"] == "ok"
    assert row["error"] is None
    assert row["final_url"] == "https://www.ozon.ru/product/1456494260"
    assert row["raw_json"] == {"some_key": "some_value"}


def test_save_ozon_price_snapshots() -> None:
    session = MagicMock()
    snapshot_at = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)
    items = [
        {
            "offer_id": "AvokaDo744-46",
            "seller_price_api": 2711.0,
            "buyer_visible_price_web": 1471.0,
        }
    ]

    with patch("src.db.ozon_price_snapshot_loader.upsert_rows") as mock_upsert:
        mock_upsert.return_value = 1
        rowcount = save_ozon_price_snapshots(session, snapshot_at, items)

        assert rowcount == 1
        mock_upsert.assert_called_once()
        args, kwargs = mock_upsert.call_args
        assert args[0] == session
        assert args[1] == FactOzonPriceSnapshot
        assert kwargs["conflict_columns"] == ["snapshot_at", "offer_id"]
        assert len(args[2]) == 1
        assert args[2][0]["offer_id"] == "AvokaDo744-46"


@patch("src.db.ozon_price_snapshot_loader.load_tracked_articles")
@patch("src.db.ozon_price_snapshot_loader.get_ozon_credentials")
@patch("src.db.ozon_price_snapshot_loader.fetch_api_details")
@patch("src.db.ozon_price_snapshot_loader.probe_ozon_browser_prices")
def test_collect_and_load_ozon_snapshots_dry_run(
    mock_probe,
    mock_fetch_api,
    mock_creds,
    mock_load_articles,
) -> None:
    mock_load_articles.return_value = {"AvokaDo744-46"}
    mock_creds.return_value = ("client-123", "api-key-456")

    # Mock API returns
    mock_fetch_api.return_value = {
        "AvokaDo744-46": {
            "offer_id": "AvokaDo744-46",
            "product_id": 914491367,
            "sku": 1456494260,
            "name": "Product slipy",
            "status_api": "active",
            "stock": 32.0,
            "seller_price_api": 2711.0,
        }
    }

    # Mock Playwright results
    mock_probe.return_value = [
        OzonBrowserCardResult(
            offer_id="AvokaDo744-46",
            product_id=914491367,
            status="ok",
            error=None,
            buyer_visible_price=1471.0,
            other_bank_price=1634.0,
            old_price=1634.0,
            final_url="https://www.ozon.ru/product/1456494260",
            price_candidates=(),
        )
    ]

    result = collect_and_load_ozon_snapshots(headless=True, dry_run=True)

    assert result["status"] == "success"
    assert result["dry_run"] is True
    assert result["saved_count"] == 0
    assert len(result["items"]) == 1

    item = result["items"][0]
    assert item["offer_id"] == "AvokaDo744-46"
    assert item["seller_price_api"] == 2711.0
    assert item["buyer_visible_price_web"] == 1471.0
    assert item["old_price_web"] == 1634.0
    assert item["status_api"] == "active"
    assert item["status_web"] == "ok"


@patch("src.db.ozon_price_snapshot_loader.load_tracked_articles")
@patch("src.db.ozon_price_snapshot_loader.get_ozon_credentials")
@patch("src.db.ozon_price_snapshot_loader.fetch_api_details")
@patch("src.db.ozon_price_snapshot_loader.probe_ozon_browser_prices")
def test_ozon_spp_calculations(
    mock_probe,
    mock_fetch_api,
    mock_creds,
    mock_load_articles,
) -> None:
    mock_load_articles.return_value = {"item-1", "item-2", "item-3", "item-4", "item-5", "item-6"}
    mock_creds.return_value = ("client-123", "api-key-456")

    mock_fetch_api.return_value = {
        "item-1": {"offer_id": "item-1", "product_id": 1, "sku": 10, "name": "Item 1", "status_api": "active", "stock": 1, "seller_price_api": 2000.0},
        "item-2": {"offer_id": "item-2", "product_id": 2, "sku": 20, "name": "Item 2", "status_api": "active", "stock": 1, "seller_price_api": 2000.0},
        "item-3": {"offer_id": "item-3", "product_id": 3, "sku": 30, "name": "Item 3", "status_api": "active", "stock": 1, "seller_price_api": 2000.0},
        "item-4": {"offer_id": "item-4", "product_id": 4, "sku": 40, "name": "Item 4", "status_api": "active", "stock": 1, "seller_price_api": 2000.0},
        "item-5": {"offer_id": "item-5", "product_id": 5, "sku": 50, "name": "Item 5", "status_api": "active", "stock": 1, "seller_price_api": 0.0},
        "item-6": {"offer_id": "item-6", "product_id": 6, "sku": 60, "name": "Item 6", "status_api": "active", "stock": 1, "seller_price_api": None},
    }

    mock_probe.return_value = [
        OzonBrowserCardResult(
            offer_id="item-1", product_id=1, status="ok", buyer_visible_price=1400.0, other_bank_price=1500.0, old_price=2200.0, price_candidates=()
        ),
        OzonBrowserCardResult(
            offer_id="item-2", product_id=2, status="ok", buyer_visible_price=1500.0, other_bank_price=None, old_price=2200.0, price_candidates=()
        ),
        OzonBrowserCardResult(
            offer_id="item-3", product_id=3, status="ok", buyer_visible_price=None, other_bank_price=None, old_price=2200.0, price_candidates=()
        ),
        OzonBrowserCardResult(
            offer_id="item-4", product_id=4, status="ok", buyer_visible_price=1.0, other_bank_price=None, old_price=2200.0, price_candidates=()
        ),
        OzonBrowserCardResult(
            offer_id="item-5", product_id=5, status="ok", buyer_visible_price=1500.0, other_bank_price=None, old_price=2200.0, price_candidates=()
        ),
        OzonBrowserCardResult(
            offer_id="item-6", product_id=6, status="ok", buyer_visible_price=1500.0, other_bank_price=None, old_price=2200.0, price_candidates=()
        ),
    ]

    result = collect_and_load_ozon_snapshots(headless=True, dry_run=True)
    assert result["status"] == "success"
    items_by_oid = {item["offer_id"]: item for item in result["items"]}

    # Case 1: other_bank_price_web=1500 -> buyer_regular_price_web=1500, spp_rub=500, spp_percent=25
    r1 = items_by_oid["item-1"]
    assert r1["buyer_regular_price_web"] == 1500.0
    assert r1["spp_rub"] == 500.0
    assert r1["spp_percent"] == 25.0

    # Case 2: other_bank_price_web is None, buyer_visible_price_web=1500 -> buyer_regular_price_web=1500
    r2 = items_by_oid["item-2"]
    assert r2["buyer_regular_price_web"] == 1500.0
    assert r2["spp_rub"] == 500.0
    assert r2["spp_percent"] == 25.0

    # Case 3: only old_price_web -> no regular price, no SPP
    r3 = items_by_oid["item-3"]
    assert r3["buyer_regular_price_web"] is None
    assert r3["spp_rub"] is None
    assert r3["spp_percent"] is None

    # Case 4: 1.0₽ -> no regular price, no SPP
    r4 = items_by_oid["item-4"]
    assert r4["buyer_regular_price_web"] is None
    assert r4["spp_rub"] is None
    assert r4["spp_percent"] is None

    # Case 5: seller_price_api is 0.0 -> no SPP calculation
    r5 = items_by_oid["item-5"]
    assert r5["buyer_regular_price_web"] == 1500.0
    assert r5["spp_rub"] is None
    assert r5["spp_percent"] is None

    # Case 6: seller_price_api is None -> no SPP calculation
    r6 = items_by_oid["item-6"]
    assert r6["buyer_regular_price_web"] == 1500.0
    assert r6["spp_rub"] is None
    assert r6["spp_percent"] is None

