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

from src.scheduler.daily_refresh_scheduler import moscow_now, run_scheduler_worker_loop, run_scheduler_worker_once


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run unified scheduler worker for dashboard + Google Sheets sync jobs.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run startup catchup + due jobs once and exit.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()

    if args.once:
        results = run_scheduler_worker_once(now=moscow_now(), include_startup_catchup=True)
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        has_failures = any(result.get("status") == "failed" for result in results)
        return 1 if has_failures else 0

    run_scheduler_worker_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
