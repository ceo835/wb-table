from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db.stock_warehouse_loader import DEFAULT_OUTPUT_DIR, DEFAULT_PAGE_LIMIT, load_stock_warehouse_snapshot


def default_snapshot_date() -> str:
    return date.today().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load WB warehouse-level stock snapshots into PostgreSQL.")
    parser.add_argument(
        "--snapshot-date",
        default=default_snapshot_date(),
        help="Snapshot date in YYYY-MM-DD. Default: today.",
    )
    parser.add_argument(
        "--tracked-products",
        action="store_true",
        help="Restrict saved rows to tracked_products.csv list.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_PAGE_LIMIT,
        help="Page size for API pagination.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional hard cap for loaded pages.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Where to store raw/normalized/aggregate/summary artifacts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write rows into PostgreSQL, only fetch and store artifacts.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = load_stock_warehouse_snapshot(
        snapshot_date=date.fromisoformat(args.snapshot_date),
        tracked_products=args.tracked_products,
        limit=args.limit,
        max_pages=args.max_pages,
        output_dir=Path(args.output_dir),
        write_db=not args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
