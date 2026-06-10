#!/usr/bin/env python3
from __future__ import annotations

import argparse
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

from src.ad_campaign_product_dataset import (
    AD_CAMPAIGN_PRODUCT_DATASET_PATH,
    fetch_ad_campaign_product_rows,
    write_ad_campaign_product_csv,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Streamlit ad campaign by product dataset.")
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    return parser.parse_args()


def export_ad_campaign_product_dataset(date_from: date, date_to: date) -> dict[str, object]:
    rows = fetch_ad_campaign_product_rows(date_from, date_to)
    write_ad_campaign_product_csv(AD_CAMPAIGN_PRODUCT_DATASET_PATH, rows)

    dates = sorted({row["report_date"].isoformat() for row in rows if row.get("report_date") is not None})
    nm_ids = {row["nm_id"] for row in rows if row.get("nm_id") is not None}
    advert_ids = {row["advert_id"] for row in rows if row.get("advert_id") is not None}
    conversion_types = sorted({str(row["conversion_type"]) for row in rows if row.get("conversion_type") not in (None, "")})

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "total_rows": len(rows),
        "dates": dates,
        "products_count": len(nm_ids),
        "campaigns_count": len(advert_ids),
        "conversion_types_count": len(conversion_types),
        "conversion_types": conversion_types,
        "writeoff_included": False,
        "output_path": str(AD_CAMPAIGN_PRODUCT_DATASET_PATH),
    }


def main() -> int:
    args = parse_args()
    summary = export_ad_campaign_product_dataset(
        date_from=date.fromisoformat(args.date_from),
        date_to=date.fromisoformat(args.date_to),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
