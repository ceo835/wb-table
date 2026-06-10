#!/usr/bin/env python3
from __future__ import annotations

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

from src.db.stock_loader import load_stocks_to_db


TEST_SNAPSHOT_DATE = date(2026, 6, 1)


def main() -> int:
    result = load_stocks_to_db(TEST_SNAPSHOT_DATE)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["duplicate_keys"] != 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
