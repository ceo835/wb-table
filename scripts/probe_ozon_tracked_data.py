#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ozon.config import load_tracked_articles
from src.ozon.models import OzonProduct
from src.ozon.probe import probe_ozon_browser_prices
from scripts.probe_ozon_catalog import OzonApiClient, get_ozon_credentials

OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "ozon_catalog_audit"


def fetch_api_details(client: OzonApiClient, offer_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetches details from Ozon Seller API v3 info, v4 stocks, and v5 prices.

    Returns a dict mapping offer_id to merged API data.
    """
    if not offer_ids:
        return {}

    merged_data: dict[str, dict[str, Any]] = {
        oid: {
            "offer_id": oid,
            "product_id": None,
            "sku": None,
            "name": "",
            "status_api": "unknown",
            "stock": 0.0,
            "seller_price_api": None,
        }
        for oid in offer_ids
    }

    # 1. Fetch info (/v3/product/info/list)
    info_payload = {"offer_id": offer_ids}
    status, data, error = client.post("/v3/product/info/list", info_payload)
    if status == 200 and data:
        result = data.get("result", data)
        items = (result.get("products") or result.get("items") or []) if isinstance(result, dict) else []
        for item in items:
            oid = item.get("offer_id")
            if oid in merged_data:
                merged_data[oid]["product_id"] = item.get("id") or item.get("product_id")
                merged_data[oid]["sku"] = item.get("sku") or item.get("fbo_sku") or item.get("fbs_sku")
                merged_data[oid]["name"] = item.get("name", "")
                statuses = item.get("statuses")
                status_obj = item.get("status")
                if isinstance(statuses, dict) and statuses:
                    merged_data[oid]["status_api"] = statuses.get("status_name") or statuses.get("status") or "unknown"
                elif isinstance(status_obj, dict) and status_obj:
                    merged_data[oid]["status_api"] = status_obj.get("state_name") or status_obj.get("state") or "unknown"
                else:
                    merged_data[oid]["status_api"] = str(statuses or status_obj or "unknown")

    # 2. Fetch stocks (/v4/product/info/stocks)
    stocks_payload = {
        "filter": {
            "offer_id": offer_ids,
            "visibility": "ALL",
        },
        "limit": 100,
    }
    status, data, error = client.post("/v4/product/info/stocks", stocks_payload)
    if status == 200 and data:
        result = data.get("result", data)
        items = result.get("items", []) if isinstance(result, dict) else []
        for item in items:
            oid = item.get("offer_id")
            if oid in merged_data:
                total_stock = 0.0
                stocks_list = item.get("stocks", [])
                for stock_entry in stocks_list:
                    present = stock_entry.get("present") or stock_entry.get("stock") or stock_entry.get("quantity") or 0
                    total_stock += float(present)
                merged_data[oid]["stock"] = total_stock

    # 3. Fetch prices (/v5/product/info/prices)
    prices_payload = {
        "filter": {
            "offer_id": offer_ids,
            "visibility": "ALL",
        },
        "limit": 100,
    }
    status, data, error = client.post("/v5/product/info/prices", prices_payload)
    if status == 200 and data:
        result = data.get("result", data)
        items = result.get("items", []) if isinstance(result, dict) else []
        for item in items:
            oid = item.get("offer_id")
            if oid in merged_data:
                price_obj = item.get("price", {})
                if isinstance(price_obj, dict):
                    seller_price = price_obj.get("price")
                    if seller_price is not None:
                        merged_data[oid]["seller_price_api"] = float(seller_price)

    return merged_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run combined Ozon API and browser probe audit on tracked articles.")
    parser.add_argument("--headless", action="store_true", help="Run browser probe in headless mode.")
    parser.add_argument("--connect-cdp-url", default=os.getenv("OZON_WEB_CONNECT_CDP_URL", "").strip())
    return parser.parse_args()


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    args = parse_args()

    client_id, api_key = get_ozon_credentials()
    if not client_id or not api_key:
        print("[ERR] Ozon Seller API credentials (OZON_CLIENT_ID, OZON_API_KEY/TOKEN) are missing.")
        return 1

    # Load tracked articles
    tracked_articles = sorted(list(load_tracked_articles()))
    if not tracked_articles:
        print("[WARN] No tracked articles found in data/config/ozon_tracked_articles.csv")
        return 0

    print(f"Loaded {len(tracked_articles)} tracked articles: {tracked_articles}")

    # 1. Fetch from Seller API
    print("[1/3] Fetching Ozon Seller API data (info, stocks, prices)...")
    client = OzonApiClient(client_id, api_key)
    api_records = fetch_api_details(client, tracked_articles)

    # 2. Run browser probe
    print("[2/3] Running Ozon browser price probe...")
    ozon_products: list[OzonProduct] = []
    for oid in tracked_articles:
        rec = api_records[oid]
        ozon_products.append(
            OzonProduct(
                offer_id=rec["offer_id"],
                product_id=rec["product_id"],
                sku=rec["sku"],
                name=rec["name"],
                status=rec["status_api"],
                raw=rec,
            )
        )

    web_results = probe_ozon_browser_prices(
        ozon_products,
        timeout=30,
        headless=args.headless,
        connect_cdp_url=args.connect_cdp_url,
    )

    # 3. Merge API & Web data
    print("[3/3] Merging data and generating reports...")
    unified_report: list[dict[str, Any]] = []

    for result in web_results:
        oid = result.offer_id
        rec = api_records[oid]

        buyer_price = result.buyer_visible_price
        if buyer_price is not None and buyer_price <= 1.01:
            print(f"[WARN] Suspiciously low price ({buyer_price}₽) for {oid}.")
            real_candidates = [c for c in result.price_candidates if c.get("role") == "current" and c.get("value", 0) > 1.01]
            if real_candidates:
                best_cand = max(real_candidates, key=lambda c: (int(c.get("score", 0)), float(c.get("value", 0))))
                buyer_price = float(best_cand["value"])
                print(f"       Replaced with candidate: {buyer_price}₽ (source: {best_cand.get('source')})")

        row = {
            "offer_id": oid,
            "product_id": rec["product_id"],
            "sku": rec["sku"],
            "seller_price_api": rec["seller_price_api"],
            "buyer_visible_price_web": buyer_price,
            "old_price_web": result.old_price or result.other_bank_price,
            "stock": rec["stock"],
            "status_api": rec["status_api"],
            "status_web": result.status,
            "error": result.error,
        }
        unified_report.append(row)

    # Print summary
    print("\nCombined Ozon Tracked Articles Report:")
    print("-" * 120)
    print(f"{'offer_id':<18} | {'prod_id':<10} | {'sku':<10} | {'price_api':<9} | {'price_web':<9} | {'old_web':<8} | {'stock':<6} | {'status_api':<10} | {'status_web':<10}")
    print("-" * 120)
    for r in unified_report:
        p_api = f"{r['seller_price_api']:.0f}" if r['seller_price_api'] is not None else "None"
        p_web = f"{r['buyer_visible_price_web']:.0f}" if r['buyer_visible_price_web'] is not None else "None"
        old_web = f"{r['old_price_web']:.0f}" if r['old_price_web'] is not None else "None"
        print(f"{r['offer_id']:<18} | {str(r['product_id'] or ''):<10} | {str(r['sku'] or ''):<10} | {p_api:<9} | {p_web:<9} | {old_web:<8} | {r['stock']:<6.0f} | {r['status_api']:<10} | {r['status_web']:<10}")
    print("-" * 120)

    # Write files
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUTPUT_DIR / f"ozon_tracked_data_report_{timestamp}.json"
    csv_path = OUTPUT_DIR / f"ozon_tracked_data_report_{timestamp}.csv"

    # Save JSON
    json_path.write_text(json.dumps(unified_report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Save CSV
    fieldnames = [
        "offer_id",
        "product_id",
        "sku",
        "seller_price_api",
        "buyer_visible_price_web",
        "old_price_web",
        "stock",
        "status_api",
        "status_web",
        "error",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in unified_report:
            writer.writerow(r)

    # Add terminal fallback encoding support if printing issues arise
    output_str = f"\nSaved reports to:\n  JSON: {json_path}\n  CSV:  {csv_path}\n"
    try:
        print(output_str)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(output_str.encode("utf-8"))
        print()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"Exception: {e}")
        sys.exit(1)
