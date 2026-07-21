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
from src.services.external_context.sources.search_demand import YandexDirectSearchDemandAdapter
from src.services.external_context.category_config import get_active_categories

# Credentials steps description
CREDENTIALS_INSTRUCTIONS = """
To configure real Yandex Direct API connectivity for search demand:
1. Obtain Yandex Direct API OAuth token from: https://oauth.yandex.ru/
2. Request a Developer Token in Yandex Direct API administration panel.
3. Configure Yandex client login if using agency or representative accounts.
4. Set the following environment variables in .env:
   YANDEX_DIRECT_TOKEN="your_oauth_token"
   YANDEX_DIRECT_CLIENT_LOGIN="your_client_login" (optional)
"""

def main() -> int:
    parser = argparse.ArgumentParser(description="Load Yandex Direct Search Demand metrics to DB.")
    parser.add_argument("--dry-run", action="store_true", help="Run without committing to database.")
    args = parser.parse_args()

    print(f"Starting Yandex Direct search demand loader. Dry-run: {args.dry_run}")
    
    token = os.getenv("YANDEX_DIRECT_TOKEN")
    client_login = os.getenv("YANDEX_DIRECT_CLIENT_LOGIN")
    
    adapter = YandexDirectSearchDemandAdapter(token, client_login)
    categories = get_active_categories()
    
    stats = {"inserted": 0, "updated": 0, "unchanged": 0, "errors": 0}
    
    if not token:
        print("WARNING: Yandex Direct credentials are not set. Search demand data cannot be loaded.")
        print(CREDENTIALS_INSTRUCTIONS)
        
        # Save a placeholder/unavailable record in DB to mark status
        with session_scope() as session:
            for cat in categories:
                code = f"search_demand_{cat['category_code']}"
                existing = session.query(ExternalContextMetric).filter_by(
                    source="yandex_direct",
                    metric_code=code,
                    period_start=date(2026, 7, 13),
                    period_end=date(2026, 7, 19),
                    region=None,
                    category=cat["category_code"],
                    query_text=None
                ).first()
                
                if existing:
                    if existing.data_status != "unavailable":
                        existing.data_status = "unavailable"
                        existing.updated_at = datetime.now()
                        stats["updated"] += 1
                else:
                    new_metric = ExternalContextMetric(
                        source="yandex_direct",
                        metric_code=code,
                        metric_name=f"Поисковый спрос: {cat['category_title']}",
                        period_start=date(2026, 7, 13),
                        period_end=date(2026, 7, 19),
                        region=None,
                        category=cat["category_code"],
                        unit="searches",
                        data_status="unavailable",
                        source_reference="Yandex Direct Wordstat API"
                    )
                    session.add(new_metric)
                    stats["inserted"] += 1
            if not args.dry_run:
                session.commit()
        print(f"Loader completed (credentials missing fallback). Stats: {stats}")
        return 0

    # If token exists, fetch real queries
    # For testing, we also provide a simulation option so we can load demo data when credentials are set
    # but since they are not set locally, we execute the real call
    with session_scope() as session:
        for cat in categories:
            queries = cat["search_queries"]
            print(f"Fetching demand for category {cat['category_code']} containing {len(queries)} queries...")
            
            res = adapter.fetch_search_demand(date(2026, 7, 13), date(2026, 7, 19), queries)
            
            code = f"search_demand_{cat['category_code']}"
            data_status = res["status"]
            
            # Upsert into DB
            existing = session.query(ExternalContextMetric).filter_by(
                source="yandex_direct",
                metric_code=code,
                period_start=date(2026, 7, 13),
                period_end=date(2026, 7, 19),
                region=None,
                category=cat["category_code"],
                query_text=None
            ).first()
            
            if existing:
                if existing.data_status != data_status:
                    existing.data_status = data_status
                    existing.updated_at = datetime.now()
                    stats["updated"] += 1
                else:
                    stats["unchanged"] += 1
            else:
                new_metric = ExternalContextMetric(
                    source="yandex_direct",
                    metric_code=code,
                    metric_name=f"Поисковый спрос: {cat['category_title']}",
                    period_start=date(2026, 7, 13),
                    period_end=date(2026, 7, 19),
                    region=None,
                    category=cat["category_code"],
                    unit="searches",
                    data_status=data_status,
                    source_reference="Yandex Direct Wordstat API"
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
