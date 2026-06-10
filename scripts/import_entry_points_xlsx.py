#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.importers.entry_points_importer import import_entry_points_xlsx


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import WB entry-points XLSX into fact_entry_point_day.")
    parser.add_argument("--file", required=True, help="Path to WB entry-points xlsx export.")
    parser.add_argument("--date", help="Explicit report date in YYYY-MM-DD format.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Read and validate file without DB writes.")
    mode.add_argument("--apply", action="store_true", help="Read file and upsert normalized rows into PostgreSQL.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    result = import_entry_points_xlsx(
        args.file,
        explicit_date=_parse_date(args.date),
        apply=bool(args.apply),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result.get("missing_required_columns"):
        return 1
    if args.apply and result.get("duplicate_keys", 0) != 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
