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

from src.db.localization_loader import load_localization_to_db


def main() -> int:
    result = load_localization_to_db()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if (
        result["duplicate_keys"] != 0
        or result["nonnull_regional_stock_rows"] != 0
        or result["nonnull_local_nonlocal_rows"] != 0
        or result["nonnull_delivery_time_rows"] != 0
        or result["mock_like_rows"] != 0
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
