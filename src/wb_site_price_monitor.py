from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit

from src.config.settings import settings
from src.tracked_products import TRACKED_PRODUCTS_PATH, load_tracked_products


WB_PRODUCT_URL_TEMPLATE = "https://www.wildberries.ru/catalog/{nm_id}/detail.aspx"
DEFAULT_TIMEOUT_MS = 30_000
RUB_CURRENCY = "RUB"
PRICE_QUANT = Decimal("0.01")

_PRICE_TEXT_RE = re.compile(r"(\d[\d\s]*(?:[.,]\d{1,2})?)")
_SALE_PRICE_U_RE = re.compile(r'"salePriceU"\s*:\s*(\d+)', re.IGNORECASE)
_PRICE_U_RE = re.compile(r'"priceU"\s*:\s*(\d+)', re.IGNORECASE)
_NO_STOCK_RE = re.compile(r"нет в наличии|скоро закончится|товар закончился", re.IGNORECASE)
_BLOCKED_RE = re.compile(r"captcha|доступ ограничен|access denied|forbidden", re.IGNORECASE)


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_wb_product_url(nm_id: int) -> str:
    return WB_PRODUCT_URL_TEMPLATE.format(nm_id=int(nm_id))


def build_playwright_proxy_config(proxy_url: str | None) -> dict[str, str] | None:
    if not proxy_url:
        return None
    trimmed = str(proxy_url).strip()
    if not trimmed:
        return None
    if "://" not in trimmed:
        return {"server": trimmed}

    parsed = urlsplit(trimmed)
    server = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        server = f"{server}:{parsed.port}"
    proxy: dict[str, str] = {"server": server}
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return proxy


def build_browser_launch_kwargs(*, headless: bool, proxy_url: str | None) -> dict[str, Any]:
    launch_kwargs: dict[str, Any] = {"headless": bool(headless)}
    proxy_config = build_playwright_proxy_config(proxy_url)
    if proxy_config:
        launch_kwargs["proxy"] = proxy_config
    return launch_kwargs


def load_price_monitor_targets(
    *,
    tracked_path: Path | None = None,
    nm_ids: Sequence[int] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    tracked_df = load_tracked_products(tracked_path or TRACKED_PRODUCTS_PATH)
    if tracked_df.empty:
        return []

    filtered = tracked_df.loc[tracked_df["is_tracked"]].copy()
    if nm_ids:
        requested = {int(nm_id) for nm_id in nm_ids}
        filtered = filtered[filtered["nm_id"].isin(requested)].copy()
    if limit is not None and limit > 0:
        filtered = filtered.head(limit).copy()

    return [
        {
            "nm_id": int(row["nm_id"]),
            "item_label": row.get("tracked_label") or row.get("item_label") or None,
            "lifecycle_status": row.get("lifecycle_status") or None,
            "product_url": build_wb_product_url(int(row["nm_id"])),
        }
        for _, row in filtered.iterrows()
    ]


def _quantize_price(value: Decimal) -> Decimal:
    return value.quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)


def parse_price_text(value: str | None) -> Decimal | None:
    if value is None:
        return None
    match = _PRICE_TEXT_RE.search(str(value))
    if not match:
        return None
    normalized = match.group(1).replace(" ", "").replace(",", ".")
    try:
        return _quantize_price(Decimal(normalized))
    except InvalidOperation:
        return None


def _parse_minor_units(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return _quantize_price(Decimal(str(value)) / Decimal("100"))
    except InvalidOperation:
        return None


def _extract_json_ld_price(html: str) -> tuple[Decimal | None, str | None]:
    matches = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for raw_script in matches:
        try:
            payload = json.loads(raw_script.strip())
        except Exception:
            continue
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                offers = item.get("offers")
                if isinstance(offers, dict):
                    price_value = offers.get("price")
                    price = parse_price_text(str(price_value)) if price_value is not None else None
                    if price is not None:
                        return price, str(price_value)
                stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
            elif isinstance(item, list):
                stack.extend(item)
    return None, None


def extract_price_from_html(html: str) -> tuple[Decimal | None, str | None, str | None]:
    ld_price, ld_raw = _extract_json_ld_price(html)
    if ld_price is not None:
        return ld_price, ld_raw, "json_ld"

    sale_price_match = _SALE_PRICE_U_RE.search(html)
    if sale_price_match:
        price = _parse_minor_units(sale_price_match.group(1))
        if price is not None:
            return price, sale_price_match.group(1), "salePriceU"

    price_u_match = _PRICE_U_RE.search(html)
    if price_u_match:
        price = _parse_minor_units(price_u_match.group(1))
        if price is not None:
            return price, price_u_match.group(1), "priceU"

    return None, None, None


def derive_availability_status(*, html: str, price: Decimal | None) -> str:
    if price is not None:
        return "available"
    if _NO_STOCK_RE.search(html):
        return "unavailable"
    return "unknown"


def build_failure_snapshot_row(
    target: dict[str, Any],
    *,
    snapshot_at: datetime,
    fetch_status: str,
    error: str,
    proxy_used: bool,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "snapshot_at": snapshot_at.isoformat(),
        "snapshot_date": snapshot_at.date().isoformat(),
        "nm_id": int(target["nm_id"]),
        "item_label": target.get("item_label"),
        "lifecycle_status": target.get("lifecycle_status"),
        "product_url": target.get("product_url") or build_wb_product_url(int(target["nm_id"])),
        "buyer_visible_price": None,
        "currency": None,
        "price_text_raw": None,
        "availability_status": "unknown",
        "fetch_status": fetch_status,
        "error": error,
        "proxy_used": proxy_used,
        "raw_payload": raw_payload or {},
    }


def fetch_wb_site_price_snapshots_with_playwright(
    targets: Sequence[dict[str, Any]],
    *,
    headless: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    proxy_url: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not targets:
        return [], {
            "success": True,
            "proxy_enabled": bool(proxy_url),
            "region_detected": None,
            "fetch_status_counts": {},
        }

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Playwright is not installed for WB site price monitor") from exc

    results: list[dict[str, Any]] = []
    fetch_status_counts: dict[str, int] = {}
    region_detected: str | None = None
    proxy_used = bool(proxy_url)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**build_browser_launch_kwargs(headless=headless, proxy_url=proxy_url))
        context = browser.new_context(locale="ru-RU", timezone_id="Europe/Moscow")
        page = context.new_page()
        try:
            for target in targets:
                snapshot_at = utc_now()
                url = target.get("product_url") or build_wb_product_url(int(target["nm_id"]))
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(1_200)
                    title = page.title()
                    html = page.content()
                    current_url = page.url
                    price, raw_price_text, price_source = extract_price_from_html(html)
                    if region_detected is None:
                        region_detected = None
                        try:
                            region_detected = page.locator("[data-link*='address']").first.text_content(timeout=1_000)
                        except Exception:
                            region_detected = None

                    blocked = bool(_BLOCKED_RE.search(" ".join(filter(None, [title, current_url, html[:4000]]))))
                    availability_status = derive_availability_status(html=html, price=price)
                    if blocked and price is None:
                        row = build_failure_snapshot_row(
                            target,
                            snapshot_at=snapshot_at,
                            fetch_status="blocked",
                            error="wb_site_blocked_or_captcha",
                            proxy_used=proxy_used,
                            raw_payload={
                                "title": title,
                                "current_url": current_url,
                                "price_source": price_source,
                                "site_region_text": region_detected,
                            },
                        )
                    elif price is None:
                        row = build_failure_snapshot_row(
                            target,
                            snapshot_at=snapshot_at,
                            fetch_status="no_price_data",
                            error="price_not_found_on_page",
                            proxy_used=proxy_used,
                            raw_payload={
                                "title": title,
                                "current_url": current_url,
                                "price_source": price_source,
                                "site_region_text": region_detected,
                                "availability_status": availability_status,
                            },
                        )
                        row["availability_status"] = availability_status
                    else:
                        row = {
                            "snapshot_at": snapshot_at.isoformat(),
                            "snapshot_date": snapshot_at.date().isoformat(),
                            "nm_id": int(target["nm_id"]),
                            "item_label": target.get("item_label"),
                            "lifecycle_status": target.get("lifecycle_status"),
                            "product_url": current_url or url,
                            "buyer_visible_price": str(price),
                            "currency": RUB_CURRENCY,
                            "price_text_raw": raw_price_text,
                            "availability_status": availability_status,
                            "fetch_status": "success",
                            "error": None,
                            "proxy_used": proxy_used,
                            "raw_payload": {
                                "title": title,
                                "current_url": current_url,
                                "price_source": price_source,
                                "site_region_text": region_detected,
                            },
                        }
                except PlaywrightTimeoutError:
                    row = build_failure_snapshot_row(
                        target,
                        snapshot_at=snapshot_at,
                        fetch_status="timeout",
                        error="page_timeout",
                        proxy_used=proxy_used,
                        raw_payload={"target_url": url},
                    )
                except Exception as exc:  # pragma: no cover - defensive branch
                    row = build_failure_snapshot_row(
                        target,
                        snapshot_at=snapshot_at,
                        fetch_status="failed",
                        error=str(exc),
                        proxy_used=proxy_used,
                        raw_payload={"target_url": url},
                    )

                fetch_status = str(row["fetch_status"])
                fetch_status_counts[fetch_status] = fetch_status_counts.get(fetch_status, 0) + 1
                results.append(row)
        finally:
            context.close()
            browser.close()

    return results, {
        "success": True,
        "proxy_enabled": proxy_used,
        "region_detected": region_detected,
        "fetch_status_counts": fetch_status_counts,
    }


def resolve_proxy_url(explicit_proxy_url: str | None = None) -> str | None:
    return explicit_proxy_url if explicit_proxy_url is not None else settings.wb_site_price_proxy_url
