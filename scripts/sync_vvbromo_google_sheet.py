#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Try importing zoneinfo (Python 3.9+) or fallback to UTC/local
try:
    import zoneinfo
    moscow_tz = zoneinfo.ZoneInfo("Europe/Moscow")
except Exception:
    moscow_tz = None

def get_current_moscow_year() -> int:
    if moscow_tz:
        return datetime.now(moscow_tz).year
    return datetime.now().year

# Set up logger
logger = logging.getLogger("sync_vvbromo")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def main() -> int:
    default_year = get_current_moscow_year()
    
    parser = argparse.ArgumentParser(description="Regular production loader/syncer for VVBromo sheet.")
    parser.add_argument("--year", type=int, default=default_year, help=f"Year to associate with sheet dates (default: {default_year}).")
    parser.add_argument("--apply", action="store_true", help="Write parsed data to database.")
    parser.add_argument("--dry-run", action="store_true", help="Force run without writing to database (dry-run is active by default unless --apply is passed).")
    args = parser.parse_args()

    # Determine whether to apply or dry-run
    # --dry-run overrides --apply
    apply = args.apply and not args.dry_run
    dry_run = not apply

    from src.config.settings import settings
    from scripts.parse_vvbromo_sheet import run_loader

    spreadsheet_id = settings.vvbromo_google_sheet_id
    sheet_name = settings.vvbromo_google_sheet_name or "VVBromo"

    logger.info("Starting VVBromo sync pipeline...")
    logger.info(f"Target spreadsheet_id: {spreadsheet_id}")
    logger.info(f"Target sheet_name: {sheet_name}")
    logger.info(f"Target year: {args.year}")
    logger.info(f"Execution mode: {'APPLY (write to DB)' if apply else 'DRY-RUN (read only)'}")

    try:
        summary = run_loader(year=args.year, apply=apply, dry_run=dry_run)
        
        # Prepare summary logs
        log_summary = {
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "dates_found": summary["distinct_dates"],
            "rows_parsed": summary["rows_parsed"],
            "rows_upserted": summary["rows_upserted"],
            "date_min": summary["date_min"],
            "date_max": summary["date_max"],
            "distinct_nm_id": summary["distinct_nm_id"],
            "errors_count": summary["errors"],
            "db_changed": summary["db_changed"]
        }

        # Print JSON summary to stdout
        print(json.dumps(log_summary, ensure_ascii=False, indent=2))
        
        return 0
    except Exception as e:
        logger.error(f"Sync execution failed: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
