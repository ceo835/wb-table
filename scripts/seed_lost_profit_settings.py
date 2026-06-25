from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import ensure_safe_database_environment
from src.db.lost_profit_settings import seed_lost_profit_settings_to_db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed lost-profit market/warehouse area settings.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write seed data into PostgreSQL. Without this flag the script runs in dry-run mode.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.apply:
        ensure_safe_database_environment()
    summary = seed_lost_profit_settings_to_db(apply=args.apply)
    print("seed_lost_profit_settings summary:")
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
