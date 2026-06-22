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

from src.reports.wb_api_data_availability import DEFAULT_PROJECT_TIMEZONE, run_availability_probe


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only WB API availability probe for yesterday/target_date.")
    parser.add_argument("--target-date", type=date.fromisoformat, help="Explicit target date YYYY-MM-DD. Default: yesterday in Europe/Moscow.")
    parser.add_argument("--timezone", default=DEFAULT_PROJECT_TIMEZONE, help="Timezone for default target date resolution.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = run_availability_probe(target_date=args.target_date, timezone_name=args.timezone)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
