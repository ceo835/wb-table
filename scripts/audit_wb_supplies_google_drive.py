from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.services.wb_supplies.sync_service import build_wb_supplies_audit_report, sync_wb_supplies_from_google_drive


if __name__ == "__main__":
    summary = sync_wb_supplies_from_google_drive(write_db=False)
    report = build_wb_supplies_audit_report(summary)
    report_path = ROOT_DIR / 'docs' / 'wb_supplies_google_drive_audit_report.md'
    report_path.write_text(report, encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(f"Audit report saved to {report_path}")
