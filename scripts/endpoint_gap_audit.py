#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.reports.endpoint_gap_audit import (
    CSV_REPORT_PATH,
    DOCS_REPORT_PATH,
    JSON_SUMMARY_PATH,
    run_endpoint_gap_audit,
    write_csv_report,
    write_json_summary,
    write_markdown_report,
)


def main() -> None:
    blocks, fields, summary = run_endpoint_gap_audit()
    write_markdown_report(DOCS_REPORT_PATH, blocks, fields, summary)
    write_csv_report(CSV_REPORT_PATH, fields)
    write_json_summary(JSON_SUMMARY_PATH, summary)

    print(f"Markdown report: {DOCS_REPORT_PATH}")
    print(f"CSV report: {CSV_REPORT_PATH}")
    print(f"JSON summary: {JSON_SUMMARY_PATH}")


if __name__ == "__main__":
    main()
