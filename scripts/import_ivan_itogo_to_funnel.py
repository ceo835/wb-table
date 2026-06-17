#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.importers.ivan_itogo_importer import (
    SUPPORTED_IMPORT_SCOPES,
    apply_ivan_itogo_insert_missing,
    build_ivan_itogo_import_dry_run_summary,
    build_ivan_itogo_insert_missing_summary,
    parse_ivan_itogo_csv,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare Ivan itogo CSV import into fact_funnel_day.")
    parser.add_argument("--file", required=True, help="Path to ivan_itogo CSV export.")
    parser.add_argument(
        "--mode",
        default="insert-missing",
        choices=("insert-missing",),
        help="Import mode. Existing fact_funnel_day rows for the same date+nm_id are skipped.",
    )
    parser.add_argument(
        "--scope",
        default="tracked",
        choices=SUPPORTED_IMPORT_SCOPES,
        help="Import scope. Default is tracked products only.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run flag. Dry-run is the default.")
    parser.add_argument("--apply", action="store_true", help="Write only missing date+nm_id rows into fact_funnel_day.")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args()
    parsed = parse_ivan_itogo_csv(args.file)
    if args.mode == "insert-missing":
        summary = (
            apply_ivan_itogo_insert_missing(parsed, scope=args.scope)
            if args.apply
            else build_ivan_itogo_insert_missing_summary(parsed, scope=args.scope)
        )
    else:
        summary = build_ivan_itogo_import_dry_run_summary(parsed)
    summary["requested_mode"] = args.mode
    summary["requested_scope"] = args.scope
    summary["write_requested"] = bool(args.apply)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    if args.apply and not summary.get("write_executed"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
