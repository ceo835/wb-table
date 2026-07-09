from __future__ import annotations

from dataclasses import asdict

from src.ozon.catalog_resolver import OzonSellerCatalogResolver
from src.ozon.models import OzonProduct, WebPriceInfo
from src.ozon import probe
from src.ozon.web_checker_playwright import PlaywrightWebPriceChecker


def test_probe_wraps_resolved_products_into_results(monkeypatch) -> None:
    resolved = [
        OzonProduct(
            offer_id="ABC-1",
            product_id=101,
            sku=777001,
            name="Product 1",
            visibility="ACTIVE",
            status="visible",
            raw={"foo": "bar"},
        )
    ]

    class FakeChecker:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False

        def get_buyer_visible_price(self, product):
            return WebPriceInfo(
                offer_id=product.offer_id,
                product_id=product.product_id,
                sku=product.sku,
                web_lookup_id=product.sku,
                url=f"https://www.ozon.ru/product/{product.sku}/",
                final_url=f"https://www.ozon.ru/product/{product.sku}/",
                buyer_visible_price=1990.0,
                raw_price_text="1 990 ₽",
                source='product_page:[data-widget="webPrice"]',
                page_type="product_page",
                status="ok",
                page_title="Product 1",
                error=None,
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(probe, "_resolve_products", lambda items: resolved)
    monkeypatch.setattr(probe, "PlaywrightWebPriceChecker", FakeChecker)

    results = probe.probe_ozon_browser_prices(["ABC-1"])

    assert len(results) == 1
    row = asdict(results[0])
    assert row["offer_id"] == "ABC-1"
    assert row["product_id"] == 101
    assert row["sku"] == 777001
    assert row["web_lookup_id"] == 777001
    assert row["buyer_visible_price"] == 1990.0
    assert row["raw_price_text"] == "1 990 ₽"
    assert row["page_type"] == "product_page"
    assert row["status"] == "ok"
    assert row["seller_status"] == "visible"
    assert row["raw"] == {"foo": "bar"}


def test_playwright_price_parser_extracts_price_from_widget_text() -> None:
    checker = PlaywrightWebPriceChecker()
    price, raw = checker._price_from_text("Price 1 234 ₽")
    assert price == 1234.0
    assert raw == "1 234 ₽"


def test_playwright_price_parser_prefers_structured_main_price_over_noise() -> None:
    checker = PlaywrightWebPriceChecker()

    class FakeNode:
        def __init__(self, text: str) -> None:
            self._text = text

        def inner_text(self, timeout: int = 0) -> str:
            return self._text

        def text_content(self, timeout: int = 0) -> str:
            return self._text

    class FakeLocator:
        def __init__(self, texts: list[str]) -> None:
            self._texts = texts

        def count(self) -> int:
            return len(self._texts)

        def nth(self, index: int) -> FakeNode:
            return FakeNode(self._texts[index])

    class FakePage:
        def locator(self, selector: str) -> FakeLocator:
            if selector == '[data-widget*="price"]':
                return FakeLocator(["Товары за 1₽"])
            return FakeLocator([])

    html = """
        <html>
          <body>
            <script>
              {"type":"priceV2","priceV2":{"price":[
                {"text":"1294 ₽","textStyle":"PRICE"},
                {"text":"с другими банками 1438 ₽","textStyle":"PRICE"},
                {"text":"5500 ₽","textStyle":"ORIGINAL_PRICE"}
              ]}}
            </script>
          </body>
        </html>
    """

    price, raw, source = checker._extract_price(FakePage(), html, "product_page")

    assert price == 1294.0
    assert raw == "1294₽"
    assert source == "product_page:structured"
    assert checker._last_other_bank_price == 1438.0
    assert checker._last_old_price == 5500.0
    assert [candidate["value"] for candidate in checker._last_price_candidates[:3]] == [1294.0, 1438.0, 5500.0]


def test_playwright_price_parser_reads_web_price_state_json() -> None:
    checker = PlaywrightWebPriceChecker()

    class FakeLocator:
        def count(self) -> int:
            return 0

    class FakePage:
        def locator(self, selector: str) -> FakeLocator:
            return FakeLocator()

    html = """
        <html>
          <body>
            <div id="state-webPrice-3121879-default-1" data-state="{&quot;isAvailable&quot;:true,&quot;cardPrice&quot;:&quot;538 ₽&quot;,&quot;price&quot;:&quot;598 ₽&quot;,&quot;originalPrice&quot;:&quot;4 400 ₽&quot;}"></div>
          </body>
        </html>
    """

    price, raw, source = checker._extract_price(FakePage(), html, "product_page")

    assert price == 538.0
    assert raw == "538₽"
    assert source == "product_page:web_price_state"
    assert checker._last_other_bank_price == 598.0
    assert checker._last_old_price == 4400.0
    assert [candidate["value"] for candidate in checker._last_price_candidates[:3]] == [538.0, 598.0, 4400.0]


def test_playwright_page_type_detection_for_product_page() -> None:
    checker = PlaywrightWebPriceChecker()
    html = "<html><body><div>Product page</div></body></html>"
    assert checker._detect_page_type("https://www.ozon.ru/product/123/", html) == "product_page"


def test_playwright_uses_sku_for_lookup_id() -> None:
    checker = PlaywrightWebPriceChecker()
    product = OzonProduct(offer_id="ABC-1", product_id=101, sku=777001)

    assert checker._resolve_web_lookup_id(product) == 777001
    assert checker._build_product_url(777001) == "https://www.ozon.ru/product/777001/"


def test_playwright_marks_delivery_unavailable_as_separate_status(monkeypatch) -> None:
    checker = PlaywrightWebPriceChecker()
    product = OzonProduct(offer_id="ABC-1", product_id=101, sku=777001)

    class FakePage:
        url = "https://www.ozon.ru/product/777001/"

        def goto(self, *args, **kwargs):
            return None

        def wait_for_load_state(self, *args, **kwargs):
            return None

        def wait_for_selector(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def content(self):
            return "<html><body>Доставка недоступна</body></html>"

        def title(self):
            return "Product 1"

        def locator(self, *args, **kwargs):
            class _Loc:
                def count(self):
                    return 0

                def inner_text(self, *a, **k):
                    return ""

            return _Loc()

    monkeypatch.setattr(checker, "_ensure_page", lambda: FakePage())
    monkeypatch.setattr(checker, "_save_debug_artifacts", lambda *args, **kwargs: (None, None))
    info = checker.get_buyer_visible_price(product)

    assert info.web_lookup_id == 777001
    assert info.status == "delivery_unavailable"
    assert info.buyer_visible_price is None
    assert info.error is None


def test_playwright_marks_search_redirect_as_not_found(monkeypatch) -> None:
    checker = PlaywrightWebPriceChecker()
    product = OzonProduct(offer_id="ABC-1", product_id=101, sku=777001)

    class FakePage:
        url = "https://www.ozon.ru/search/?text=777001"

        def goto(self, *args, **kwargs):
            return None

        def wait_for_load_state(self, *args, **kwargs):
            return None

        def wait_for_selector(self, *args, **kwargs):
            return None

        def wait_for_timeout(self, *args, **kwargs):
            return None

        def content(self):
            return "<html><body><div>search results</div></body></html>"

        def title(self):
            return "Search"

        def locator(self, *args, **kwargs):
            class _Loc:
                def count(self):
                    return 0

                def inner_text(self, *a, **k):
                    return ""

            return _Loc()

    monkeypatch.setattr(checker, "_ensure_page", lambda: FakePage())
    monkeypatch.setattr(checker, "_save_debug_artifacts", lambda *args, **kwargs: (None, None))
    info = checker.get_buyer_visible_price(product)

    assert info.web_lookup_id == 777001
    assert info.status == "not_found_or_search_redirect"
    assert info.buyer_visible_price is None


def test_catalog_resolver_fills_missing_product_id_from_index(monkeypatch) -> None:
    resolver = OzonSellerCatalogResolver(client_id="cid", api_key="key")
    monkeypatch.setattr(
        resolver,
        "_build_offer_index",
        lambda offer_ids: {"ABC-1": OzonProduct(offer_id="ABC-1", product_id=777, name="Product")},
    )

    resolved = resolver.resolve_products([{"offer_id": "ABC-1", "name": "Product"}])

    assert len(resolved) == 1
    assert resolved[0].offer_id == "ABC-1"
    assert resolved[0].product_id == 777
