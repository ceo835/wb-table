#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import distinct, func, select

from src.db.ad_campaign_loader import load_ad_campaign_stats_to_db
from src.db.models import FactAdCampaignDay, FactAdCampaignNmDay, FactAdCostEvent
from src.db.session import session_scope


TEST_DATE_FROM = date(2026, 5, 31)
TEST_DATE_TO = date(2026, 6, 1)
DEFAULT_LIMIT = 5
DEFAULT_SLEEP_SECONDS = 45


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _load_ad_event_groups(date_from: date, date_to: date, limit: int | None = None) -> list[tuple[int, list[dict[str, object]]]]:
    with session_scope() as session:
        rows = session.execute(
            select(
                FactAdCostEvent.advert_id,
                FactAdCostEvent.campaign_name,
                FactAdCostEvent.nm_id,
            )
            .where(
                FactAdCostEvent.date >= date_from,
                FactAdCostEvent.date <= date_to,
                FactAdCostEvent.advert_id.is_not(None),
                FactAdCostEvent.nm_id.is_not(None),
            )
            .order_by(FactAdCostEvent.advert_id, FactAdCostEvent.nm_id)
        ).all()

    grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        advert_id = int(row.advert_id)
        grouped[advert_id].append(
            {
                "advertId": advert_id,
                "campaign_name": row.campaign_name,
                "nm_id": int(row.nm_id),
            }
        )

    advert_ids = sorted(grouped)
    if limit is not None:
        advert_ids = advert_ids[:limit]
    return [(advert_id, grouped[advert_id]) for advert_id in advert_ids]


def _unique_nm_ids(rows: list[dict[str, object]]) -> list[int]:
    return sorted({int(row["nm_id"]) for row in rows if row.get("nm_id") is not None})


def _load_processed_advert_ids(date_from: date, date_to: date) -> set[int]:
    with session_scope() as session:
        rows = session.execute(
            select(distinct(FactAdCampaignDay.advert_id)).where(
                FactAdCampaignDay.date >= date_from,
                FactAdCampaignDay.date <= date_to,
            )
        ).all()
    return {int(row[0]) for row in rows if row[0] is not None}


def _count_rows_and_duplicates(date_from: date, date_to: date) -> dict[str, int]:
    with session_scope() as session:
        campaign_day_rows = int(
            session.execute(
                select(func.count())
                .select_from(FactAdCampaignDay)
                .where(FactAdCampaignDay.date >= date_from, FactAdCampaignDay.date <= date_to)
            ).scalar_one()
        )
        campaign_nm_rows = int(
            session.execute(
                select(func.count())
                .select_from(FactAdCampaignNmDay)
                .where(FactAdCampaignNmDay.date >= date_from, FactAdCampaignNmDay.date <= date_to)
            ).scalar_one()
        )
        campaign_day_duplicates = len(
            session.execute(
                select(FactAdCampaignDay.date, FactAdCampaignDay.advert_id, FactAdCampaignDay.row_type)
                .where(FactAdCampaignDay.date >= date_from, FactAdCampaignDay.date <= date_to)
                .group_by(FactAdCampaignDay.date, FactAdCampaignDay.advert_id, FactAdCampaignDay.row_type)
                .having(func.count() > 1)
            ).all()
        )
        campaign_nm_duplicates = len(
            session.execute(
                select(
                    FactAdCampaignNmDay.date,
                    FactAdCampaignNmDay.advert_id,
                    FactAdCampaignNmDay.row_type,
                    FactAdCampaignNmDay.conversion_type_raw,
                    FactAdCampaignNmDay.nm_id,
                )
                .where(FactAdCampaignNmDay.date >= date_from, FactAdCampaignNmDay.date <= date_to)
                .group_by(
                    FactAdCampaignNmDay.date,
                    FactAdCampaignNmDay.advert_id,
                    FactAdCampaignNmDay.row_type,
                    FactAdCampaignNmDay.conversion_type_raw,
                    FactAdCampaignNmDay.nm_id,
                )
                .having(func.count() > 1)
            ).all()
        )
    return {
        "fact_ad_campaign_day_rows": campaign_day_rows,
        "fact_ad_campaign_nm_day_rows": campaign_nm_rows,
        "fact_ad_campaign_day_duplicates": campaign_day_duplicates,
        "fact_ad_campaign_nm_day_duplicates": campaign_nm_duplicates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Slow smoke-test for WB fullstats on a few advert_ids.")
    parser.add_argument("--date-from", type=_parse_date, default=TEST_DATE_FROM, help="Start date, YYYY-MM-DD.")
    parser.add_argument("--date-to", type=_parse_date, default=TEST_DATE_TO, help="End date, YYYY-MM-DD.")
    parser.add_argument("--limit", type=int, default=None, help="Optional cap for advert_id values.")
    parser.add_argument(
        "--sleep-seconds",
        type=int,
        default=DEFAULT_SLEEP_SECONDS,
        help="Sleep between advert_id requests in seconds.",
    )
    parser.add_argument("--resume", action="store_true", help="Skip advert_id values that already have rows in fact_ad_campaign_day.")
    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be >= 1")
    if args.sleep_seconds < 1:
        raise SystemExit("--sleep-seconds must be >= 1")
    if args.date_from > args.date_to:
        raise SystemExit("--date-from must be <= --date-to")

    all_groups = _load_ad_event_groups(args.date_from, args.date_to, limit=None)
    total_advert_ids_found = len(all_groups)
    processed_before = _load_processed_advert_ids(args.date_from, args.date_to)

    groups = all_groups
    if args.resume:
        groups = [(advert_id, rows) for advert_id, rows in groups if advert_id not in processed_before]
    if args.limit is not None:
        groups = groups[: args.limit]

    if not groups:
        print(
            json.dumps(
                {
                    "status": "NO_WORK",
                    "message": "No advert_id rows selected for this run.",
                    "date_from": args.date_from.isoformat(),
                    "date_to": args.date_to.isoformat(),
                    "total_advert_ids_found": total_advert_ids_found,
                    "already_processed_before_run": len(processed_before),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    totals = {
        "date_from": args.date_from.isoformat(),
        "date_to": args.date_to.isoformat(),
        "total_advert_ids_found": total_advert_ids_found,
        "already_processed_before_run": len(processed_before),
        "selected_for_this_run": len(groups),
        "advert_ids_attempted": 0,
        "advert_ids_processed_this_run": 0,
        "campaign_rows_upserted": 0,
        "nm_rows_upserted": 0,
        "stopped_on_429_advert_id": None,
        "stop_error": "",
        "results": [],
    }

    for index, (advert_id, ad_event_rows) in enumerate(groups, start=1):
        nm_ids = _unique_nm_ids(ad_event_rows)
        print(
            json.dumps(
                {
                    "status": "START",
                    "index": index,
                    "advert_id": advert_id,
                    "nm_ids_count": len(nm_ids),
                },
                ensure_ascii=False,
            )
        )
        try:
            result = load_ad_campaign_stats_to_db(
                args.date_from,
                args.date_to,
                nm_ids=nm_ids,
                ad_event_rows=ad_event_rows,
            )
        except Exception as exc:
            error_text = str(exc)
            totals["advert_ids_attempted"] = index
            totals["stop_error"] = error_text
            if "429" in error_text:
                totals["stopped_on_429_advert_id"] = advert_id
            print(
                json.dumps(
                    {
                        "status": "FAIL",
                        "advert_id": advert_id,
                        "error": error_text,
                    },
                    ensure_ascii=False,
                )
            )
            break

        totals["advert_ids_attempted"] = index
        totals["advert_ids_processed_this_run"] += 1
        totals["campaign_rows_upserted"] += int(result.get("campaign_rows_upserted", 0) or 0)
        totals["nm_rows_upserted"] += int(result.get("nm_rows_upserted", 0) or 0)
        totals["results"].append(
            {
                "advert_id": advert_id,
                "campaign_rows_upserted": int(result.get("campaign_rows_upserted", 0) or 0),
                "nm_rows_upserted": int(result.get("nm_rows_upserted", 0) or 0),
                "fullstats_requests": int(result.get("fullstats_requests", 0) or 0),
                "unknown_code_64_rows": int(result.get("unknown_code_64_rows", 0) or 0),
            }
        )
        print(
            json.dumps(
                {
                    "status": "OK",
                    "advert_id": advert_id,
                    "campaign_rows_upserted": int(result.get("campaign_rows_upserted", 0) or 0),
                    "nm_rows_upserted": int(result.get("nm_rows_upserted", 0) or 0),
                },
                ensure_ascii=False,
            )
        )

        if index < len(groups):
            time.sleep(args.sleep_seconds)

    row_stats = _count_rows_and_duplicates(args.date_from, args.date_to)
    totals.update(row_stats)
    totals["remaining_after_run"] = max(
        total_advert_ids_found - len(processed_before) - totals["advert_ids_processed_this_run"],
        0,
    )

    print(json.dumps(totals, ensure_ascii=False, indent=2))
    return 1 if totals["stopped_on_429_advert_id"] or totals["stop_error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
