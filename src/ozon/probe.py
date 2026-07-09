from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .catalog_resolver import OzonSellerCatalogResolver
from .models import OzonBrowserCardResult, OzonProduct
from .web_checker_playwright import PlaywrightWebPriceChecker


def _coerce_product(item: str | Mapping[str, Any] | OzonProduct) -> OzonProduct:
    if isinstance(item, OzonProduct):
        return item
    if isinstance(item, str):
        offer_id = item.strip()
        return OzonProduct(offer_id=offer_id, product_id=None, name="")
    if not isinstance(item, Mapping):
        raise TypeError(f"Unsupported Ozon item type: {type(item)!r}")

    offer_id = item.get("offer_id") or item.get("offerId") or item.get("article")
    product_id = item.get("product_id") or item.get("productId")
    return OzonProduct(
        offer_id=str(offer_id).strip() if offer_id is not None else "",
        product_id=OzonSellerCatalogResolver._to_int(product_id),
        sku=OzonSellerCatalogResolver._to_int(item.get("sku")),
        name=str(item.get("name") or item.get("title") or ""),
        visibility=OzonSellerCatalogResolver._to_optional_str(item.get("visibility")),
        status=OzonSellerCatalogResolver._to_optional_str(item.get("status")),
        raw=dict(item),
    )


def _resolve_products(items: Sequence[str | Mapping[str, Any] | OzonProduct]) -> list[OzonProduct]:
    normalized = [_coerce_product(item) for item in items]
    if all(product.product_id is not None for product in normalized):
        return normalized

    resolver = OzonSellerCatalogResolver.from_env()
    if resolver is None:
        return normalized
    return resolver.resolve_products(normalized)


def probe_ozon_browser_prices(
    items: Sequence[str | Mapping[str, Any] | OzonProduct],
    *,
    timeout: int = 30,
    headless: bool = False,
    profile_dir: Path | str = "runtime/browser_profile/ozon",
    browser_channel: str = "chrome",
    web_domain: str = "ozon.ru",
    connect_cdp_url: str = "",
) -> list[OzonBrowserCardResult]:
    products = _resolve_products(items)
    checker = PlaywrightWebPriceChecker(
        timeout=timeout,
        headless=headless,
        profile_dir=profile_dir,
        browser_channel=browser_channel,
        web_domain=web_domain,
        connect_cdp_url=connect_cdp_url,
    )

    results: list[OzonBrowserCardResult] = []
    try:
        for product in products:
            web_info = checker.get_buyer_visible_price(product)
            results.append(
                OzonBrowserCardResult(
                    offer_id=product.offer_id,
                    product_id=product.product_id,
                    sku=product.sku,
                    web_lookup_id=web_info.web_lookup_id,
                    name=product.name,
                    visibility=product.visibility,
                    seller_status=product.status,
                    url=web_info.url,
                    final_url=web_info.final_url,
                    page_title=web_info.page_title,
                    buyer_visible_price=web_info.buyer_visible_price,
                    raw_price_text=web_info.raw_price_text,
                    other_bank_price=web_info.other_bank_price,
                    old_price=web_info.old_price,
                    price_source=web_info.source,
                    page_type=web_info.page_type,
                    status=web_info.status,
                    error=web_info.error,
                    price_candidates=web_info.price_candidates,
                    raw=product.raw,
                )
            )
        return results
    finally:
        checker.close()
