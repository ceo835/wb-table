#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db.ozon_price_snapshot_loader import collect_and_load_ozon_snapshots
from dotenv import load_dotenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Ozon API + Web price snapshots and load into PostgreSQL.")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser probe in headless mode.")
    parser.add_argument("--no-headless", action="store_false", dest="headless", help="Run browser probe in headful mode.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and process data but skip database write.")
    parser.add_argument("--connect-cdp-url", default=os.getenv("OZON_WEB_CONNECT_CDP_URL", "").strip(), help="CDP URL to connect to an existing browser instance.")
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT_DIR / ".env")
    args = parse_args()

    print("Starting Ozon API + Web price snapshot collection...")
    result = collect_and_load_ozon_snapshots(
        headless=args.headless,
        connect_cdp_url=args.connect_cdp_url,
        dry_run=args.dry_run,
    )

    if result.get("status") != "success":
        print(f"[ERR] Load failed: {result.get('error')}", file=sys.stderr)
        return 1

    items = result.get("items", [])
    saved_count = result.get("saved_count", 0)

    # Print summary
    print("\nLoad Summary:")
    print("-" * 115)
    print(f"{'offer_id':<18} | {'price_api':<9} | {'price_web':<9} | {'other_web':<9} | {'reg_web':<8} | {'spp_rub':<8} | {'spp_pct':<8} | {'stock':<6} | {'status_web':<10}")
    print("-" * 115)
    
    for r in items:
        p_api = f"{r['seller_price_api']:.0f}" if r['seller_price_api'] is not None else "None"
        p_web = f"{r['buyer_visible_price_web']:.0f}" if r['buyer_visible_price_web'] is not None else "None"
        other_web = f"{r['other_bank_price_web']:.0f}" if r['other_bank_price_web'] is not None else "None"
        reg_web = f"{r['buyer_regular_price_web']:.0f}" if r['buyer_regular_price_web'] is not None else "None"
        spp_rub = f"{r['spp_rub']:.0f}" if r['spp_rub'] is not None else "None"
        spp_pct = f"{r['spp_percent']:.1f}%" if r['spp_percent'] is not None else "None"
        print(f"{r['offer_id']:<18} | {p_api:<9} | {p_web:<9} | {other_web:<9} | {reg_web:<8} | {spp_rub:<8} | {spp_pct:<8} | {r['stock']:<6.0f} | {r['status_web']:<10}")
    
    print("-" * 115)
    print(f"Successfully processed {len(items)} items. Saved/Upserted rows count: {saved_count}")
    if args.dry_run:
        print("[Dry Run Mode] Database write skipped.")

    # Diagnostic Summary Calculation
    from src.ozon.config import load_tracked_articles
    tracked_articles = sorted(list(load_tracked_articles()))
    tracked_count = len(tracked_articles)
    
    items_map = {r["offer_id"]: r for r in items}
    api_found_offer_ids = [
        oid for oid, r in items_map.items()
        if r.get("product_id") is not None or r.get("sku") is not None
    ]
    api_found_count = len(api_found_offer_ids)
    
    web_checked_offer_ids = [
        oid for oid, r in items_map.items()
        if r.get("status_web") != "parse_error"
    ]
    web_checked_count = len(web_checked_offer_ids)
    
    db_saved_count = saved_count if not args.dry_run else 0
    missing_from_api = [oid for oid in tracked_articles if oid not in api_found_offer_ids]
    missing_from_web = [oid for oid in tracked_articles if oid not in web_checked_offer_ids]
    saved_offer_ids = sorted(list(items_map.keys())) if db_saved_count > 0 else []

    print("\nDiagnostic Summary:")
    print("-" * 115)
    print(f"tracked_count     : {tracked_count}")
    print(f"api_found_count   : {api_found_count}")
    print(f"web_checked_count : {web_checked_count}")
    print(f"db_saved_count    : {db_saved_count}")
    print(f"missing_from_api  : {missing_from_api}")
    print(f"missing_from_web  : {missing_from_web}")
    print(f"saved_offer_ids   : {saved_offer_ids}")
    print("-" * 115)
    
    # Blocked diagnostics list
    blocked_items = [r for r in items if r.get("status_web") == "blocked"]
    if blocked_items:
        print("\nBlocked Ozon Items Diagnostics:")
        print("-" * 115)
        print(f"{'offer_id':<18} | {'sku':<10} | {'stock':<5} | {'page_type':<13} | {'error':<8} | {'title':<30}")
        print("-" * 115)
        for b in blocked_items:
            raw = b.get("raw_json", {})
            web_res = raw.get("web_result", {})
            page_title = web_res.get("page_title") or "None"
            page_type = web_res.get("page_type") or "None"
            err = web_res.get("error") or "None"
            
            # Format requested URL based on sku
            req_url = f"https://www.ozon.ru/product/{b['sku']}/" if b.get('sku') else "None"
            
            print(f"{b['offer_id']:<18} | {str(b['sku']):<10} | {b['stock']:<5.0f} | {page_type:<13} | {err:<8} | {page_title[:30]:<30}")
            print(f"  > Requested URL: {req_url}")
            print(f"  > Final URL    : {b.get('final_url') or 'None'}")
        print("-" * 115)
    print()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"Exception: {e}", file=sys.stderr)
        sys.exit(1)
