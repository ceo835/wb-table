#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
import argparse


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db.mart_total_report_builder import build_mart_total_report


TEST_DATE_FROM = date(2026, 5, 31)
TEST_DATE_TO = date(2026, 6, 1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build mart_total_report from PostgreSQL facts.")
    parser.add_argument("--date-from", default=TEST_DATE_FROM.isoformat())
    parser.add_argument("--date-to", default=TEST_DATE_TO.isoformat())
    parser.add_argument("--version", default="v2", choices=["v1", "v2"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_mart_total_report(
        date.fromisoformat(args.date_from),
        date.fromisoformat(args.date_to),
        version=args.version,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["duplicate_keys"] != 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
