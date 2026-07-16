#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db.wb_finance_realization_loader import load_wb_finance_realization_to_db


def _default_end_date() -> date:
    return datetime.now(UTC).date() - timedelta(days=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load WB financial realization lines from reportDetailByPeriod.")
    parser.add_argument(
        "--date-from",
        default=(_default_end_date() - timedelta(days=6)).isoformat(),
        help="Start date in YYYY-MM-DD. Default: last 7 days ending yesterday UTC.",
    )
    parser.add_argument(
        "--date-to",
        default=_default_end_date().isoformat(),
        help="End date in YYYY-MM-DD. Default: yesterday UTC.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and normalize rows without writing to DB.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    date_from = date.fromisoformat(args.date_from)
    date_to = date.fromisoformat(args.date_to)
    result = load_wb_finance_realization_to_db(
        date_from,
        date_to,
        write_db=not args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") != "200":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
