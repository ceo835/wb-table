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

from src.importers.ivan_current_importer import (
    SUPPORTED_IMPORT_MODES,
    apply_ivan_current_insert_missing,
    build_ivan_current_import_dry_run_summary,
    persist_ivan_current_import_dry_run_report,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-run import for normalized Ivan current files.")
    parser.add_argument("--source-dir", required=True, help="Directory with normalized Ivan current CSV files.")
    parser.add_argument("--only-active-products", action="store_true", help="Restrict import dry-run to settings_products.active=true.")
    parser.add_argument("--mode", default="insert-missing", choices=SUPPORTED_IMPORT_MODES, help="Dry-run mode. Apply is intentionally disabled.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run flag. Dry-run is always used in this script.")
    parser.add_argument("--apply", action="store_true", help="Insert only missing fact_funnel_day rows after empty-row guard.")
    parser.add_argument(
        "--output-dir",
        default=str(Path("data") / "manual_imports" / "ivan_current"),
        help="Directory for dry-run JSON and CSV reports.",
    )
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args()
    if args.apply:
        summary = apply_ivan_current_insert_missing(
            source_dir=args.source_dir,
            only_active_products=bool(args.only_active_products),
            mode=args.mode,
            output_dir=args.output_dir,
        )
    else:
        summary = build_ivan_current_import_dry_run_summary(
            source_dir=args.source_dir,
            only_active_products=bool(args.only_active_products),
            mode=args.mode,
        )
        summary["dry_run_forced"] = True
        summary = persist_ivan_current_import_dry_run_report(summary, output_dir=args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
