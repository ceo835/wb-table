from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.clients.google_sheets_client import GoogleSheetsClient
from src.config.settings import settings
from src.pipelines.mvp_real_run import _build_suspicious_ctr_validation_rows
from src.sheets.backlog_builder import build_backlog_rows
from src.sheets.coverage_builder import build_coverage_rows
from src.sheets.schema_definitions import USER_SHEET_SCHEMAS


DATA_DIR = ROOT_DIR / "data" / "processed"
FACT_FUNNEL_PATH = DATA_DIR / "fact_funnel_day.csv"
FORBIDDEN_MARKERS = ("ART-", "TestBrand", "Товар тестовый", "DRY_RUN", "mock", "fake")
MAIN_SHEETS = (
    "Воронка на день",
    "РасходРК",
    "РК стата",
    "Поисковые запросы",
    "Локализация",
    "ВБро",
)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _column_letter(index: int) -> str:
    result = ""
    while index > 0:
        index -= 1
        result = chr(65 + index % 26) + result
        index //= 26
    return result


def _ordered_values(row: Mapping[str, Any], columns: Sequence[str]) -> list[Any]:
    return [row.get(column, "") for column in columns]


def _load_funnel_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _ensure_headers(client: GoogleSheetsClient, spreadsheet_id: str, sheet_name: str) -> None:
    headers = list(USER_SHEET_SCHEMAS[sheet_name].columns)
    client.ensure_worksheet(spreadsheet_id, sheet_name)
    current = client.get_header_row(spreadsheet_id, sheet_name) or []
    if list(current) != headers:
        client.update_header_row(spreadsheet_id, sheet_name, headers)


def _replace_sheet_rows(client: GoogleSheetsClient, spreadsheet_id: str, sheet_name: str, rows: list[dict[str, Any]]) -> int:
    headers = USER_SHEET_SCHEMAS[sheet_name].columns
    _ensure_headers(client, spreadsheet_id, sheet_name)
    end_col = _column_letter(len(headers))
    client.clear_range(spreadsheet_id, f"{sheet_name}!A2:{end_col}5000")
    if not rows:
        return 0
    values = [_ordered_values(row, headers) for row in rows]
    client.write_rows(spreadsheet_id, sheet_name, values, start_row=2, start_col=1)
    return len(rows)


def _load_sheet_rows(client: GoogleSheetsClient, spreadsheet_id: str, sheet_name: str) -> list[dict[str, str]]:
    columns = USER_SHEET_SCHEMAS[sheet_name].columns
    end_col = _column_letter(len(columns))
    values = client.read_range(spreadsheet_id, f"'{sheet_name}'!A1:{end_col}5000") or []
    header = [_stringify(value) for value in values[0]] if values else []
    rows: list[dict[str, str]] = []
    for raw_row in values[1:]:
        row_values = [_stringify(value) for value in raw_row]
        if not any(row_values):
            continue
        rows.append({header[i]: row_values[i] if i < len(row_values) else "" for i in range(len(header))})
    return rows


def _count_sheet_rows(client: GoogleSheetsClient, spreadsheet_id: str, sheet_name: str) -> int:
    return len(_load_sheet_rows(client, spreadsheet_id, sheet_name))


def _count_forbidden(rows: list[dict[str, str]]) -> int:
    count = 0
    for row in rows:
        if any(any(marker.lower() in _stringify(cell).lower() for marker in FORBIDDEN_MARKERS) for cell in row.values()):
            count += 1
    return count


def main() -> dict[str, Any]:
    spreadsheet_id = settings.google_sheet_id
    if not spreadsheet_id:
        raise RuntimeError("GOOGLE_SHEET_ID is missing")

    client = GoogleSheetsClient(spreadsheet_id=spreadsheet_id)
    before_counts = {sheet: _count_sheet_rows(client, spreadsheet_id, sheet) for sheet in MAIN_SHEETS}

    backlog_rows = build_backlog_rows()
    coverage_rows = build_coverage_rows()
    validation_rows = _build_suspicious_ctr_validation_rows(_load_funnel_rows(FACT_FUNNEL_PATH))

    updated = {
        "Backlog": _replace_sheet_rows(client, spreadsheet_id, "Backlog", backlog_rows),
        "Coverage": _replace_sheet_rows(client, spreadsheet_id, "Coverage", coverage_rows),
        "Validation_v1": _replace_sheet_rows(client, spreadsheet_id, "Validation_v1", validation_rows),
    }

    after_counts = {sheet: _count_sheet_rows(client, spreadsheet_id, sheet) for sheet in MAIN_SHEETS}
    preserved = {sheet: before_counts[sheet] == after_counts[sheet] for sheet in MAIN_SHEETS}

    validation_live_rows = _load_sheet_rows(client, spreadsheet_id, "Validation_v1")
    backlog_live_rows = _load_sheet_rows(client, spreadsheet_id, "Backlog")
    coverage_live_rows = _load_sheet_rows(client, spreadsheet_id, "Coverage")
    main_forbidden = {
        sheet: _count_forbidden(_load_sheet_rows(client, spreadsheet_id, sheet))
        for sheet in MAIN_SHEETS
    }

    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated_sheets": updated,
        "suspicious_ctr_rows": len(validation_live_rows),
        "main_sheet_rows_before": before_counts,
        "main_sheet_rows_after": after_counts,
        "main_sheet_rows_preserved": preserved,
        "forbidden_markers": main_forbidden,
        "backlog_rows": len(backlog_live_rows),
        "coverage_rows": len(coverage_live_rows),
        "api_calls_executed": False,
    }
    print(summary)
    return summary


if __name__ == "__main__":
    main()
