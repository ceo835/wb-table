from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from src.db.models import FactOzonPriceSnapshot
from src.db.session import session_scope, upsert_rows
from src.ozon.config import load_tracked_articles
from src.ozon.models import OzonProduct
from src.ozon.probe import probe_ozon_browser_prices
from scripts.probe_ozon_catalog import OzonApiClient, get_ozon_credentials
from scripts.probe_ozon_tracked_data import fetch_api_details
from src.utils.logger import get_logger

logger = get_logger("ozon_price_snapshot_loader")

SNAPSHOT_CONFLICT_COLUMNS = ("snapshot_at", "offer_id")


def _to_decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def prepare_fact_ozon_price_snapshot_upsert_rows(
    snapshot_at: datetime,
    items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Maps raw combined Ozon items to DB model fields."""
    prepared: list[dict[str, Any]] = []
    snapshot_date = snapshot_at.date()

    for item in items:
        # Resolve prices
        seller_price = _to_decimal_or_none(item.get("seller_price_api"))
        buyer_visible = _to_decimal_or_none(item.get("buyer_visible_price_web"))
        old_price = _to_decimal_or_none(item.get("old_price_web"))
        other_bank = _to_decimal_or_none(item.get("other_bank_price_web"))
        buyer_regular = _to_decimal_or_none(item.get("buyer_regular_price_web"))
        spp_rub = _to_decimal_or_none(item.get("spp_rub"))
        spp_percent = _to_decimal_or_none(item.get("spp_percent"))

        # Raw JSON payload container
        raw_payload = item.get("raw_json") or dict(item)

        prepared_row = {
            "snapshot_at": snapshot_at,
            "snapshot_date": snapshot_date,
            "offer_id": str(item["offer_id"]),
            "product_id": item.get("product_id"),
            "sku": item.get("sku"),
            "name": item.get("name"),
            "seller_status": item.get("status_api") or "unknown",
            "stock_total": _to_decimal_or_none(item.get("stock")),
            "seller_price_api": seller_price,
            "buyer_visible_price_web": buyer_visible,
            "other_bank_price_web": other_bank,
            "old_price_web": old_price,
            "buyer_regular_price_web": buyer_regular,
            "spp_rub": spp_rub,
            "spp_percent": spp_percent,
            "final_url": item.get("final_url"),
            "status_api": item.get("status_api") or "unknown",
            "status_web": item.get("status_web") or "unknown",
            "error": item.get("error"),
            "raw_json": raw_payload,
        }
        prepared.append(prepared_row)

    return prepared


def save_ozon_price_snapshots(
    session: Session,
    snapshot_at: datetime,
    items: Sequence[Mapping[str, Any]],
) -> int:
    """Saves price snapshots to PostgreSQL database using upsert."""
    prepared_rows = prepare_fact_ozon_price_snapshot_upsert_rows(snapshot_at, items)
    if not prepared_rows:
        return 0

    rowcount = upsert_rows(
        session,
        FactOzonPriceSnapshot,
        prepared_rows,
        conflict_columns=list(SNAPSHOT_CONFLICT_COLUMNS),
    )
    return rowcount if rowcount >= 0 else len(prepared_rows)


def collect_and_load_ozon_snapshots(
    headless: bool = True,
    connect_cdp_url: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Collects Ozon metrics from API + web probe and saves them to PostgreSQL."""
    logger.info("Initializing Ozon price snapshot load...")

    client_id, api_key = get_ozon_credentials()
    if not client_id or not api_key:
        err_msg = "Ozon Seller API credentials missing (OZON_CLIENT_ID / OZON_API_KEY)"
        logger.error(err_msg)
        return {"status": "failed", "error": err_msg}

    # 1. Load tracked articles
    tracked_articles = sorted(list(load_tracked_articles()))
    if not tracked_articles:
        logger.warning("No tracked articles found in data/config/ozon_tracked_articles.csv")
        return {"status": "success", "saved_count": 0, "summary": "No articles to track"}

    logger.info(f"Loaded {len(tracked_articles)} articles to track.")

    # 2. Fetch Ozon API details
    logger.info("Fetching Ozon Seller API details...")
    client = OzonApiClient(client_id, api_key)
    api_records = fetch_api_details(client, tracked_articles)

    # 3. Trigger Browser check
    logger.info("Triggering Ozon web browser probe...")
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
        headless=headless,
        connect_cdp_url=connect_cdp_url,
    )

    # 4. Merge API & Web data
    logger.info("Merging API and Web details...")
    unified_items: list[dict[str, Any]] = []
    snapshot_at = datetime.now(timezone.utc)

    for result in web_results:
        oid = result.offer_id
        rec = api_records[oid]

        buyer_price = result.buyer_visible_price
        # 1₽ Edge Case
        if buyer_price is not None and buyer_price <= 1.01:
            logger.warning(f"Suspiciously low price ({buyer_price}₽) for {oid}, reviewing candidates...")
            real_candidates = [c for c in result.price_candidates if c.get("role") == "current" and c.get("value", 0) > 1.01]
            if real_candidates:
                best_cand = max(real_candidates, key=lambda c: (int(c.get("score", 0)), float(c.get("value", 0))))
                buyer_price = float(best_cand["value"])
                logger.info(f"Replaced with candidate: {buyer_price}₽ ({best_cand.get('source')})")

        # Capture other_bank_price and old_price from web probe result
        other_bank = result.other_bank_price
        old_price = result.old_price

        # Determine buyer_regular_price_web
        buyer_regular = None
        if other_bank is not None:
            buyer_regular = other_bank
        elif buyer_price is not None and buyer_price > 1.01:
            buyer_regular = buyer_price

        # Calculate SPP
        spp_rub = None
        spp_percent = None
        seller_price = rec.get("seller_price_api")
        if seller_price is not None and seller_price > 0 and buyer_regular is not None:
            spp_rub = float(seller_price) - float(buyer_regular)
            spp_percent = (spp_rub / float(seller_price)) * 100

        # Full web probe debug info package as raw_json
        raw_json = {
            "api_record": rec,
            "web_result": {
                "offer_id": result.offer_id,
                "status": result.status,
                "error": result.error,
                "buyer_visible_price": result.buyer_visible_price,
                "other_bank_price": result.other_bank_price,
                "old_price": result.old_price,
                "buyer_regular_price_web": buyer_regular,
                "spp_rub": spp_rub,
                "spp_percent": spp_percent,
                "final_url": result.final_url,
                "price_candidates": result.price_candidates,
            }
        }

        row = {
            "offer_id": oid,
            "product_id": rec["product_id"],
            "sku": rec["sku"],
            "name": rec["name"],
            "seller_price_api": rec["seller_price_api"],
            "buyer_visible_price_web": buyer_price,
            "other_bank_price_web": other_bank,
            "old_price_web": old_price,
            "buyer_regular_price_web": buyer_regular,
            "spp_rub": spp_rub,
            "spp_percent": spp_percent,
            "stock": rec["stock"],
            "status_api": rec["status_api"],
            "status_web": result.status,
            "error": result.error,
            "final_url": result.final_url,
            "raw_json": raw_json,
        }
        unified_items.append(row)

    # 5. DB Persistance
    saved_count = 0
    if not dry_run:
        logger.info(f"Writing {len(unified_items)} snapshots to Postgres...")
        with session_scope() as session:
            saved_count = save_ozon_price_snapshots(session, snapshot_at, unified_items)
        logger.info(f"Successfully saved {saved_count} snapshot records to DB.")
    else:
        logger.info("[Dry Run] Skipped DB persistence step.")

    return {
        "status": "success",
        "snapshot_at": snapshot_at,
        "saved_count": saved_count,
        "items": unified_items,
        "dry_run": dry_run,
    }
