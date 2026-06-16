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

from src.db.wb_site_price_loader import DEFAULT_OUTPUT_DIR, load_wb_site_price_snapshot


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load WB site buyer-visible price snapshots into PostgreSQL.")
    parser.add_argument("--tracked-products", action="store_true", help="Use tracked_products.csv scope.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of tracked products.")
    parser.add_argument("--nm-id", dest="nm_ids", action="append", type=int, help="Restrict to specific nm_id. Repeatable.")
    parser.add_argument("--headless", default="true", help="true/false. Default: true.")
    parser.add_argument("--timeout", type=int, default=30_000, help="Per-page timeout in milliseconds.")
    parser.add_argument("--snapshot-date", default=None, help="Snapshot date in YYYY-MM-DD. Default: today.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Where to store JSON summary.")
    parser.add_argument("--write-db", default="true", help="true/false. Default: true.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = load_wb_site_price_snapshot(
        tracked_products=bool(args.tracked_products),
        nm_ids=args.nm_ids,
        limit=args.limit,
        headless=_parse_bool(str(args.headless)),
        timeout_ms=int(args.timeout),
        snapshot_date=date.fromisoformat(args.snapshot_date) if args.snapshot_date else None,
        write_db=_parse_bool(str(args.write_db)),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if summary.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
