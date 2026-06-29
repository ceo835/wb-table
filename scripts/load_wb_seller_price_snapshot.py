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

from src.db.wb_seller_price_loader import load_wb_seller_price_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load WB seller prices from Discounts & Prices API into PostgreSQL.")
    parser.add_argument("--nm-id", dest="nm_ids", action="append", type=int, help="Restrict to specific nm_id. Repeatable.")
    parser.add_argument("--snapshot-date", default=None, help="Snapshot date in YYYY-MM-DD. Default: today.")
    parser.add_argument("--write-db", default="true", help="true/false. Default: true.")
    return parser.parse_args()


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    args = parse_args()
    snapshot_date = date.fromisoformat(args.snapshot_date) if args.snapshot_date else None
    write_db = _parse_bool(str(args.write_db))
    
    summary = load_wb_seller_price_snapshot(
        snapshot_date=snapshot_date,
        nm_ids=args.nm_ids,
        write_db=write_db,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if summary.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
