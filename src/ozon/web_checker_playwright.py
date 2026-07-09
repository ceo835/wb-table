import atexit
import json
import logging
import re
import time
from html import unescape as html_unescape
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:
    PlaywrightTimeoutError = Exception
    sync_playwright = None

from .models import OzonProduct, WebPriceInfo

logger = logging.getLogger(__name__)


class PlaywrightWebPriceChecker:
    ALLOWED_DOMAINS = ("ozon.ru", "ozon.kz")
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0 Safari/537.36"
    )
    WAIT_AFTER_LOAD_MS = 3000
    PRICE_WIDGET_SELECTORS = [
        '[data-widget="webPrice"]',
        '[data-widget="webPriceWithDiscount"]',
        '[data-widget*="price"]',
        '[data-widget*="Price"]',
    ]
    PRICE_CONTAINER_SELECTORS = [
        '[data-widget*="webPrice"]',
        '[data-widget*="priceV2"]',
        '[data-widget*="price"]',
        '[class*="webPrice"]',
        '[class*="price"]',
        '[data-test*="price"]',
    ]
    RUB_PATTERN = re.compile(r"(\d[\d\s\u00A0\u2009]{0,})(?:[.,](\d{1,2}))?\s*(?:₽|руб\.?)", re.IGNORECASE)
    PRICE_TEXT_PATTERN = re.compile(
        r'"text"\s*:\s*"(?P<text>[^"]*?(?:₽|руб)[^"]*?)"\s*,\s*"textStyle"\s*:\s*"(?P<style>[^"]+)"',
        re.IGNORECASE,
    )
    PRICE_IGNORE_CONTEXT_MARKERS = (
        "доставка",
        "рассроч",
        "installment",
        "бонус",
        "bonus",
        "балл",
        "points",
        "товары за",
    )
    PRICE_OTHER_BANK_MARKERS = (
        "с другими банками",
        "другими банками",
        "other bank",
        "other banks",
        "with other banks",
    )
    PRICE_OLD_MARKERS = (
        "original price",
        "old price",
        "старая цена",
        "зачерк",
        "до скидки",
        "price cut",
    )
    BLOCKED_MARKERS = [
        "captcha",
        "доступ ограничен",
        "access denied",
        "verify you are human",
        "robot",
        "робот",
        "проверьте, что вы не робот",
    ]
    NETWORK_BLOCKED_MARKERS = [
        "выключите vpn",
        "подключитесь к другой сети",
        "нет соединения",
        "похоже, нет соединения",
    ]
    UNAVAILABLE_MARKERS = [
        "нет в наличии",
        "товар закончился",
        "не найден",
        "страница не найдена",
        "product not found",
        "out of stock",
    ]

    def __init__(
        self,
        timeout: int = 30,
        headless: bool = False,
        profile_dir: Path | str = "runtime/browser_profile/ozon",
        browser_channel: str = "chrome",
        web_domain: str = "ozon.ru",
        connect_cdp_url: str = "",
    ):
        self.timeout = timeout
        self.headless = headless
        self.profile_dir = Path(profile_dir)
        self.browser_channel = browser_channel
        self.web_domain = self._normalize_domain(web_domain)
        self.connect_cdp_url = connect_cdp_url.strip()
        self._playwright_manager = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._connected_over_cdp = False
        self._created_page = False
        self._last_price_candidates: list[dict[str, object]] = []
        self._last_selected_price_candidate: dict[str, object] | None = None
        self._last_other_bank_price: float | None = None
        self._last_old_price: float | None = None
        self._debug_dir = Path("debug/web_audit")
        logger.info("Using Playwright web checker")
        logger.info("Playwright target domain: %s", self.web_domain)
        logger.info("Playwright persistent profile: %s", self.profile_dir)
        logger.info("Playwright browser channel: %s", self.browser_channel)
        logger.info("Playwright headless: %s", str(self.headless).lower())
        if self.connect_cdp_url:
            logger.info("Connecting to existing Chrome via CDP: %s", self.connect_cdp_url)
        atexit.register(self.close)

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        cleaned = (domain or "ozon.ru").strip().lower()
        cleaned = cleaned.removeprefix("https://").removeprefix("http://")
        cleaned = cleaned.removeprefix("www.")
        return cleaned.strip("/") or "ozon.ru"

    def _build_base_url(self) -> str:
        return f"https://www.{self.web_domain}"

    def _build_product_url(self, web_lookup_id: int) -> str:
        return f"{self._build_base_url()}/product/{web_lookup_id}/"

    @staticmethod
    def _resolve_web_lookup_id(product: OzonProduct) -> Optional[int]:
        if product.sku is not None:
            return product.sku
        return product.product_id

    def _is_target_domain(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return host == f"www.{self.web_domain}" or host == self.web_domain

    def _launch_persistent_context(self, headless: bool):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright_manager = sync_playwright()
        self._playwright = self._playwright_manager.start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            channel=self.browser_channel,
            headless=headless,
            user_agent=self.USER_AGENT,
            locale="ru-RU",
            args=["--no-proxy-server"],
        )
        logger.info("Playwright browser started without proxy")
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        self._created_page = not bool(pages)
        return self._context, self._page

    def _connect_over_cdp(self):
        self._playwright_manager = sync_playwright()
        self._playwright = self._playwright_manager.start()
        logger.info("Connecting to existing Chrome via CDP: %s", self.connect_cdp_url)
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(self.connect_cdp_url)
        except Exception as exc:
            self._playwright.stop()
            self._playwright = None
            self._playwright_manager = None
            raise RuntimeError(
                "Could not connect to Chrome CDP. Start Chrome with --remote-debugging-port=9222"
            ) from exc

        contexts = self._browser.contexts
        if not contexts:
            self._playwright.stop()
            self._browser = None
            self._playwright = None
            self._playwright_manager = None
            raise RuntimeError(
                "Could not connect to Chrome CDP. Start Chrome with --remote-debugging-port=9222"
            )

        self._context = contexts[0]
        pages = self._context.pages
        if pages:
            self._page = pages[0]
            self._created_page = False
        else:
            self._page = self._context.new_page()
            self._created_page = True
        self._connected_over_cdp = True
        return self._context, self._page

    def _ensure_page(self):
        if sync_playwright is None:
            return None
        if self._page is not None:
            return self._page
        if self.connect_cdp_url:
            _, page = self._connect_over_cdp()
            return page
        _, page = self._launch_persistent_context(headless=self.headless)
        return page

    def run_setup_browser(self) -> None:
        if sync_playwright is None:
            raise RuntimeError("Playwright is not installed.")

        logger.info("Playwright persistent profile: %s", self.profile_dir)
        logger.info("Playwright browser channel: %s", self.browser_channel)
        logger.info("Playwright headless: false")
        logger.info("Playwright browser started without proxy")
        logger.info(
            "Open ozon.ru or ozon.kz, choose region, pass any check, open any product card, verify price is visible, then close the browser."
        )

        playwright_manager = sync_playwright()
        playwright = playwright_manager.start()
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            channel=self.browser_channel,
            headless=False,
            user_agent=self.USER_AGENT,
            locale="ru-RU",
            args=["--no-proxy-server"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(self._build_base_url(), wait_until="domcontentloaded", timeout=self.timeout * 1000)

        try:
            while True:
                if len(context.pages) == 0:
                    break
                time.sleep(1)
        finally:
            logger.info("OZON browser setup finished, profile saved to %s", self.profile_dir)
            try:
                context.close()
            except Exception:
                logger.debug("Failed to close setup browser context", exc_info=True)
            try:
                playwright.stop()
            except Exception:
                logger.debug("Failed to stop Playwright after setup", exc_info=True)

    @staticmethod
    def _to_price(raw: str) -> Optional[float]:
        cleaned = raw.replace(" ", "").replace("\u00A0", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _price_from_text(self, text: str) -> tuple[Optional[float], Optional[str]]:
        match = self.RUB_PATTERN.search(text)
        if not match:
            return None, None
        raw = match.group(0)
        number = match.group(1)
        fraction = match.group(2)
        normalized = number if fraction is None else f"{number}.{fraction}"
        return self._to_price(normalized), raw

    @staticmethod
    def _normalize_price_text(text: str) -> str:
        normalized = re.sub(r"\s+", " ", text or "").strip()
        return normalized.replace("\u2009", " ").replace("\u00A0", " ")

    @staticmethod
    def _compact_raw_price_text(text: str) -> str:
        return re.sub(r"[\s\u00A0\u2009]+", "", text or "").strip()

    def _extract_price_candidates_from_text(
        self,
        text: str,
        *,
        source: str,
        selector: str | None = None,
        base_score: int = 0,
        source_kind: str = "text",
    ) -> list[dict[str, object]]:
        normalized = self._normalize_price_text(text)
        if not normalized:
            return []

        lower = normalized.lower()
        candidates: list[dict[str, object]] = []
        exact_price_selector = selector in {
            '[data-widget="webPrice"]',
            '[data-widget="webPriceWithDiscount"]',
        }

        for match in self.RUB_PATTERN.finditer(normalized):
            raw_text = match.group(0)
            number = match.group(1)
            fraction = match.group(2)
            price_text = number if fraction is None else f"{number}.{fraction}"
            value = self._to_price(price_text)
            if value is None:
                continue

            context_start = max(0, match.start() - 80)
            context_end = min(len(lower), match.end() + 80)
            context = lower[context_start:context_end]

            # Check context around the match to distinguish between different prices within the same text block
            right_context = lower[match.end() : match.end() + 22]
            left_context = lower[max(0, match.start() - 12) : match.start()]

            role = "current"
            reason = "price_candidate"
            if any(marker in right_context or marker in left_context for marker in self.PRICE_OLD_MARKERS):
                role = "old"
                reason = "old_price"
            elif any(marker in right_context or marker in left_context for marker in self.PRICE_OTHER_BANK_MARKERS):
                role = "other_bank"
                reason = "other_bank_price"

            if value <= 1.01 and not exact_price_selector and source_kind != "structured":
                if "товары за" in lower or "за 1" in lower or "1₽" in lower:
                    continue
                if "price" not in lower and "цена" not in lower and "руб" not in lower:
                    continue

            if any(marker in lower for marker in self.PRICE_IGNORE_CONTEXT_MARKERS):
                if not exact_price_selector and source_kind != "structured":
                    continue

            score = base_score
            if source_kind == "structured":
                score += 90
            elif exact_price_selector:
                score += 120
            elif selector and "price" in selector.lower():
                score += 70
            else:
                score += 40

            if role == "current":
                score += 20
            elif role == "other_bank":
                score -= 10
            elif role == "old":
                score -= 50

            if value <= 1.01:
                score -= 120

            candidates.append(
                {
                    "value": value,
                    "raw_price_text": self._compact_raw_price_text(raw_text),
                    "source": source,
                    "selector": selector,
                    "source_kind": source_kind,
                    "role": role,
                    "score": score,
                    "context": context.strip(),
                    "reason": reason,
                    "text": normalized,
                }
            )

        # Auto-adjust roles and update scores if multiple prices are found in a single text block
        if len(candidates) >= 2:
            sorted_candidates = sorted(candidates, key=lambda c: float(c["value"]))
            for i, cand in enumerate(sorted_candidates):
                old_role = cand["role"]
                if len(sorted_candidates) == 2:
                    new_role = "current" if i == 0 else "other_bank"
                    reason = "auto_block_current_price" if i == 0 else "auto_block_other_bank_price"
                else:
                    if i == 0:
                        new_role = "current"
                        reason = "auto_block_current_price"
                    elif i == 1:
                        new_role = "other_bank"
                        reason = "auto_block_other_bank_price"
                    else:
                        new_role = "old"
                        reason = "auto_block_old_price"
                
                cand["role"] = new_role
                cand["reason"] = reason
                
                if old_role != new_role:
                    if old_role == "current":
                        cand["score"] -= 20
                    elif old_role == "other_bank":
                        cand["score"] += 10
                    elif old_role == "old":
                        cand["score"] += 50
                        
                    if new_role == "current":
                        cand["score"] += 20
                    elif new_role == "other_bank":
                        cand["score"] -= 10
                    elif new_role == "old":
                        cand["score"] -= 50

        return candidates

    def _extract_price_candidates_from_html(self, html: str, page_type: str) -> list[dict[str, object]]:
        decoded = html_unescape(html)
        candidates: list[dict[str, object]] = []
        for match in self.PRICE_TEXT_PATTERN.finditer(decoded):
            text = self._normalize_price_text(match.group("text"))
            style = match.group("style") or ""
            style_upper = style.upper()
            context = decoded[max(0, match.start() - 120) : min(len(decoded), match.end() + 120)].lower()
            source = f"{page_type}:structured"
            role = "current"
            reason = "structured_price"

            if "ORIGINAL" in style_upper:
                role = "old"
                reason = "structured_old_price"
            elif "BANK" in style_upper or any(marker in text.lower() for marker in self.PRICE_OTHER_BANK_MARKERS):
                role = "other_bank"
                reason = "structured_other_bank_price"
            elif "PRICE" not in style_upper:
                continue

            price, _ = self._price_from_text(text)
            if price is None:
                continue
            if price <= 1.01 and role == "current":
                if "товары за" in text.lower() or "за 1" in text.lower() or "1₽" in text:
                    continue

            score = 90
            if role == "current":
                score += 30
            elif role == "other_bank":
                score -= 10
            elif role == "old":
                score -= 50

            candidates.append(
                {
                    "value": price,
                    "raw_price_text": self._compact_raw_price_text(text),
                    "source": source,
                    "selector": None,
                    "source_kind": "structured",
                    "role": role,
                    "score": score,
                    "context": context.strip(),
                    "reason": reason,
                    "text": text,
                    "style": style,
                }
            )

        return candidates

    def _collect_price_candidates(self, page, html: str, page_type: str) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        selectors = list(dict.fromkeys([*self.PRICE_WIDGET_SELECTORS, *self.PRICE_CONTAINER_SELECTORS]))

        for selector in selectors:
            try:
                locator = page.locator(selector)
                count = locator.count()
            except Exception:
                continue

            base_score = 120 if selector in {
                '[data-widget="webPrice"]',
                '[data-widget="webPriceWithDiscount"]',
            } else 60

            for index in range(min(count, 5)):
                try:
                    item = locator.nth(index)
                except Exception:
                    continue

                text = ""
                for getter in ("inner_text", "text_content"):
                    try:
                        text = getattr(item, getter)(timeout=1000) or ""
                    except Exception:
                        text = ""
                    if text:
                        break

                if not text:
                    continue

                candidates.extend(
                    self._extract_price_candidates_from_text(
                        text,
                        source=f"{page_type}:selector:{selector}[{index}]",
                        selector=selector,
                        base_score=base_score,
                        source_kind="selector",
                    )
                )

        candidates.extend(self._extract_price_candidates_from_html(html, page_type))
        candidates.sort(
            key=lambda candidate: (
                int(candidate.get("score") or 0),
                float(candidate.get("value") or 0.0),
            ),
            reverse=True,
        )
        return candidates

    @staticmethod
    def _select_best_price_candidate(candidates: list[dict[str, object]]) -> dict[str, object] | None:
        current_candidates = [candidate for candidate in candidates if candidate.get("role") == "current"]
        if not current_candidates:
            return None
        return max(
            current_candidates,
            key=lambda candidate: (
                int(candidate.get("score") or 0),
                float(candidate.get("value") or 0.0),
            ),
        )

    def _extract_price(self, page, html: str, page_type: str) -> tuple[Optional[float], Optional[str], Optional[str]]:
        self._last_price_candidates = self._collect_price_candidates(page, html, page_type)
        self._last_selected_price_candidate = self._select_best_price_candidate(self._last_price_candidates)
        self._last_other_bank_price = None
        self._last_old_price = None

        for candidate in self._last_price_candidates:
            if candidate.get("role") == "other_bank" and self._last_other_bank_price is None:
                value = candidate.get("value")
                if isinstance(value, (int, float)):
                    self._last_other_bank_price = float(value)
            if candidate.get("role") == "old" and self._last_old_price is None:
                value = candidate.get("value")
                if isinstance(value, (int, float)):
                    self._last_old_price = float(value)

        if self._last_selected_price_candidate is None:
            return None, None, None

        selected_value = self._last_selected_price_candidate.get("value")
        selected_raw = self._last_selected_price_candidate.get("raw_price_text")
        selected_source = self._last_selected_price_candidate.get("source")
        if not isinstance(selected_value, (int, float)):
            return None, None, None

        return (
            float(selected_value),
            str(selected_raw) if selected_raw is not None else None,
            str(selected_source) if selected_source is not None else None,
        )

    def _is_allowed_domain(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return any(host == domain or host.endswith(f".{domain}") for domain in self.ALLOWED_DOMAINS)

    def _detect_page_type(self, url: str, html: str, status_code: Optional[int] = None) -> str:
        normalized = html.lower()
        if status_code in {403, 429}:
            return "blocked_page"
        if any(marker in normalized for marker in self.NETWORK_BLOCKED_MARKERS):
            return "network_blocked"
        if any(marker in normalized for marker in self.BLOCKED_MARKERS):
            return "blocked_page"

        if not self._is_allowed_domain(url):
            return "wrong_page"

        path = urlparse(url).path.lower()
        if "/search/" in path or path == "/search":
            return "search_page"
        if "/product/" in path:
            return "product_page"
        return "wrong_page"

    def _detect_error_reason(self, html: str, status_code: Optional[int] = None) -> str:
        normalized = html.lower()
        if status_code in {403, 429}:
            return "blocked"
        if any(marker in normalized for marker in self.NETWORK_BLOCKED_MARKERS):
            return "network_blocked"
        if any(marker in normalized for marker in self.BLOCKED_MARKERS):
            return "blocked"
        if any(marker in normalized for marker in self.UNAVAILABLE_MARKERS):
            return "unavailable"
        return "price_not_found"

    def _find_product_url_on_search_page(self, page, current_url: str, web_lookup_id: Optional[int]) -> Optional[str]:
        if web_lookup_id is None:
            return None
        selectors = [
            f'a[href*="/product/{web_lookup_id}"]',
            f'a[href*="-{web_lookup_id}"]',
            f'a[href*="{web_lookup_id}"]',
        ]
        for selector in selectors:
            try:
                href = page.locator(selector).first.get_attribute("href", timeout=1000)
            except Exception:
                href = None
            if not href:
                continue
            absolute_url = urljoin(current_url, href)
            if self._is_allowed_domain(absolute_url) and "/product/" in urlparse(absolute_url).path.lower():
                return absolute_url
        return None

    def _detect_delivery_unavailable(self, html: str, page_title: Optional[str] = None) -> bool:
        normalized = f"{html}\n{page_title or ''}".lower()
        return any(
            marker in normalized
            for marker in (
                "доставка недоступна",
                "delivery unavailable",
                "нет доставки",
                "доставка пока недоступна",
            )
        )

    def _detect_result_status(
        self,
        *,
        page_type: str,
        final_url: str,
        html: str,
        price: Optional[float],
        status_code: Optional[int],
        page_title: Optional[str],
    ) -> str:
        if not self._is_target_domain(final_url):
            return "not_found_or_search_redirect"
        if page_type == "product_page":
            if price is not None:
                return "ok"
            if self._detect_delivery_unavailable(html, page_title):
                return "delivery_unavailable"
            if any(marker in html.lower() for marker in self.UNAVAILABLE_MARKERS):
                return "not_found_or_search_redirect"
            return self._detect_error_reason(html, status_code=status_code)
        if page_type == "search_page":
            return "not_found_or_search_redirect"
        if page_type == "network_blocked":
            return "network_blocked"
        if page_type == "blocked_page":
            return "blocked"
        return self._detect_error_reason(html, status_code=status_code)

    def _save_debug_artifacts(self, page, product: OzonProduct, html: str) -> tuple[Path, Path]:
        self._debug_dir.mkdir(parents=True, exist_ok=True)
        safe_offer_id = re.sub(r"[^A-Za-z0-9._-]+", "_", product.offer_id)
        lookup_id = product.sku if product.sku is not None else product.product_id
        base_name = f"{safe_offer_id}_{lookup_id if lookup_id is not None else 'no_web_lookup_id'}"
        screenshot_path = self._debug_dir / f"{base_name}.png"
        html_path = self._debug_dir / f"{base_name}.html"

        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            logger.debug("Failed to save screenshot for %s", product.offer_id, exc_info=True)

        html_path.write_text(html, encoding="utf-8")
        return screenshot_path, html_path

    def _save_price_candidates_artifact(
        self,
        product: OzonProduct,
        page_type: str,
        final_url: str,
    ) -> Path | None:
        if not self._last_price_candidates:
            return None

        self._debug_dir.mkdir(parents=True, exist_ok=True)
        safe_offer_id = re.sub(r"[^A-Za-z0-9._-]+", "_", product.offer_id)
        lookup_id = product.sku if product.sku is not None else product.product_id
        base_name = f"{safe_offer_id}_{lookup_id if lookup_id is not None else 'no_web_lookup_id'}"
        candidates_path = self._debug_dir / f"{base_name}.candidates.json"
        payload = {
            "offer_id": product.offer_id,
            "product_id": product.product_id,
            "sku": product.sku,
            "web_lookup_id": lookup_id,
            "page_type": page_type,
            "final_url": final_url,
            "selected_candidate": self._last_selected_price_candidate,
            "other_bank_price": self._last_other_bank_price,
            "old_price": self._last_old_price,
            "candidates": self._last_price_candidates,
        }
        candidates_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return candidates_path

    def close(self) -> None:
        if self._page is not None:
            try:
                if self._connected_over_cdp:
                    if self._created_page:
                        self._page.close()
                else:
                    self._page.close()
            except Exception:
                logger.debug("Failed to close Playwright page", exc_info=True)
            self._page = None

        if self._context is not None:
            try:
                if not self._connected_over_cdp:
                    self._context.close()
            except Exception:
                logger.debug("Failed to close Playwright context", exc_info=True)
            self._context = None

        if self._browser is not None:
            try:
                if not self._connected_over_cdp:
                    self._browser.close()
            except Exception:
                logger.debug("Failed to close Playwright browser", exc_info=True)
            self._browser = None

        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                logger.debug("Failed to stop Playwright", exc_info=True)
            self._playwright = None

        self._playwright_manager = None
        self._connected_over_cdp = False
        self._created_page = False

    def _log_page_debug(
        self,
        page,
        requested_url: str,
        html: str,
        error_reason: str,
        web_lookup_id: Optional[int],
        page_type: str,
        parsed_price_source: Optional[str],
    ) -> None:
        try:
            current_url = page.url
        except Exception:
            current_url = "<unknown>"
        try:
            page_title = page.title()
        except Exception:
            page_title = "<unknown>"
        text_snippet = re.sub(r"\s+", " ", html)[:300]
        logger.warning(
            "Playwright page debug: requested_url=%s web_lookup_id=%s final_url=%s title=%s page_type=%s parsed_price_source=%s error=%s text=%s",
            requested_url,
            web_lookup_id,
            current_url,
            page_title,
            page_type,
            parsed_price_source,
            error_reason,
            text_snippet,
        )

    def get_buyer_visible_price(self, product: OzonProduct) -> WebPriceInfo:
        web_lookup_id = self._resolve_web_lookup_id(product)
        requested_url = self._build_product_url(web_lookup_id) if web_lookup_id is not None else None
        if requested_url is None:
            return WebPriceInfo(
                offer_id=product.offer_id,
                product_id=product.product_id,
                sku=product.sku,
                web_lookup_id=None,
                url=None,
                final_url=None,
                buyer_visible_price=None,
                raw_price_text=None,
                source="no_url",
                page_type="wrong_page",
                status="no_web_lookup_id",
                error="no_web_lookup_id",
            )

        if sync_playwright is None:
            return WebPriceInfo(
                offer_id=product.offer_id,
                product_id=product.product_id,
                sku=product.sku,
                web_lookup_id=web_lookup_id,
                url=requested_url,
                final_url=requested_url,
                buyer_visible_price=None,
                raw_price_text=None,
                source="playwright",
                page_type="wrong_page",
                status="playwright_not_installed",
                error="playwright_not_installed",
            )

        try:
            page = self._ensure_page()
            logger.info(
                "Playwright opening card for %s requested_url=%s web_lookup_id=%s",
                product.offer_id,
                requested_url,
                web_lookup_id,
            )
            response = page.goto(requested_url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
            page.wait_for_load_state("domcontentloaded", timeout=self.timeout * 1000)

            widget_selector = ", ".join(self.PRICE_WIDGET_SELECTORS)
            try:
                page.wait_for_selector(widget_selector, timeout=3000)
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(self.WAIT_AFTER_LOAD_MS)
            final_url = page.url
            html = page.content()
            status_code = response.status if response is not None else None
            page_type = self._detect_page_type(final_url, html, status_code=status_code)

            if page_type == "search_page":
                redirected_url = self._find_product_url_on_search_page(page, final_url, web_lookup_id)
                if redirected_url:
                    logger.info(
                        "Playwright search redirect for %s: web_lookup_id=%s search_url=%s target_url=%s",
                        product.offer_id,
                        web_lookup_id,
                        final_url,
                        redirected_url,
                    )
                    response = page.goto(redirected_url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
                    page.wait_for_load_state("domcontentloaded", timeout=self.timeout * 1000)
                    try:
                        page.wait_for_selector(widget_selector, timeout=3000)
                    except PlaywrightTimeoutError:
                        pass
                    page.wait_for_timeout(self.WAIT_AFTER_LOAD_MS)
                    final_url = page.url
                    html = page.content()
                    status_code = response.status if response is not None else None
                    page_type = self._detect_page_type(final_url, html, status_code=status_code)

            price, raw, parsed_price_source = self._extract_price(page, html, page_type)
            try:
                page_title = page.title()
            except Exception:
                page_title = None
            result_status = self._detect_result_status(
                page_type=page_type,
                final_url=final_url,
                html=html,
                price=price,
                status_code=status_code,
                page_title=page_title,
            )
            logger.info(
                "Playwright page evaluation offer_id=%s requested_url=%s web_lookup_id=%s final_url=%s page_type=%s status=%s parsed_price_source=%s",
                product.offer_id,
                requested_url,
                web_lookup_id,
                final_url,
                page_type,
                result_status,
                parsed_price_source,
            )
            if result_status == "ok" and price is not None:
                logger.info("Playwright parsed card for %s price=%s", product.offer_id, price)
                return WebPriceInfo(
                    offer_id=product.offer_id,
                    product_id=product.product_id,
                    sku=product.sku,
                    web_lookup_id=web_lookup_id,
                    url=final_url,
                    final_url=final_url,
                    buyer_visible_price=price,
                    raw_price_text=raw,
                    other_bank_price=self._last_other_bank_price,
                    old_price=self._last_old_price,
                    source=parsed_price_source or "product_page",
                    page_type=page_type,
                    status="ok",
                    page_title=page_title,
                    error=None,
                    price_candidates=tuple(self._last_price_candidates),
                )

            if result_status in {"delivery_unavailable", "not_found_or_search_redirect"}:
                error_reason = None
            elif result_status in {"blocked", "network_blocked"}:
                error_reason = result_status
            else:
                error_reason = self._detect_error_reason(html, status_code=status_code)

            screenshot_path, html_path = self._save_debug_artifacts(page, product, html)
            candidates_path = self._save_price_candidates_artifact(product, page_type, final_url)
            self._log_page_debug(
                page,
                requested_url,
                html,
                result_status,
                web_lookup_id,
                page_type,
                parsed_price_source,
            )
            logger.warning(
                "Playwright could not parse price for %s: requested_url=%s web_lookup_id=%s final_url=%s page_type=%s status=%s parsed_price_source=%s error=%s. Debug saved to %s, %s%s",
                product.offer_id,
                requested_url,
                web_lookup_id,
                final_url,
                page_type,
                result_status,
                parsed_price_source,
                error_reason,
                screenshot_path,
                html_path,
                f", {candidates_path}" if candidates_path is not None else "",
            )
            return WebPriceInfo(
                offer_id=product.offer_id,
                product_id=product.product_id,
                sku=product.sku,
                web_lookup_id=web_lookup_id,
                url=final_url,
                final_url=final_url,
                buyer_visible_price=None,
                raw_price_text=None,
                other_bank_price=self._last_other_bank_price,
                old_price=self._last_old_price,
                source=parsed_price_source or page_type,
                page_type=page_type,
                status=result_status,
                page_title=page_title,
                error=error_reason,
                price_candidates=tuple(self._last_price_candidates),
            )
        except PlaywrightTimeoutError:
            logger.warning("Playwright timeout for %s", product.offer_id)
            self.close()
            return WebPriceInfo(
                offer_id=product.offer_id,
                product_id=product.product_id,
                sku=product.sku,
                web_lookup_id=web_lookup_id,
                url=requested_url,
                final_url=requested_url,
                buyer_visible_price=None,
                raw_price_text=None,
                other_bank_price=None,
                old_price=None,
                source="timeout",
                page_type="blocked_page",
                status="blocked",
                error="blocked",
                price_candidates=tuple(),
            )
        except Exception as exc:
            logger.exception("Playwright fetch failed for %s: %s", product.offer_id, exc)
            self.close()
            return WebPriceInfo(
                offer_id=product.offer_id,
                product_id=product.product_id,
                sku=product.sku,
                web_lookup_id=web_lookup_id,
                url=requested_url,
                final_url=requested_url,
                buyer_visible_price=None,
                raw_price_text=None,
                other_bank_price=None,
                old_price=None,
                source="exception",
                page_type="wrong_page",
                status="parse_error",
                error="parse_error",
                price_candidates=tuple(),
            )
