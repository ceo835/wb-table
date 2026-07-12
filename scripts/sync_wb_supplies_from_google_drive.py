from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.services.wb_supplies.sync_service import sync_wb_supplies_from_google_drive


if __name__ == "__main__":
    summary = sync_wb_supplies_from_google_drive(write_db=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
