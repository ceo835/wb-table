#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db.session import session_scope
from src.db.models import ExternalContextMetric
from src.services.external_context.sources.search_demand import YandexCloudWordstatAdapter
from src.services.external_context.category_config import get_active_categories

def parse_date_arg(val: str | None, default: date) -> date:
    if not val:
        return default
    return date.fromisoformat(val)

def main() -> int:
    parser = argparse.ArgumentParser(description="Load Yandex Cloud Search API Wordstat metrics to DB.")
    parser.add_argument("--period-start", type=str, default=None, help="Period start ISO date (YYYY-MM-DD)")
    parser.add_argument("--period-end", type=str, default=None, help="Period end ISO date (YYYY-MM-DD)")
    parser.add_argument("--category", type=str, default=None, help="Category code filter (e.g. womens_tshirts)")
    parser.add_argument("--query", type=str, default=None, help="Specific search query filter")
    parser.add_argument("--region", type=str, default=None, help="Region ID filter")
    parser.add_argument("--dry-run", action="store_true", help="Run without committing to database.")
    args = parser.parse_args()

    period_start = parse_date_arg(args.period_start, date(2026, 7, 13))
    period_end = parse_date_arg(args.period_end, date(2026, 7, 19))

    print(f"Starting Yandex Cloud Wordstat search demand loader.")
    print(f"  Period: {period_start} to {period_end}")
    print(f"  Category filter: {args.category or 'ALL'}")
    print(f"  Query filter: {args.query or 'ALL'}")
    print(f"  Region: {args.region or 'ALL'}")
    print(f"  Dry-run: {args.dry_run}")

    api_key = os.getenv("YANDEX_SEARCH_API_KEY")
    folder_id = os.getenv("YANDEX_CLOUD_FOLDER_ID")

    adapter = YandexCloudWordstatAdapter(api_key, folder_id)
    all_categories = get_active_categories()
    
    if args.category:
        categories = [c for c in all_categories if c["category_code"] == args.category]
    else:
        categories = all_categories

    stats = {
        "requested": 0,
        "received": 0,
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "unavailable": 0,
        "errors": 0
    }

    if not api_key or not folder_id:
        print("WARNING: YANDEX_SEARCH_API_KEY or YANDEX_CLOUD_FOLDER_ID credentials are not configured.")
        with session_scope() as session:
            for cat in categories:
                code = f"search_demand_{cat['category_code']}"
                stats["requested"] += 1
                existing = session.query(ExternalContextMetric).filter_by(
                    source="yandex_cloud_wordstat",
                    metric_code=code,
                    period_start=period_start,
                    period_end=period_end,
                    category=cat["category_code"]
                ).first()

                if existing:
                    if existing.data_status != "unavailable":
                        existing.data_status = "unavailable"
                        existing.updated_at = datetime.now()
                        stats["updated"] += 1
                    else:
                        stats["unchanged"] += 1
                else:
                    new_metric = ExternalContextMetric(
                        source="yandex_cloud_wordstat",
                        metric_code=code,
                        metric_name=f"Поисковый спрос: {cat['category_title']}",
                        period_start=period_start,
                        period_end=period_end,
                        region=args.region,
                        category=cat["category_code"],
                        unit="searches",
                        data_status="unavailable",
                        source_reference="yandex_cloud_wordstat"
                    )
                    session.add(new_metric)
                    stats["inserted"] += 1
                stats["unavailable"] += 1

            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        print(f"Loader completed (credentials missing fallback). Stats: {stats}")
        return 0

    with session_scope() as session:
        for cat in categories:
            queries = [args.query] if args.query else cat["search_queries"]
            stats["requested"] += len(queries)

            print(f"Fetching demand for category '{cat['category_code']}' with {len(queries)} query/queries...")
            res = adapter.fetch_search_demand(
                period_start=period_start,
                period_end=period_end,
                queries=queries,
                category=cat["category_code"],
                region=args.region
            )

            data_list = res.get("data", [])
            stats["received"] += len(data_list)

            if res["status"] != "ok" or not data_list:
                stats["errors"] += len(queries)
                # Store aggregated error status for category
                code = f"search_demand_{cat['category_code']}"
                existing = session.query(ExternalContextMetric).filter_by(
                    source="yandex_cloud_wordstat",
                    metric_code=code,
                    period_start=period_start,
                    period_end=period_end,
                    category=cat["category_code"]
                ).first()
                if existing:
                    if existing.data_status != "error":
                        existing.data_status = "error"
                        existing.updated_at = datetime.now()
                        stats["updated"] += 1
                    else:
                        stats["unchanged"] += 1
                else:
                    new_metric = ExternalContextMetric(
                        source="yandex_cloud_wordstat",
                        metric_code=code,
                        metric_name=f"Поисковый спрос: {cat['category_title']}",
                        period_start=period_start,
                        period_end=period_end,
                        region=args.region,
                        category=cat["category_code"],
                        unit="searches",
                        data_status="error",
                        source_reference="yandex_cloud_wordstat"
                    )
                    session.add(new_metric)
                    stats["inserted"] += 1
                continue

            # Process successfully received records
            # Aggregate queries at category level
            tot_value = sum(Decimal(str(item["value"])) for item in data_list)
            tot_prev = sum(Decimal(str(item["previous_value"])) for item in data_list)
            change_pct = Decimal("0")
            if tot_prev > Decimal("0"):
                change_pct = ((tot_value - tot_prev) / tot_prev * Decimal("100")).quantize(Decimal("0.1"))

            code = f"search_demand_{cat['category_code']}"
            existing = session.query(ExternalContextMetric).filter_by(
                source="yandex_cloud_wordstat",
                metric_code=code,
                period_start=period_start,
                period_end=period_end,
                category=cat["category_code"]
            ).first()

            if existing:
                changed = (
                    existing.value != tot_value or
                    existing.previous_value != tot_prev or
                    existing.change_pct != change_pct or
                    existing.data_status != "ok"
                )
                if changed:
                    existing.value = tot_value
                    existing.previous_value = tot_prev
                    existing.change_pct = change_pct
                    existing.data_status = "ok"
                    existing.updated_at = datetime.now()
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1
            else:
                new_metric = ExternalContextMetric(
                    source="yandex_cloud_wordstat",
                    metric_code=code,
                    metric_name=f"Поисковый спрос: {cat['category_title']}",
                    period_start=period_start,
                    period_end=period_end,
                    value=tot_value,
                    previous_value=tot_prev,
                    change_pct=change_pct,
                    region=args.region,
                    category=cat["category_code"],
                    unit="searches",
                    data_status="ok",
                    source_reference="yandex_cloud_wordstat"
                )
                session.add(new_metric)
                stats["inserted"] += 1

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    print(f"Search demand loader completed. Stats: {stats}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
