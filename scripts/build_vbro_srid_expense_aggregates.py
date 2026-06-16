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

from src.reports.vbro_srid_expense_probe import run_vbro_srid_expense_aggregates


def main() -> int:
    result = run_vbro_srid_expense_aggregates()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, default=str))
    print(f"Output dir: {result['output_dir']}")
    print(f"Summary: {result['summary_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
