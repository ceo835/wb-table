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

from src.db.ivan_stock_sheet_loader import load_ivan_stock_sheet


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load Ivan's stock sheet from Google Sheets.")
    parser.add_argument("--apply", action="store_true", help="Commit changes to the database.")
    parser.add_argument("--dry-run", action="store_true", help="Run without database commit (default).")
    parser.add_argument("--sheet-id", help="Override default Google Sheets ID.")
    return parser


def main() -> int:
    # Fix stdout encoding to UTF-8 for Windows console
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    elif sys.stdout.encoding != 'utf-8':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
        
    args = build_arg_parser().parse_args()
    
    # Defaults to dry-run unless --apply is set
    write_db = args.apply
    
    try:
        summary = load_ivan_stock_sheet(sheet_id=args.sheet_id, write_db=write_db)
        summary["dry_run"] = not write_db
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as e:
        logger_err = {
            "success": False,
            "error": str(e),
            "dry_run": not write_db,
        }
        print(json.dumps(logger_err, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
