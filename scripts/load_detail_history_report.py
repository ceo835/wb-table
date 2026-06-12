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

from src.db.detail_history_report_loader import load_detail_history_report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load WB Seller Analytics DETAIL_HISTORY_REPORT into fact_funnel_day.")
    parser.add_argument("--date-from", required=True, type=date.fromisoformat)
    parser.add_argument("--date-to", required=True, type=date.fromisoformat)
    parser.add_argument("--nmids-from-file", type=Path)
    parser.add_argument("--nmids", nargs="*", type=int)
    parser.add_argument("--poll-interval-seconds", type=int, default=15)
    parser.add_argument("--max-polls", type=int, default=8)
    parser.add_argument("--save-raw-dir", type=Path, default=ROOT_DIR / "data" / "processed" / "detail_history_reports")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    result = load_detail_history_report(
        date_from=args.date_from,
        date_to=args.date_to,
        nmids_from_file=args.nmids_from_file,
        nm_ids=args.nmids,
        poll_interval_seconds=args.poll_interval_seconds,
        max_polls=args.max_polls,
        dry_run=bool(args.dry_run),
        save_raw_dir=args.save_raw_dir,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if not result.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
