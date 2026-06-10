#!/usr/bin/env python3
"""
Sync Google Sheets structure with canonical schema definitions.

Default mode is report-only and performs no Google API calls.
Use --apply only when you intentionally want to update the live spreadsheet.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.clients.google_sheets_client import GoogleSheetsClient
from src.config.settings import settings
from src.sheets.schema_definitions import PROCESSED_TABLE_SCHEMAS, USER_SHEET_SCHEMAS
from src.sheets.sync_structure import (
    apply_sync_plan,
    build_sync_plan,
    existing_project_sheet_names,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync sheet headers with canonical field map.")
    parser.add_argument("--apply", action="store_true", help="Apply changes to Google Sheets.")
    parser.add_argument("--spreadsheet-id", help="Override spreadsheet ID from settings.")
    parser.add_argument(
        "--verification-note",
        action="append",
        default=[],
        help="Optional verification note to append into the markdown report.",
    )
    parser.add_argument(
        "--report-path",
        default=str(ROOT_DIR / "docs" / "sheet_structure_sync_report.md"),
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--csv-path",
        default=str(ROOT_DIR / "data" / "processed" / "sheet_structure_sync_report.csv"),
        help="CSV report output path.",
    )
    return parser.parse_args()


def gather_live_sheet_headers(client: GoogleSheetsClient, spreadsheet_id: str) -> dict[str, list[str]]:
    titles = client.get_worksheet_titles(spreadsheet_id) or []
    return {title: client.get_header_row(spreadsheet_id, title) or [] for title in titles}


def write_csv_report(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["sheet_name", "object_type", "status", "details"])
        writer.writerows(rows)


def write_markdown_report(
    path: Path,
    apply_mode: bool,
    existing_project_sheets: list[str],
    added_sheets: list[str],
    updated_headers: list[str],
    processed_added: list[str],
    verification_notes: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial_blocks = [
        "ВБро",
        "Точка вх",
        "Локализация",
        "Сравнение карточек",
        "Поисковые запросы competitor percentiles",
        "ИТОГО / ИТОГО_FULL dynamic wide blocks",
    ]
    lines = [
        "# Sheet Structure Sync Report",
        "",
        f"- Generated at: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Mode: `{'apply' if apply_mode else 'report-only'}`",
        "- Real API / Google Sheets calls for data loading were not performed.",
        "- Existing tab/data rows were not cleared.",
        "- Mock/fake rows were not added.",
        "",
        "## Existing tabs in project definitions",
        "",
    ]
    lines.extend(f"- {name}" for name in existing_project_sheets)
    lines.extend(
        [
            "",
            "## Tabs added to canonical structure",
            "",
        ]
    )
    lines.extend(f"- {name}" for name in added_sheets or ["- none"])
    lines.extend(
        [
            "",
            "## Headers updated in canonical structure",
            "",
        ]
    )
    lines.extend(f"- {name}" for name in updated_headers or ["- none"])
    lines.extend(
        [
            "",
            "## Processed schemas added or normalized",
            "",
        ]
    )
    lines.extend(f"- {name}" for name in processed_added)
    lines.extend(
        [
            "",
            "## PARTIAL / LATER blocks",
            "",
        ]
    )
    lines.extend(f"- {name}" for name in partial_blocks)
    lines.extend(
        [
            "",
            "## Verification",
            "",
        ]
    )
    lines.extend(f"- {note}" for note in verification_notes or ["- Verification notes were not provided."])
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- The report reflects project structure sync and planned Google Sheets header sync.",
            "- Live spreadsheet presence/checks are only available when running this script with `--apply` and a configured spreadsheet ID.",
            "- Data was not populated.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    report_path = Path(args.report_path)
    csv_path = Path(args.csv_path)

    existing_project_sheets = existing_project_sheet_names()
    existing_live_headers = {}
    apply_actions = []

    if args.apply:
        spreadsheet_id = args.spreadsheet_id or settings.google_sheet_id
        if not spreadsheet_id:
            raise ValueError("Spreadsheet ID is required for --apply mode.")
        client = GoogleSheetsClient(spreadsheet_id=spreadsheet_id)
        existing_live_headers = gather_live_sheet_headers(client, spreadsheet_id)
        plan = build_sync_plan(existing_live_headers)
        apply_actions = apply_sync_plan(client, spreadsheet_id, plan)
    else:
        plan = build_sync_plan(existing_sheet_headers={})

    required_sheet_names = list(USER_SHEET_SCHEMAS.keys())
    added_sheets = [name for name in required_sheet_names if name not in existing_project_sheets]
    updated_headers = required_sheet_names
    processed_added = list(PROCESSED_TABLE_SCHEMAS.keys())

    csv_rows: list[list[str]] = []
    for name in required_sheet_names:
        status = "existing_in_project" if name in existing_project_sheets else "added_to_canonical_schema"
        details = "Header row defined in schema definitions."
        csv_rows.append([name, "user_sheet", status, details])

    for name, schema in PROCESSED_TABLE_SCHEMAS.items():
        csv_rows.append(
            [
                name,
                "processed_table",
                "schema_defined",
                f"primary_key={','.join(schema.primary_key)}; service_fields=data_status,source_status,loaded_at",
            ]
        )

    if args.apply:
        for action in apply_actions:
            csv_rows.append([action.sheet_name, "google_sheet_action", action.action, action.details])

    write_csv_report(csv_path, csv_rows)
    write_markdown_report(
        report_path,
        apply_mode=args.apply,
        existing_project_sheets=existing_project_sheets,
        added_sheets=added_sheets,
        updated_headers=updated_headers,
        processed_added=processed_added,
        verification_notes=args.verification_note,
    )

    print(f"Report written to: {report_path}")
    print(f"CSV written to: {csv_path}")
    if args.apply:
        print(f"Applied actions: {len(apply_actions)}")
    else:
        print("No Google Sheets API calls executed (report-only mode).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
