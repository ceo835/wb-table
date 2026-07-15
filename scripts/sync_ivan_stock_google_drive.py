from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.services.google_drive_daily_sync import sync_ivan_stock_from_google_drive


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync IVAN_STOCK files from Google Drive.")
    parser.add_argument("--apply", action="store_true", help="Write parsed data and source journal to database.")
    parser.add_argument("--date", type=str, default=None, help="Run date in YYYY-MM-DD format.")
    args = parser.parse_args()

    run_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else datetime.utcnow().date()
    summary = sync_ivan_stock_from_google_drive(run_date=run_date, write_db=args.apply)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 1 if summary.get("failed_files", 0) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
