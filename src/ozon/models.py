from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class OzonProduct:
    offer_id: str
    product_id: int | None
    sku: int | None = None
    name: str = ""
    visibility: str | None = None
    status: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WebPriceInfo:
    offer_id: str
    product_id: int | None
    sku: int | None = None
    web_lookup_id: int | None = None
    url: str | None = None
    final_url: str | None = None
    buyer_visible_price: float | None = None
    raw_price_text: str | None = None
    other_bank_price: float | None = None
    old_price: float | None = None
    source: str = "web"
    page_type: str = "unknown_page"
    status: str = "unknown"
    page_title: str | None = None
    error: str | None = None
    price_candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class OzonBrowserCardResult:
    offer_id: str
    product_id: int | None
    sku: int | None = None
    web_lookup_id: int | None = None
    name: str = ""
    visibility: str | None = None
    seller_status: str | None = None
    url: str | None = None
    final_url: str | None = None
    page_title: str | None = None
    buyer_visible_price: float | None = None
    raw_price_text: str | None = None
    other_bank_price: float | None = None
    old_price: float | None = None
    price_source: str = "web"
    page_type: str = "unknown_page"
    status: str = "unknown"
    error: str | None = None
    price_candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    raw: dict[str, Any] = field(default_factory=dict)
