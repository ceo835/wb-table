#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select

from src.db.models import MartTotalReport
from src.db.session import session_scope


CHECK_COLUMNS = [
    "report_date",
    "supplier_article",
    "nm_id",
    "cart_count",
    "ad_atbs_total",
    "associated_ad_atbs",
    "organic_cart_count",
    "organic_cart_share_calc",
    "ad_campaign_spend_total",
    "ad_cost_per_all_carts_calc",
    "order_count",
    "cart_to_order_conversion_calc",
    "impressions",
    "card_clicks",
    "ctr_calc",
    "add_to_cart_conversion_calc",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export top-10 itogo formula check rows.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args()


def row_to_dict(row: MartTotalReport) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in MartTotalReport.__table__.columns}


def main() -> int:
    args = parse_args()
    report_date = date.fromisoformat(args.date)
    output_path = ROOT_DIR / "data" / "processed" / f"itogo_formula_check_{report_date.isoformat()}.csv"

    with session_scope() as session:
        rows = [
            row_to_dict(row)
            for row in session.execute(
            select(MartTotalReport)
            .where(MartTotalReport.report_date == report_date)
            .order_by(MartTotalReport.order_sum.desc().nullslast(), MartTotalReport.nm_id.asc())
            .limit(args.limit)
        ).scalars().all()
        ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CHECK_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
