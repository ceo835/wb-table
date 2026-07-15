from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from src.clients.google_drive_client import GOOGLE_FOLDER_MIME_TYPE, GOOGLE_SHEETS_MIME_TYPE
from src.services.google_drive_daily_sync import (
    SOURCE_IVAN_STOCK,
    SOURCE_VVBROMO,
    STATUS_FAILED_DOWNLOAD,
    STATUS_PROCESSED,
    STATUS_SKIPPED_ALREADY_PROCESSED,
    sync_ivan_stock_from_google_drive,
    sync_vvbromo_from_google_drive,
)
from src.services.wb_supplies.file_reader import ParsedWorkbook, ParsedWorksheet


class FakeDriveClient:
    def __init__(self, tree: dict[str, list[dict]]):
        self.tree = tree

    def list_folder_children(self, folder_id: str, *, mime_type: str | None = None):
        return list(self.tree.get(folder_id, []))


def _make_workbook(file_item: dict, sheet_name: str, rows: list[list[object]]) -> ParsedWorkbook:
    return ParsedWorkbook(
        source_file_id=str(file_item["id"]),
        source_file_name=str(file_item["name"]),
        source_mime_type=file_item["mimeType"],
        effective_file_id=str(file_item["id"]),
        effective_file_name=str(file_item["name"]),
        effective_mime_type=file_item["mimeType"],
        worksheets=[
            ParsedWorksheet(
                sheet_name=sheet_name,
                rows=rows,
                raw_rows_count=len(rows),
            )
        ],
        warnings=[],
    )


@pytest.fixture(autouse=True)
def _patch_source_config(monkeypatch):
    from src.config.settings import settings as app_settings

    monkeypatch.setattr(app_settings, "vvbromo_google_drive_folder_id", "folder-vvbromo")
    monkeypatch.setattr(app_settings, "ivan_stock_google_drive_folder_id", "folder-ivan")


def test_sync_vvbromo_processes_new_file(monkeypatch) -> None:
    file_item = {
        "id": "file-1",
        "name": "vvbromo.xlsx",
        "mimeType": GOOGLE_SHEETS_MIME_TYPE,
        "modifiedTime": "2026-07-15T09:00:00Z",
        "size": "100",
    }
    workbook = _make_workbook(
        file_item,
        "Лист1",
        [["01.07"], ["123", "SKU-1", "10", "20", "2"]],
    )
    saved_states: list[dict] = []

    monkeypatch.setattr("src.services.google_drive_daily_sync._load_existing_index", lambda source_type: {})
    monkeypatch.setattr("src.services.google_drive_daily_sync._save_source_file_state", lambda state: saved_states.append(dict(state)))
    monkeypatch.setattr("src.services.google_drive_daily_sync._write_vvbromo_rows", lambda parsed_payload, write_db: len(parsed_payload["records"]))
    monkeypatch.setattr("src.services.google_drive_daily_sync.read_supply_file", lambda *args, **kwargs: workbook)

    summary = sync_vvbromo_from_google_drive(
        run_date=date(2026, 7, 15),
        write_db=True,
        drive_client=FakeDriveClient({"folder-vvbromo": [file_item]}),
        sheets_client=object(),
    )

    assert summary["source"] == SOURCE_VVBROMO
    assert summary["files_found"] == 1
    assert summary["new_files"] == 1
    assert summary["processed_files"] == 1
    assert summary["failed_files"] == 0
    assert summary["rows_loaded"] == 1
    assert summary["status"] == "OK"
    assert saved_states[-1]["processing_status"] == STATUS_PROCESSED


def test_sync_vvbromo_skips_unchanged_processed_file(monkeypatch) -> None:
    file_item = {
        "id": "file-1",
        "name": "vvbromo.xlsx",
        "mimeType": GOOGLE_SHEETS_MIME_TYPE,
        "modifiedTime": "2026-07-15T09:00:00Z",
        "size": "100",
    }
    existing = SimpleNamespace(
        processing_status=STATUS_PROCESSED,
        google_modified_time=datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
        file_size=100,
        content_hash="same-hash",
        rows_loaded=7,
    )

    monkeypatch.setattr("src.services.google_drive_daily_sync._load_existing_index", lambda source_type: {"file-1": existing})
    monkeypatch.setattr("src.services.google_drive_daily_sync.read_supply_file", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not read unchanged file")))

    summary = sync_vvbromo_from_google_drive(
        run_date=date(2026, 7, 15),
        write_db=False,
        drive_client=FakeDriveClient({"folder-vvbromo": [file_item]}),
        sheets_client=object(),
    )

    assert summary["already_processed"] == 1
    assert summary["skipped_files"] == 1
    assert summary["processed_files"] == 0
    assert summary["status"] == "NO_NEW_FILES"
    assert summary["file_results"][0]["status"] == STATUS_SKIPPED_ALREADY_PROCESSED


def test_sync_vvbromo_reprocesses_changed_file(monkeypatch) -> None:
    file_item = {
        "id": "file-1",
        "name": "vvbromo.xlsx",
        "mimeType": GOOGLE_SHEETS_MIME_TYPE,
        "modifiedTime": "2026-07-15T10:00:00Z",
        "size": "120",
    }
    existing = SimpleNamespace(
        processing_status=STATUS_PROCESSED,
        google_modified_time=datetime(2026, 7, 14, 9, 0, tzinfo=UTC),
        file_size=100,
        content_hash="old-hash",
        rows_loaded=1,
    )
    workbook = _make_workbook(
        file_item,
        "Лист1",
        [["01.07"], ["123", "SKU-1", "10", "20", "2"], ["02.07"], ["123", "SKU-1", "5", "6", "1"]],
    )

    monkeypatch.setattr("src.services.google_drive_daily_sync._load_existing_index", lambda source_type: {"file-1": existing})
    monkeypatch.setattr("src.services.google_drive_daily_sync._write_vvbromo_rows", lambda parsed_payload, write_db: len(parsed_payload["records"]))
    monkeypatch.setattr("src.services.google_drive_daily_sync.read_supply_file", lambda *args, **kwargs: workbook)

    summary = sync_vvbromo_from_google_drive(
        run_date=date(2026, 7, 15),
        write_db=False,
        drive_client=FakeDriveClient({"folder-vvbromo": [file_item]}),
        sheets_client=object(),
    )

    assert summary["new_files"] == 1
    assert summary["processed_files"] == 1
    assert summary["rows_loaded"] == 2
    assert summary["status"] == "OK"


def test_sync_vvbromo_continues_when_one_file_fails(monkeypatch) -> None:
    good_file = {
        "id": "file-good",
        "name": "vvbromo-good.xlsx",
        "mimeType": GOOGLE_SHEETS_MIME_TYPE,
        "modifiedTime": "2026-07-15T09:00:00Z",
        "size": "100",
    }
    bad_file = {
        "id": "file-bad",
        "name": "vvbromo-bad.xlsx",
        "mimeType": GOOGLE_SHEETS_MIME_TYPE,
        "modifiedTime": "2026-07-15T09:05:00Z",
        "size": "101",
    }
    workbook = _make_workbook(good_file, "Лист1", [["01.07"], ["123", "SKU-1", "10", "20", "2"]])

    def fake_read_supply_file(file_item, **kwargs):
        if file_item["id"] == "file-bad":
            raise RuntimeError("download boom")
        return workbook

    monkeypatch.setattr("src.services.google_drive_daily_sync._load_existing_index", lambda source_type: {})
    monkeypatch.setattr("src.services.google_drive_daily_sync._write_vvbromo_rows", lambda parsed_payload, write_db: len(parsed_payload["records"]))
    monkeypatch.setattr("src.services.google_drive_daily_sync.read_supply_file", fake_read_supply_file)

    summary = sync_vvbromo_from_google_drive(
        run_date=date(2026, 7, 15),
        write_db=False,
        drive_client=FakeDriveClient({"folder-vvbromo": [good_file, bad_file]}),
        sheets_client=object(),
    )

    assert summary["processed_files"] == 1
    assert summary["failed_files"] == 1
    assert summary["success"] is False
    assert {row["status"] for row in summary["file_results"]} >= {STATUS_PROCESSED, STATUS_FAILED_DOWNLOAD}


def test_sync_ivan_stock_reads_nested_folders(monkeypatch) -> None:
    folder_item = {
        "id": "nested-folder",
        "name": "2026-07-15",
        "mimeType": GOOGLE_FOLDER_MIME_TYPE,
    }
    file_item = {
        "id": "ivan-file-1",
        "name": "ivan-stock.xlsx",
        "mimeType": GOOGLE_SHEETS_MIME_TYPE,
        "modifiedTime": "2026-07-15T22:00:00Z",
        "size": "50",
    }
    workbook = _make_workbook(
        file_item,
        "Остатки",
        [
            ["04.07.2026"],
            ["Номенклатура, Штрихкод", "Номенклатура.Артикул", "Количество"],
            ["Товар Размер: 42 Цвет: Черный, 1234567890123", "1001", "7"],
        ],
    )

    monkeypatch.setattr("src.services.google_drive_daily_sync._load_existing_index", lambda source_type: {})
    monkeypatch.setattr("src.services.google_drive_daily_sync._write_ivan_stock_rows", lambda parsed_payload, write_db: len(parsed_payload["records"]))
    monkeypatch.setattr("src.services.google_drive_daily_sync.read_supply_file", lambda *args, **kwargs: workbook)

    summary = sync_ivan_stock_from_google_drive(
        run_date=date(2026, 7, 15),
        write_db=False,
        drive_client=FakeDriveClient({"folder-ivan": [folder_item], "nested-folder": [file_item]}),
        sheets_client=object(),
    )

    assert summary["source"] == SOURCE_IVAN_STOCK
    assert summary["files_found"] == 1
    assert summary["processed_files"] == 1
    assert summary["rows_loaded"] == 1
    assert summary["status"] == "OK"


def test_sync_returns_no_new_files_when_folder_is_empty(monkeypatch) -> None:
    monkeypatch.setattr("src.services.google_drive_daily_sync._load_existing_index", lambda source_type: {})

    summary = sync_vvbromo_from_google_drive(
        run_date=date(2026, 7, 15),
        write_db=False,
        drive_client=FakeDriveClient({"folder-vvbromo": []}),
        sheets_client=object(),
    )

    assert summary["files_found"] == 0
    assert summary["processed_files"] == 0
    assert summary["failed_files"] == 0
    assert summary["status"] == "NO_NEW_FILES"
