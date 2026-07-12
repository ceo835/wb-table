from __future__ import annotations

from contextlib import contextmanager

from src.db import wb_supply_loader
from src.services.wb_supplies import sync_service


class FakeDriveClient:
    def __init__(self, files):
        self._files = files

    def list_folder_files(self, folder_id: str, include_all_supported: bool = True):
        assert folder_id == "folder-1"
        return list(self._files)

    def audit_folder_access(self, folder_id: str):
        assert folder_id == "folder-1"
        return {
            "folder_visible": True,
            "folder_metadata": {"id": folder_id, "name": "WB supplies"},
            "folder_error": None,
            "direct_children": list(self._files),
            "subfolders": [],
            "nested_children": {},
        }

    def resolve_shortcut_target(self, file_item):
        return file_item

    def download_file_bytes(self, file_id: str):
        raise AssertionError(f"download_file_bytes should not be used in this test: {file_id}")


class FakeSheetsClient:
    def __init__(self, titles_by_file, rows_by_file_sheet):
        self._titles_by_file = titles_by_file
        self._rows_by_file_sheet = rows_by_file_sheet

    def get_worksheet_titles(self, spreadsheet_id: str):
        value = self._titles_by_file[spreadsheet_id]
        if isinstance(value, Exception):
            raise value
        return value

    def read_range(self, spreadsheet_id: str, range_name: str):
        return self._rows_by_file_sheet[(spreadsheet_id, range_name)]


def test_replace_wb_supply_file_rows_uses_replace_by_file(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(wb_supply_loader, "delete_wb_supply_rows_for_file", lambda session, google_file_id: calls.append(("delete", google_file_id)) or 3)
    monkeypatch.setattr(
        wb_supply_loader,
        "upsert_rows",
        lambda session, model, rows, conflict_columns: calls.append(("upsert", len(rows), tuple(conflict_columns))) or len(rows),
    )

    result = wb_supply_loader.replace_wb_supply_file_rows(
        object(),
        "file-1",
        [{"google_file_id": "file-1", "sheet_name": "Лист1", "row_number": 2}],
    )

    assert result == {"rows_deleted": 3, "rows_upserted": 1}
    assert calls == [("delete", "file-1"), ("upsert", 1, ("google_file_id", "sheet_name", "row_number"))]


def test_sync_wb_supplies_continues_when_one_file_fails(caplog) -> None:
    drive_client = FakeDriveClient(
        [
            {
                "id": "file-1",
                "name": "Шушары",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "modifiedTime": "2026-07-11T10:00:00Z",
                "effectiveMimeType": "application/vnd.google-apps.spreadsheet",
            },
            {
                "id": "file-2",
                "name": "Казань",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "modifiedTime": "2026-07-11T11:00:00Z",
                "effectiveMimeType": "application/vnd.google-apps.spreadsheet",
            },
        ]
    )
    sheets_client = FakeSheetsClient(
        {
            "file-1": ["Лист1"],
            "file-2": RuntimeError("boom"),
        },
        {
            ("file-1", "'Лист1'!A:ZZ"): [
                ["Артикул ВБ", "Кол-во"],
                ["111", "7"],
            ],
        },
    )

    summary = sync_service.sync_wb_supplies_from_google_drive(
        folder_id="folder-1",
        write_db=False,
        drive_client=drive_client,
        sheets_client=sheets_client,
    )

    assert summary["files_total_in_folder"] == 2
    assert summary["supported_files_count"] == 2
    assert summary["unsupported_files_count"] == 0
    assert summary["files_found"] == 2
    assert summary["files_processed"] == 1
    assert summary["files_failed"] == 1
    assert summary["total_parsed_rows"] == 1
    assert summary["warehouses_detected"] == ["Шушары"]
    assert "PRIVATE_KEY" not in caplog.text


def test_sync_wb_supplies_writes_source_status_without_clearing_empty_parse(monkeypatch) -> None:
    drive_client = FakeDriveClient(
        [
            {
                "id": "file-1",
                "name": "Шушары",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "modifiedTime": "2026-07-11T10:00:00Z",
                "effectiveMimeType": "application/vnd.google-apps.spreadsheet",
            },
        ]
    )
    sheets_client = FakeSheetsClient(
        {"file-1": ["Лист1"]},
        {("file-1", "'Лист1'!A:ZZ"): [["что-то без заголовка"]]},
    )
    events = []

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(sync_service, "session_scope", fake_session_scope)
    monkeypatch.setattr(sync_service, "replace_wb_supply_file_rows", lambda *args, **kwargs: events.append("replace"))
    monkeypatch.setattr(sync_service, "upsert_wb_supply_source_file", lambda *args, **kwargs: events.append("source"))

    summary = sync_service.sync_wb_supplies_from_google_drive(
        folder_id="folder-1",
        write_db=True,
        drive_client=drive_client,
        sheets_client=sheets_client,
    )

    assert summary["files_processed"] == 1
    assert summary["total_parsed_rows"] == 0
    assert summary["file_summaries"][0]["status"] == "PARTIAL"
    assert summary["file_summaries"][0]["warnings"]
    assert events == ["source"]


def test_sync_wb_supplies_counts_unsupported_files_in_diagnostics() -> None:
    drive_client = FakeDriveClient(
        [
            {
                "id": "pdf-1",
                "name": "Шушары.pdf",
                "mimeType": "application/pdf",
                "modifiedTime": "2026-07-11T10:00:00Z",
                "effectiveMimeType": "application/pdf",
                "webViewLink": "https://example.test/pdf-1",
            },
            {
                "id": "file-1",
                "name": "Шушары",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "modifiedTime": "2026-07-11T11:00:00Z",
                "effectiveMimeType": "application/vnd.google-apps.spreadsheet",
            },
        ]
    )
    sheets_client = FakeSheetsClient(
        {"file-1": ["Лист1"]},
        {("file-1", "'Лист1'!A:ZZ"): [["Артикул ВБ", "Кол-во"], ["111", "2"]]},
    )

    summary = sync_service.sync_wb_supplies_from_google_drive(
        folder_id="folder-1",
        write_db=False,
        drive_client=drive_client,
        sheets_client=sheets_client,
    )

    assert summary["files_total_in_folder"] == 2
    assert summary["supported_files_count"] == 1
    assert summary["unsupported_files_count"] == 1
    assert summary["unsupported_files"][0]["google_file_name"] == "Шушары.pdf"
    assert summary["unsupported_files"][0]["reason"] == "unsupported mimeType: application/pdf"
    assert summary["files_processed"] == 1
    assert summary["total_raw_rows"] > 0