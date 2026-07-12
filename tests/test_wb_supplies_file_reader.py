from __future__ import annotations

import io

from openpyxl import Workbook
import pytest

from src.clients.google_drive_client import is_supported_supply_file
from src.services.wb_supplies import file_reader


class FakeDriveClient:
    def __init__(self, downloads=None, resolved=None):
        self._downloads = downloads or {}
        self._resolved = resolved or {}

    def resolve_shortcut_target(self, file_item):
        return self._resolved.get(file_item["id"], file_item)

    def download_file_bytes(self, file_id: str):
        return self._downloads[file_id]


class FakeSheetsClient:
    def __init__(self, titles_by_file=None, rows_by_file_sheet=None):
        self._titles_by_file = titles_by_file or {}
        self._rows_by_file_sheet = rows_by_file_sheet or {}

    def get_worksheet_titles(self, spreadsheet_id: str):
        return self._titles_by_file[spreadsheet_id]

    def read_range(self, spreadsheet_id: str, range_name: str):
        return self._rows_by_file_sheet[(spreadsheet_id, range_name)]


def _build_xlsx_bytes(rows):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Лист1"
    for row in rows:
        worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_supported_file_detection_covers_google_sheet_xlsx_xls_csv_and_shortcut() -> None:
    assert is_supported_supply_file({"mimeType": "application/vnd.google-apps.spreadsheet"})
    assert is_supported_supply_file({"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "name": "supplies.xlsx"})
    assert is_supported_supply_file({"mimeType": "application/vnd.ms-excel", "name": "supplies.xls"})
    assert is_supported_supply_file({"mimeType": "text/csv", "name": "supplies.csv"})
    assert is_supported_supply_file(
        {
            "mimeType": "application/vnd.google-apps.shortcut",
            "shortcutDetails": {
                "targetId": "file-1",
                "targetMimeType": "text/csv",
            },
        }
    )


def test_read_supply_file_reads_google_sheet() -> None:
    workbook = file_reader.read_supply_file(
        {"id": "sheet-1", "name": "Шушары", "mimeType": "application/vnd.google-apps.spreadsheet"},
        drive_client=FakeDriveClient(),
        sheets_client=FakeSheetsClient(
            {"sheet-1": ["Лист1"]},
            {("sheet-1", "'Лист1'!A:ZZ"): [["Артикул ВБ", "Кол-во"], ["111", "3"]]},
        ),
    )

    assert workbook.effective_file_id == "sheet-1"
    assert workbook.effective_mime_type == "application/vnd.google-apps.spreadsheet"
    assert len(workbook.worksheets) == 1
    assert workbook.worksheets[0].rows[1] == ["111", "3"]


def test_read_supply_file_reads_xlsx_bytes() -> None:
    file_bytes = _build_xlsx_bytes([["Артикул ВБ", "Кол-во"], ["123", 5]])
    workbook = file_reader.read_supply_file(
        {"id": "xlsx-1", "name": "Казань.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        drive_client=FakeDriveClient(downloads={"xlsx-1": file_bytes}),
        sheets_client=FakeSheetsClient(),
    )

    assert workbook.effective_file_name == "Казань.xlsx"
    assert workbook.worksheets[0].sheet_name == "Лист1"
    assert workbook.worksheets[0].rows[1][0] == "123"
    assert workbook.worksheets[0].rows[1][1] == 5


def test_read_supply_file_resolves_shortcut_to_csv() -> None:
    csv_bytes = "Артикул ВБ,Кол-во\n222,4\n".encode("utf-8")
    workbook = file_reader.read_supply_file(
        {
            "id": "shortcut-1",
            "name": "Shortcut",
            "mimeType": "application/vnd.google-apps.shortcut",
            "shortcutDetails": {"targetId": "csv-1", "targetMimeType": "text/csv"},
        },
        drive_client=FakeDriveClient(
            downloads={"csv-1": csv_bytes},
            resolved={
                "shortcut-1": {
                    "id": "csv-1",
                    "name": "Поставка.csv",
                    "mimeType": "text/csv",
                    "shortcutSource": {"id": "shortcut-1", "name": "Shortcut"},
                }
            },
        ),
        sheets_client=FakeSheetsClient(),
    )

    assert workbook.source_file_id == "shortcut-1"
    assert workbook.effective_file_id == "csv-1"
    assert workbook.shortcut_source == {"id": "shortcut-1", "name": "Shortcut"}
    assert workbook.worksheets[0].rows[1] == ["222", "4"]


def test_read_supply_file_reports_missing_xls_parser(monkeypatch) -> None:
    monkeypatch.setattr(file_reader.importlib, "import_module", lambda name: (_ for _ in ()).throw(ImportError("missing")))

    with pytest.raises(RuntimeError, match="xlrd"):
        file_reader.read_supply_file(
            {"id": "xls-1", "name": "Поставка.xls", "mimeType": "application/vnd.ms-excel"},
            drive_client=FakeDriveClient(downloads={"xls-1": b"xls"}),
            sheets_client=FakeSheetsClient(),
        )