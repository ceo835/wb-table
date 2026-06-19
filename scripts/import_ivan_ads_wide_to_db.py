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

from src.importers.ivan_ads_wide_importer import (
    apply_ivan_ads_wide_import,
    build_ivan_ads_wide_import_dry_run_summary,
    parse_ivan_ads_wide_csv,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-run/apply import for Ivan ads wide CSV export.")
    parser.add_argument("--file", required=True, help="Path to ivan_ads_wide CSV export.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run flag. Dry-run is the default.")
    parser.add_argument("--apply", action="store_true", help="Write normalized rows into fact_ivan_ads_wide_day.")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args()
    parsed = parse_ivan_ads_wide_csv(args.file)
    if args.apply:
        summary = apply_ivan_ads_wide_import(parsed)
    else:
        summary = build_ivan_ads_wide_import_dry_run_summary(parsed)
        summary["dry_run_forced"] = True
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
