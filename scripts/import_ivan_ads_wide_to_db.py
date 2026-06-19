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
    write_ivan_ads_wide_duplicate_report,
    write_ivan_ads_wide_skipped_conflicts_report,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dry-run/apply import for Ivan ads wide CSV export.")
    parser.add_argument("--file", required=True, help="Path to ivan_ads_wide CSV export.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run flag. Dry-run is the default.")
    parser.add_argument("--apply", action="store_true", help="Write normalized rows into fact_ivan_ads_wide_day.")
    parser.add_argument("--dedupe", choices=["exact"], help="Allow dropping only fully identical duplicate rows.")
    parser.add_argument(
        "--skip-conflicts",
        action="store_true",
        help="Requires --dedupe exact. Skip all rows that belong to conflicting duplicate keys.",
    )
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args()
    if args.skip_conflicts and args.dedupe != "exact":
        raise SystemExit("--skip-conflicts requires --dedupe exact")
    parsed = parse_ivan_ads_wide_csv(args.file)
    if args.apply:
        summary = apply_ivan_ads_wide_import(parsed, dedupe_mode=args.dedupe, skip_conflicts=args.skip_conflicts)
    else:
        summary = build_ivan_ads_wide_import_dry_run_summary(
            parsed,
            dedupe_mode=args.dedupe,
            skip_conflicts=args.skip_conflicts,
        )
        summary["dry_run_forced"] = True
    summary["duplicate_report_path"] = str(write_ivan_ads_wide_duplicate_report(parsed))
    if args.skip_conflicts:
        summary["skipped_conflicts_report_path"] = str(
            write_ivan_ads_wide_skipped_conflicts_report(parsed, dedupe_mode=args.dedupe)
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
