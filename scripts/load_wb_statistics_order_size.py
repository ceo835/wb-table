#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Add src and root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db.wb_statistics_order_size_loader import load_wb_statistics_order_size


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load WB Statistics orders with size level breakdown into DB.")
    parser.add_argument("--date-from", required=True, type=date.fromisoformat, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--date-to", type=date.fromisoformat, default=None, help="End date (YYYY-MM-DD)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Perform checks without writing to database")
    mode.add_argument("--apply", action="store_true", help="Write parsed size level sales data to database")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    
    result = load_wb_statistics_order_size(
        date_from=args.date_from,
        date_to=args.date_to,
        dry_run=bool(args.dry_run),
    )
    
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
