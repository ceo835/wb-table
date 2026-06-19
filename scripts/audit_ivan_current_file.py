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

from src.importers.ivan_current_importer import parse_ivan_current_file, persist_ivan_current_audit_report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only audit for Ivan current file.")
    parser.add_argument("--input", required=True, help="Path to ivan_current CSV/XLSX file.")
    parser.add_argument("--only-active-products", action="store_true", help="Restrict audit summary to settings_products.active=true scope.")
    parser.add_argument(
        "--output-dir",
        default=str(Path("data") / "manual_imports" / "ivan_current"),
        help="Directory for audit_report.json and unmapped_columns.csv.",
    )
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_arg_parser().parse_args()
    parsed = parse_ivan_current_file(args.input)
    summary = persist_ivan_current_audit_report(
        parsed,
        only_active_products=bool(args.only_active_products),
        output_dir=args.output_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
