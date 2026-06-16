from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from src.db.stock_warehouse_loader import (
    WarehouseStockPageResult,
    aggregate_stock_warehouse_rows,
    fetch_wb_warehouse_stock_pages,
    load_stock_warehouse_snapshot,
    normalize_wb_warehouse_stock_rows,
    prepare_fact_stock_warehouse_snapshot_upsert_rows,
)


def test_normalize_wb_warehouse_stock_rows_maps_fields() -> None:
    rows = normalize_wb_warehouse_stock_rows(
        [
            {
                "nmId": 197330807,
                "chrtId": 123,
                "warehouseId": 206348,
                "warehouseName": "Тула",
                "regionName": "Центральный",
                "quantity": 7,
                "inWayToClient": 2,
                "inWayFromClient": 1,
            }
        ],
        date(2026, 6, 15),
    )

    assert rows == [
        {
            "snapshot_date": "2026-06-15",
            "nm_id": 197330807,
            "chrt_id": 123,
            "warehouse_id": 206348,
            "warehouse_name": "Тула",
            "region_name": "Центральный",
            "stock_qty": 7,
            "in_way_to_client": 2,
            "in_way_from_client": 1,
            "source": "WB_ANALYTICS_WB_WAREHOUSES",
        }
    ]


def test_normalize_wb_warehouse_stock_rows_preserves_zero_values() -> None:
    rows = normalize_wb_warehouse_stock_rows(
        [
            {
                "nmId": 197330807,
                "chrtId": 123,
                "warehouseId": 206348,
                "warehouseName": "Тула",
                "regionName": "Центральный",
                "quantity": 0,
                "inWayToClient": 0,
                "inWayFromClient": 0,
            }
        ],
        date(2026, 6, 15),
    )

    assert rows[0]["stock_qty"] == 0
    assert rows[0]["in_way_to_client"] == 0
    assert rows[0]["in_way_from_client"] == 0


def test_prepare_upsert_rows_uses_minus_one_for_missing_chrt_id() -> None:
    rows = prepare_fact_stock_warehouse_snapshot_upsert_rows(
        [
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 197330807,
                "chrt_id": None,
                "warehouse_id": 206348,
                "warehouse_name": "Тула",
                "region_name": "Центральный",
                "stock_qty": 7,
                "in_way_to_client": 2,
                "in_way_from_client": 1,
                "source": "WB_ANALYTICS_WB_WAREHOUSES",
            }
        ]
    )

    assert rows[0]["chrt_id"] == -1


def test_prepare_upsert_rows_deduplicates_by_snapshot_nm_chrt_warehouse() -> None:
    rows = prepare_fact_stock_warehouse_snapshot_upsert_rows(
        [
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 197330807,
                "chrt_id": 123,
                "warehouse_id": 206348,
                "warehouse_name": "Тула",
                "region_name": "Центральный",
                "stock_qty": 7,
                "in_way_to_client": 2,
                "in_way_from_client": 1,
                "source": "A",
            },
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 197330807,
                "chrt_id": 123,
                "warehouse_id": 206348,
                "warehouse_name": "Тула",
                "region_name": "Центральный",
                "stock_qty": 9,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
                "source": "B",
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0]["stock_qty"] == 9
    assert rows[0]["source"] == "B"


def test_aggregate_stock_warehouse_rows_sums_by_nm_and_warehouse() -> None:
    aggregate_rows = aggregate_stock_warehouse_rows(
        [
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 197330807,
                "chrt_id": 101,
                "warehouse_id": 206348,
                "warehouse_name": "Тула",
                "region_name": "Центральный",
                "stock_qty": 2,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
                "source": "X",
            },
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 197330807,
                "chrt_id": 102,
                "warehouse_id": 206348,
                "warehouse_name": "Тула",
                "region_name": "Центральный",
                "stock_qty": 5,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
                "source": "X",
            },
        ]
    )

    assert aggregate_rows == [
        {
            "snapshot_date": "2026-06-15",
            "nm_id": 197330807,
            "warehouse_id": 206348,
            "warehouse_name": "Тула",
            "region_name": "Центральный",
            "stock_qty_total": 7,
        }
    ]


def test_fetch_wb_warehouse_stock_pages_handles_empty_response() -> None:
    def fake_request(payload):
        return WarehouseStockPageResult(http_status="200", payload={"data": {"items": []}}, error="", request_payload=payload)

    rows, meta = fetch_wb_warehouse_stock_pages(
        snapshot_date=date(2026, 6, 15),
        requester=fake_request,
        limit=1000,
    )

    assert rows == []
    assert meta["pages_loaded"] == 1
    assert meta["rows_raw"] == 0


def test_fetch_wb_warehouse_stock_pages_uses_pagination() -> None:
    calls: list[int] = []

    def fake_request(payload):
        offset = payload["offset"]
        calls.append(offset)
        if offset == 0:
            items = [{"nmId": 1, "chrtId": 10, "warehouseId": 100, "warehouseName": "Тула", "regionName": "Ц", "quantity": 1}]
        else:
            items = []
        return WarehouseStockPageResult(http_status="200", payload={"data": {"items": items}}, error="", request_payload=payload)

    rows, meta = fetch_wb_warehouse_stock_pages(
        snapshot_date=date(2026, 6, 15),
        requester=fake_request,
        limit=1,
    )

    assert calls == [0, 1]
    assert len(rows) == 1
    assert meta["pages_loaded"] == 2


def test_load_stock_warehouse_snapshot_filters_to_tracked_scope(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "src.db.stock_warehouse_loader.get_tracked_nm_ids",
        lambda _path: [197330807],
    )

    def fake_request(payload):
        return WarehouseStockPageResult(
            http_status="200",
            payload={
                "data": {
                    "items": [
                        {
                            "nmId": 197330807,
                            "chrtId": 101,
                            "warehouseId": 206348,
                            "warehouseName": "Тула",
                            "regionName": "Центральный",
                            "quantity": 3,
                            "inWayToClient": 0,
                            "inWayFromClient": 0,
                        },
                        {
                            "nmId": 37320545,
                            "chrtId": 201,
                            "warehouseId": 117986,
                            "warehouseName": "Казань",
                            "regionName": "Приволжский",
                            "quantity": 4,
                            "inWayToClient": 0,
                            "inWayFromClient": 0,
                        },
                    ]
                }
            },
            error="",
            request_payload=payload,
        )

    summary = load_stock_warehouse_snapshot(
        snapshot_date=date(2026, 6, 15),
        tracked_products=True,
        output_dir=tmp_path,
        write_db=False,
        requester=fake_request,
    )

    assert summary["tracked_total"] == 1
    assert summary["requested_nm_ids_count"] == 1
    assert summary["rows_raw"] == 2
    assert summary["rows_normalized"] == 1
    assert summary["unique_nm_ids"] == 1
    assert summary["can_build_snapshot_nm_warehouse"] is True


def test_load_stock_warehouse_snapshot_replaces_scope_and_removes_stale_rows(monkeypatch, tmp_path: Path) -> None:
    state: dict[str, Any] = {
        "rows": [
            {"snapshot_date": date(2026, 6, 15), "nm_id": 1, "chrt_id": 11, "warehouse_id": 101},
            {"snapshot_date": date(2026, 6, 15), "nm_id": 1, "chrt_id": 12, "warehouse_id": 102},
            {"snapshot_date": date(2026, 6, 15), "nm_id": 2, "chrt_id": 21, "warehouse_id": 201},
            {"snapshot_date": date(2026, 6, 15), "nm_id": 3, "chrt_id": 31, "warehouse_id": 301},
            {"snapshot_date": date(2026, 6, 14), "nm_id": 1, "chrt_id": 11, "warehouse_id": 101},
        ],
        "deleted": [],
        "upserted": [],
    }

    monkeypatch.setattr("src.db.stock_warehouse_loader.get_tracked_nm_ids", lambda _path: [1, 2])

    class FakeSession:
        pass

    class FakeSessionScope:
        def __enter__(self):
            return FakeSession()

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_delete(_session, snapshot_date, nm_ids):
        requested = {int(nm_id) for nm_id in nm_ids}
        before = len(state["rows"])
        state["rows"] = [
            row for row in state["rows"]
            if not (row["snapshot_date"] == snapshot_date and row["nm_id"] in requested)
        ]
        deleted = before - len(state["rows"])
        state["deleted"].append({"snapshot_date": snapshot_date, "nm_ids": sorted(requested), "deleted": deleted})
        return deleted

    def fake_upsert(_session, rows):
        prepared_rows = prepare_fact_stock_warehouse_snapshot_upsert_rows(rows)
        state["rows"].extend(
            {
                "snapshot_date": row["snapshot_date"],
                "nm_id": row["nm_id"],
                "chrt_id": row["chrt_id"],
                "warehouse_id": row["warehouse_id"],
            }
            for row in prepared_rows
        )
        state["upserted"].append(len(prepared_rows))
        return len(prepared_rows)

    def fake_count(_session, snapshot_date, nm_ids=None):
        requested = {int(nm_id) for nm_id in (nm_ids or [])}
        return sum(
            1
            for row in state["rows"]
            if row["snapshot_date"] == snapshot_date and (not requested or row["nm_id"] in requested)
        )

    monkeypatch.setattr("src.db.stock_warehouse_loader.session_scope", lambda: FakeSessionScope())
    monkeypatch.setattr("src.db.stock_warehouse_loader.delete_stock_warehouse_snapshot_scope", fake_delete)
    monkeypatch.setattr("src.db.stock_warehouse_loader.upsert_stock_warehouse_snapshot", fake_upsert)
    monkeypatch.setattr("src.db.stock_warehouse_loader.count_stock_warehouse_snapshot_rows", fake_count)

    def fake_request(payload):
        return WarehouseStockPageResult(
            http_status="200",
            payload={
                "data": {
                    "items": [
                        {
                            "nmId": 1,
                            "chrtId": 11,
                            "warehouseId": 101,
                            "warehouseName": "Тула",
                            "regionName": "Центральный",
                            "quantity": 5,
                            "inWayToClient": 0,
                            "inWayFromClient": 0,
                        }
                    ]
                }
            },
            error="",
            request_payload=payload,
        )

    summary = load_stock_warehouse_snapshot(
        snapshot_date=date(2026, 6, 15),
        tracked_products=True,
        output_dir=tmp_path,
        write_db=True,
        requester=fake_request,
    )

    assert summary["rows_normalized"] == 1
    assert summary["rows_upserted"] == 1
    assert summary["rows_in_db_for_snapshot"] == 1
    assert summary["rows_deleted_before_replace"] == 3
    assert summary["replace_scope_applied"] is True
    assert state["deleted"] == [{"snapshot_date": date(2026, 6, 15), "nm_ids": [1, 2], "deleted": 3}]
    assert sorted(state["rows"], key=lambda row: (row["snapshot_date"], row["nm_id"], row["chrt_id"], row["warehouse_id"])) == [
        {"snapshot_date": date(2026, 6, 14), "nm_id": 1, "chrt_id": 11, "warehouse_id": 101},
        {"snapshot_date": date(2026, 6, 15), "nm_id": 1, "chrt_id": 11, "warehouse_id": 101},
        {"snapshot_date": date(2026, 6, 15), "nm_id": 3, "chrt_id": 31, "warehouse_id": 301},
    ]


def test_load_stock_warehouse_snapshot_does_not_delete_or_upsert_on_api_error(monkeypatch, tmp_path: Path) -> None:
    state: dict[str, Any] = {
        "rows": [
            {"snapshot_date": date(2026, 6, 15), "nm_id": 1, "chrt_id": 11, "warehouse_id": 101},
            {"snapshot_date": date(2026, 6, 15), "nm_id": 2, "chrt_id": 21, "warehouse_id": 201},
        ],
        "delete_called": False,
        "upsert_called": False,
    }

    monkeypatch.setattr("src.db.stock_warehouse_loader.get_tracked_nm_ids", lambda _path: [1, 2])

    class FakeSession:
        pass

    class FakeSessionScope:
        def __enter__(self):
            return FakeSession()

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_delete(_session, snapshot_date, nm_ids):
        state["delete_called"] = True
        return 0

    def fake_upsert(_session, rows):
        state["upsert_called"] = True
        return len(rows)

    def fake_count(_session, snapshot_date, nm_ids=None):
        requested = {int(nm_id) for nm_id in (nm_ids or [])}
        return sum(
            1
            for row in state["rows"]
            if row["snapshot_date"] == snapshot_date and (not requested or row["nm_id"] in requested)
        )

    monkeypatch.setattr("src.db.stock_warehouse_loader.session_scope", lambda: FakeSessionScope())
    monkeypatch.setattr("src.db.stock_warehouse_loader.delete_stock_warehouse_snapshot_scope", fake_delete)
    monkeypatch.setattr("src.db.stock_warehouse_loader.upsert_stock_warehouse_snapshot", fake_upsert)
    monkeypatch.setattr("src.db.stock_warehouse_loader.count_stock_warehouse_snapshot_rows", fake_count)

    def fake_request(payload):
        return WarehouseStockPageResult(
            http_status="429",
            payload={"error": True},
            error="Too Many Requests",
            request_payload=payload,
        )

    summary = load_stock_warehouse_snapshot(
        snapshot_date=date(2026, 6, 15),
        tracked_products=True,
        output_dir=tmp_path,
        write_db=True,
        requester=fake_request,
    )

    assert summary["api_status"] == "429"
    assert summary["rows_normalized"] == 0
    assert summary["rows_upserted"] == 0
    assert summary["rows_deleted_before_replace"] == 0
    assert summary["replace_scope_applied"] is False
    assert summary["rows_in_db_for_snapshot"] == 2
    assert state["delete_called"] is False
    assert state["upsert_called"] is False
    assert state["rows"] == [
        {"snapshot_date": date(2026, 6, 15), "nm_id": 1, "chrt_id": 11, "warehouse_id": 101},
        {"snapshot_date": date(2026, 6, 15), "nm_id": 2, "chrt_id": 21, "warehouse_id": 201},
    ]
