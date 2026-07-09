from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from src.ozon.models import OzonBrowserCardResult
from scripts.probe_ozon_tracked_data import fetch_api_details


class FakeOzonApiClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def post(self, endpoint: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None, str]:
        self.posts.append((endpoint, payload))
        if endpoint == "/v3/product/info/list":
            return 200, {
                "result": {
                    "items": [
                        {
                            "offer_id": "ABC-1",
                            "product_id": 101,
                            "sku": 777001,
                            "name": "Product 1",
                            "status": {"state_name": "Active"}
                        }
                    ]
                }
            }, ""
        elif endpoint == "/v4/product/info/stocks":
            return 200, {
                "result": {
                    "items": [
                        {
                            "offer_id": "ABC-1",
                            "product_id": 101,
                            "stocks": [
                                {"type": "fbo", "present": 15},
                                {"type": "fbs", "present": 5}
                            ]
                        }
                    ]
                }
            }, ""
        elif endpoint == "/v5/product/info/prices":
            return 200, {
                "result": {
                    "items": [
                        {
                            "offer_id": "ABC-1",
                            "product_id": 101,
                            "price": {
                                "price": "1990.00",
                                "marketing_seller_price": "1990.00"
                            }
                        }
                    ]
                }
            }, ""
        return 404, None, "Not Found"


def test_fetch_api_details_merges_all_fields() -> None:
    client = FakeOzonApiClient()
    data = fetch_api_details(client, ["ABC-1"])

    assert len(data) == 1
    rec = data["ABC-1"]
    assert rec["offer_id"] == "ABC-1"
    assert rec["product_id"] == 101
    assert rec["sku"] == 777001
    assert rec["name"] == "Product 1"
    assert rec["status_api"] == "Active"
    assert rec["stock"] == 20.0
    assert rec["seller_price_api"] == 1990.0


def test_suspicious_one_ruble_promo_fallback() -> None:
    # Simulating a scenario where Playwright returns 1.0₽ due to a promo
    # but the candidates contain the correct price
    result = OzonBrowserCardResult(
        offer_id="ABC-1",
        product_id=101,
        sku=777001,
        buyer_visible_price=1.0,
        raw_price_text="1 ₽",
        price_candidates=(
            {
                "value": 1.0,
                "role": "current",
                "score": 10,
                "source": "promo"
            },
            {
                "value": 1499.0,
                "role": "current",
                "score": 120,
                "source": "selector:[data-widget=\"webPrice\"]"
            }
        )
    )

    buyer_price = result.buyer_visible_price
    if buyer_price is not None and buyer_price <= 1.01:
        real_candidates = [c for c in result.price_candidates if c.get("role") == "current" and c.get("value", 0) > 1.01]
        if real_candidates:
            best_cand = max(real_candidates, key=lambda c: (int(c.get("score", 0)), float(c.get("value", 0))))
            buyer_price = float(best_cand["value"])

    assert buyer_price == 1499.0
