#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db.active_products_backfill import run_backfill_active_products_2days


def main() -> int:
    result = run_backfill_active_products_2days()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("failed_sources"):
        return 1
    if any(count != 0 for count in result.get("duplicate_counts", {}).values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
