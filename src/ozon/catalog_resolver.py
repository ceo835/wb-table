from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests
from dotenv import load_dotenv

from .models import OzonProduct

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

OZON_API_BASE = "https://api-seller.ozon.ru"
DEFAULT_PRODUCT_LIST_ENDPOINTS = ("/v3/product/list", "/v2/product/list")


def get_ozon_credentials() -> tuple[str, str]:
    client_id = os.getenv("OZON_CLIENT_ID", "").strip()
    api_key = os.getenv("OZON_API_KEY", "").strip() or os.getenv("OZON_API_TOKEN", "").strip()
    return client_id, api_key


class OzonSellerCatalogResolver:
    def __init__(
        self,
        client_id: str,
        api_key: str,
        *,
        base_url: str = OZON_API_BASE,
        timeout: int = 30,
        product_list_endpoints: Sequence[str] = DEFAULT_PRODUCT_LIST_ENDPOINTS,
    ) -> None:
        self.client_id = client_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.product_list_endpoints = tuple(product_list_endpoints)
        self.session = requests.Session()
        self.session.trust_env = False
        self.headers = {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    @classmethod
    def from_env(cls) -> OzonSellerCatalogResolver | None:
        client_id, api_key = get_ozon_credentials()
        if not client_id or not api_key:
            return None
        return cls(client_id=client_id, api_key=api_key)

    def resolve_products(self, items: Sequence[str | Mapping[str, Any] | OzonProduct]) -> list[OzonProduct]:
        normalized = [self._coerce_product(item) for item in items]
        unresolved_offer_ids = [product.offer_id for product in normalized if product.product_id is None and product.offer_id]
        if not unresolved_offer_ids:
            return normalized

        resolved_by_offer_id = self._build_offer_index(unresolved_offer_ids)
        resolved_products: list[OzonProduct] = []
        for product in normalized:
            if product.product_id is not None:
                resolved_products.append(product)
                continue
            resolved = resolved_by_offer_id.get(product.offer_id)
            if resolved is not None:
                resolved_products.append(resolved)
                continue
            resolved_products.append(product)
        return resolved_products

    def _build_offer_index(self, offer_ids: Sequence[str]) -> dict[str, OzonProduct]:
        pending = {str(offer_id).strip() for offer_id in offer_ids if str(offer_id).strip()}
        if not pending:
            return {}

        index: dict[str, OzonProduct] = {}
        last_id = ""
        while pending:
            payload = {
                "filter": {"visibility": "ALL"},
                "last_id": last_id,
                "limit": 1000,
            }
            data = self._post_with_fallback(self.product_list_endpoints, payload, operation_name="product list")
            result = data.get("result", data)
            items = result.get("items", [])
            if not isinstance(items, list):
                items = []

            for item in items:
                product = self._parse_product_item(item)
                if product is None or product.offer_id not in pending:
                    continue
                index[product.offer_id] = product
                pending.discard(product.offer_id)

            next_last_id = result.get("last_id") or result.get("lastId") or ""
            if not next_last_id or str(next_last_id) == last_id or not items:
                break
            last_id = str(next_last_id)

        return index

    def _post_with_fallback(self, endpoints: Sequence[str], payload: dict[str, Any], *, operation_name: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for endpoint in endpoints:
            try:
                return self._post_json(endpoint, payload, operation_name=operation_name)
            except RuntimeError as exc:
                message = str(exc).lower()
                if "error 404" in message or "error 405" in message:
                    last_error = exc
                    continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Failed to execute OZON {operation_name}.")

    def _post_json(self, endpoint: str, payload: dict[str, Any], *, operation_name: str) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        response = self.session.post(url, json=payload, headers=self.headers, timeout=self.timeout)
        try:
            data = response.json() if response.content else {}
        except ValueError as exc:
            raise RuntimeError(f"OZON returned invalid JSON for {operation_name}.") from exc

        if not response.ok:
            error_message = data.get("message") or data.get("error") or response.text
            raise RuntimeError(f"OZON API error {response.status_code}: {error_message}")
        return data

    @staticmethod
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

    @staticmethod
    def _parse_product_item(item: Mapping[str, Any]) -> OzonProduct | None:
        offer_id = item.get("offer_id") or item.get("offerId")
        if not offer_id:
            return None
        return OzonProduct(
            offer_id=str(offer_id),
            product_id=OzonSellerCatalogResolver._to_int(item.get("product_id") or item.get("productId")),
            sku=OzonSellerCatalogResolver._to_int(item.get("sku")),
            name=str(item.get("name") or item.get("title") or ""),
            visibility=OzonSellerCatalogResolver._to_optional_str(item.get("visibility")),
            status=OzonSellerCatalogResolver._to_optional_str(item.get("status")),
            raw=dict(item),
        )

    @staticmethod
    def _to_int(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_optional_str(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
