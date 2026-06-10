#!/usr/bin/env python3
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
from src.pipelines.mvp_real_run import _build_suspicious_ctr_validation_rows, _sanitize_funnel_ctr_row
from src.sheets.schema_definitions import PROCESSED_TABLE_SCHEMAS, USER_SHEET_SCHEMAS


DATA_DIR = ROOT_DIR / "data" / "processed"
FACT_FUNNEL_PATH = DATA_DIR / "fact_funnel_day.csv"
FORBIDDEN_MARKERS = ("ART-", "TestBrand", "Товар тестовый", "DRY_RUN", "mock", "fake")
FUNNEL_SHEET = "Воронка на день"
VALIDATION_SHEET = "Validation_v1"
DIFF_COLUMNS = (
    "date",
    "nm_id",
    "impressions",
    "card_clicks",
    "ctr",
    "impressions_prev",
    "card_clicks_prev",
    "ctr_prev",
)
FUNNEL_COLUMN_MAP = {
    "date": "Дата",
    "nm_id": "Артикул WB",
    "impressions": "Показы",
    "card_clicks": "Переходы в карточку",
    "ctr": "CTR",
    "impressions_prev": "Показы (предыдущий период)",
    "card_clicks_prev": "Переходы в карточку (предыдущий период)",
    "ctr_prev": "CTR (предыдущий период)",
}


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


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _write_csv_rows(path: Path, rows: list[dict[str, Any]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _row_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (_stringify(row.get("date", "")), _stringify(row.get("nm_id", "")))


def _build_diff_rows(before_rows: list[dict[str, Any]], after_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before_index = {_row_key(row): row for row in before_rows}
    after_index = {_row_key(row): row for row in after_rows}
    diff_rows: list[dict[str, Any]] = []
    for key in sorted(after_index):
        before = before_index.get(key, {})
        after = after_index[key]
        if any(_stringify(before.get(column, "")) != _stringify(after.get(column, "")) for column in DIFF_COLUMNS[2:]):
            diff_row = {column: after.get(column, "") for column in DIFF_COLUMNS}
            diff_row["_before"] = {column: before.get(column, "") for column in DIFF_COLUMNS}
            diff_rows.append(diff_row)
    return diff_rows


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


def _load_sheet_rows(client: GoogleSheetsClient, spreadsheet_id: str, sheet_name: str) -> tuple[list[str], list[dict[str, str]]]:
    columns = USER_SHEET_SCHEMAS[sheet_name].columns
    end_col = _column_letter(len(columns))
    escaped = sheet_name.replace("'", "''")
    values = client.read_range(spreadsheet_id, f"'{escaped}'!A1:{end_col}5000") or []
    header = [_stringify(value) for value in values[0]] if values else []
    rows: list[dict[str, str]] = []
    for raw_row in values[1:]:
        row_values = [_stringify(value) for value in raw_row]
        if not any(row_values):
            continue
        rows.append({header[i]: row_values[i] if i < len(row_values) else "" for i in range(len(header))})
    return header, rows


def _patch_funnel_sheet_rows(sheet_rows: list[dict[str, str]], cleaned_index: Mapping[tuple[str, str], Mapping[str, Any]]) -> list[dict[str, Any]]:
    patched_rows: list[dict[str, Any]] = []
    for row in sheet_rows:
        patched = dict(row)
        key = (_stringify(row.get("Дата", "")), _stringify(row.get("Артикул WB", "")))
        cleaned = cleaned_index.get(key)
        if cleaned:
            for processed_column, sheet_column in FUNNEL_COLUMN_MAP.items():
                patched[sheet_column] = cleaned.get(processed_column, "")
        patched_rows.append(patched)
    return patched_rows


def _count_forbidden(rows: Sequence[Mapping[str, Any]]) -> int:
    issues = 0
    for row in rows:
        if any(any(marker.lower() in _stringify(value).lower() for marker in FORBIDDEN_MARKERS) for value in row.values()):
            issues += 1
    return issues


def _count_duplicate_keys(rows: Sequence[Mapping[str, Any]], key_fields: Sequence[str]) -> int:
    keys = [tuple(_stringify(row.get(field, "")) for field in key_fields) for row in rows]
    return len(keys) - len(set(keys))


def _has_artificial_ctr(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        impressions = _stringify(row.get("Показы", ""))
        card_clicks = _stringify(row.get("Переходы в карточку", ""))
        ctr = _stringify(row.get("CTR", ""))
        if impressions and impressions == card_clicks and ctr in {"100", "100.0", "100.00"}:
            return True
    return False


def _build_summary(diff_rows: list[dict[str, Any]], validation_rows: list[dict[str, Any]]) -> dict[str, Any]:
    preview: list[dict[str, Any]] = []
    for row in diff_rows[:10]:
        preview.append(
            {
                "Дата": _stringify(row.get("date", "")),
                "Артикул WB": _stringify(row.get("nm_id", "")),
                "Показы": _stringify(row.get("impressions", "")),
                "Переходы в карточку": _stringify(row.get("card_clicks", "")),
                "CTR": _stringify(row.get("ctr", "")),
                "Показы (предыдущий период)": _stringify(row.get("impressions_prev", "")),
                "Переходы в карточку (предыдущий период)": _stringify(row.get("card_clicks_prev", "")),
                "CTR (предыдущий период)": _stringify(row.get("ctr_prev", "")),
                "before": row["_before"],
            }
        )
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "changed_rows": len(diff_rows),
        "validation_rows_after_fix": len(validation_rows),
        "diff_preview": preview,
    }


def main(apply: bool = False) -> dict[str, Any]:
    before_rows = _load_csv_rows(FACT_FUNNEL_PATH)
    after_rows = [_sanitize_funnel_ctr_row(row) for row in before_rows]
    diff_rows = _build_diff_rows(before_rows, after_rows)
    validation_rows = _build_suspicious_ctr_validation_rows(after_rows)
    summary = _build_summary(diff_rows, validation_rows)

    if not apply:
        print(summary)
        return summary

    spreadsheet_id = settings.google_sheet_id
    if not spreadsheet_id:
        raise RuntimeError("GOOGLE_SHEET_ID is missing")

    _write_csv_rows(FACT_FUNNEL_PATH, after_rows, PROCESSED_TABLE_SCHEMAS["fact_funnel_day"].columns)
    client = GoogleSheetsClient(spreadsheet_id=spreadsheet_id)
    _, live_funnel_rows = _load_sheet_rows(client, spreadsheet_id, FUNNEL_SHEET)
    cleaned_index = {_row_key(row): row for row in after_rows}
    patched_funnel_rows = _patch_funnel_sheet_rows(live_funnel_rows, cleaned_index)

    funnel_written = _replace_sheet_rows(client, spreadsheet_id, FUNNEL_SHEET, patched_funnel_rows)
    validation_written = _replace_sheet_rows(client, spreadsheet_id, VALIDATION_SHEET, validation_rows)

    _, funnel_readback = _load_sheet_rows(client, spreadsheet_id, FUNNEL_SHEET)
    _, validation_readback = _load_sheet_rows(client, spreadsheet_id, VALIDATION_SHEET)
    summary.update(
        {
            "applied": True,
            "funnel_rows_written": funnel_written,
            "validation_rows_written": validation_written,
            "funnel_rows_readback": len(funnel_readback),
            "validation_rows_readback": len(validation_readback),
            "funnel_duplicate_keys": _count_duplicate_keys(funnel_readback, ("Дата", "Артикул WB")),
            "forbidden_markers": _count_forbidden(funnel_readback),
            "artificial_ctr_remaining": _has_artificial_ctr(funnel_readback),
        }
    )
    print(summary)
    return summary


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
