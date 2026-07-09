from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_DIR = PROJECT_ROOT / "data" / "processed" / "ozon_catalog_audit"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ozon.models import OzonProduct
from src.ozon.probe import probe_ozon_browser_prices


load_dotenv(PROJECT_ROOT / ".env")


def _stock_total(row: dict[str, Any]) -> float:
    stocks = row.get("stocks")
    if not isinstance(stocks, list):
        return 0.0
    total = 0.0
    for item in stocks:
        if not isinstance(item, dict):
            continue
        for key in ("present", "stock", "available", "quantity", "free"):
            value = item.get(key)
            if isinstance(value, (int, float)):
                total += float(value)
                break
    return total


def _load_latest_audit_products(limit: int | None = None, *, stocked_only: bool = False) -> list[dict[str, Any]]:
    audit_files = sorted(DEFAULT_AUDIT_DIR.glob("ozon_catalog_audit_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not audit_files:
        raise FileNotFoundError(f"No audit files found in {DEFAULT_AUDIT_DIR}")
    payload = json.loads(audit_files[0].read_text(encoding="utf-8"))
    products = payload.get("products") or []
    if not isinstance(products, list):
        raise ValueError("Audit file does not contain a products list.")
    rows = [row for row in products if isinstance(row, dict)]
    if stocked_only:
        rows = [row for row in rows if _stock_total(row) > 0]
    return rows[:limit]


def _items_from_args(args: argparse.Namespace) -> list[dict[str, Any]]:
    from src.ozon.config import load_tracked_articles
    tracked_articles = load_tracked_articles()

    raw_items: list[Any] = []
    if args.items_json:
        items = json.loads(args.items_json)
        if not isinstance(items, list):
            raise ValueError("--items-json must contain a JSON list.")
        raw_items = [item for item in items if isinstance(item, (str, dict))]

    elif args.items_file:
        items = json.loads(Path(args.items_file).read_text(encoding="utf-8"))
        if not isinstance(items, list):
            raise ValueError("--items-file must contain a JSON list.")
        raw_items = [item for item in items if isinstance(item, (str, dict))]

    elif args.latest_audit:
        raw_items = _load_latest_audit_products(args.limit, stocked_only=args.stocked_only)

    elif args.offer_id:
        items = []
        for index, offer_id in enumerate(args.offer_id):
            item: dict[str, Any] = {"offer_id": offer_id}
            if index < len(args.product_id) and args.product_id[index] is not None:
                item["product_id"] = args.product_id[index]
            items.append(item)
        raw_items = items
    else:
        # Default source is the CSV tracked articles list
        raw_items = [{"offer_id": art} for art in sorted(tracked_articles)]

    # Filter items so that only tracked articles are checked
    filtered_items: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, str):
            offer_id = item.strip()
            if offer_id in tracked_articles:
                filtered_items.append({"offer_id": offer_id})
        elif isinstance(item, dict):
            offer_id = item.get("offer_id") or item.get("offerId") or item.get("article")
            if offer_id is not None:
                offer_id_str = str(offer_id).strip()
                if offer_id_str in tracked_articles:
                    filtered_items.append(dict(item))

    return filtered_items


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a read-only Ozon browser probe against an open Chrome session.")
    parser.add_argument("--connect-cdp-url", default=os.getenv("OZON_WEB_CONNECT_CDP_URL", "").strip())
    parser.add_argument(
        "--profile-dir",
        default=os.getenv("OZON_WEB_PROFILE_DIR", str(PROJECT_ROOT / "runtime" / "browser_profile" / "ozon")),
    )
    parser.add_argument(
        "--browser-channel",
        default=os.getenv("OZON_WEB_BROWSER_CHANNEL", "chrome").strip() or "chrome",
    )
    parser.add_argument("--web-domain", default=os.getenv("OZON_WEB_DOMAIN", "ozon.ru").strip() or "ozon.ru")
    parser.add_argument("--headless", action="store_true", help="Launch Playwright headless if not using CDP.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit how many products to take from --latest-audit; omit to check all items.",
    )
    parser.add_argument(
        "--latest-audit",
        action="store_true",
        help="Use the latest local ozon_catalog_audit JSON file as the source of products.",
    )
    parser.add_argument(
        "--stocked-only",
        action="store_true",
        help="When used with --latest-audit, keep only products with stock > 0.",
    )
    parser.add_argument(
        "--items-json",
        help='JSON list of items, for example \'[{"offer_id":"ABC","product_id":123}]\'',
    )
    parser.add_argument(
        "--items-file",
        help="Path to a JSON file with a list of items.",
    )
    parser.add_argument(
        "--offer-id",
        action="append",
        default=[],
        help="Offer ID to probe; repeat the flag for multiple items.",
    )
    parser.add_argument(
        "--product-id",
        action="append",
        type=int,
        default=[],
        help="Product ID for the corresponding --offer-id; repeat in the same order.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    items = _items_from_args(args)
    if not items:
        print("No probe items provided. Use --latest-audit, --items-json, --items-file, or --offer-id.")
        return 2

    results = probe_ozon_browser_prices(
        [item if isinstance(item, str) else item for item in items],
        timeout=30,
        headless=args.headless,
        profile_dir=Path(args.profile_dir),
        browser_channel=args.browser_channel,
        web_domain=args.web_domain,
        connect_cdp_url=args.connect_cdp_url,
    )
    output = json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2)
    try:
        print(output)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(output.encode("utf-8"))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

