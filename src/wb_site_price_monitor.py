from __future__ import annotations

import ipaddress
import json
import re
import select
import socket
import socketserver
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import unescape
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote, urlsplit

from src.config.settings import settings
from src.tracked_products import TRACKED_PRODUCTS_PATH, load_tracked_products


WB_PRODUCT_URL_TEMPLATE = "https://www.wildberries.ru/catalog/{nm_id}/detail.aspx"
DEFAULT_TIMEOUT_MS = 30_000
RUB_CURRENCY = "RUB"
PRICE_QUANT = Decimal("0.01")
WB_HOMEPAGE_URL = "https://www.wildberries.ru/"
DEFAULT_BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
]
DEFAULT_BROWSER_CONTEXT_KWARGS = {
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "viewport": {"width": 1366, "height": 768},
    "locale": "ru-RU",
    "timezone_id": "Europe/Moscow",
}
HOMEPAGE_WAIT_MS = 3_000
PRODUCT_WAIT_MS = 5_000
INTERSTITIAL_RETRY_WAIT_MS = 12_000
DEFAULT_DEBUG_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "processed" / "wb_site_price_debug"

_TITLE_PRICE_RE = re.compile(r"купить\s+за\s+(.{1,24}?)(?:₽|руб)", re.IGNORECASE)
_HTML_PRICE_RE = re.compile(
    r"(?:final-price|wallet-price|price-block|sale-price|current-price|купить\s+за)"
    r"[\s\S]{0,120}?(.{1,24}?)(?:₽|руб)",
    re.IGNORECASE,
)

_PRICE_TEXT_RE = re.compile(r"(\d[\d\s]*(?:[.,]\d{1,2})?)")
_SALE_PRICE_U_RE = re.compile(r'"salePriceU"\s*:\s*(\d+)', re.IGNORECASE)
_PRICE_U_RE = re.compile(r'"priceU"\s*:\s*(\d+)', re.IGNORECASE)
_NO_STOCK_RE = re.compile(r"нет в наличии|скоро закончится|товар закончился", re.IGNORECASE)
_BLOCKED_RE = re.compile(r"captcha|доступ ограничен|access denied|forbidden", re.IGNORECASE)
_CAPTCHA_RE = re.compile(r"captcha|verify you are human|провер", re.IGNORECASE)
_INTERSTITIAL_RE = re.compile(r"Почти\s+готово|Подозрительная\s+активность|Пожалуйста,\s*подождите", re.IGNORECASE)


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_wb_product_url(nm_id: int) -> str:
    return WB_PRODUCT_URL_TEMPLATE.format(nm_id=int(nm_id))


@dataclass
class ProxyConfigDetails:
    raw_url: str | None
    scheme: str | None
    host: str | None
    port: int | None
    username: str | None
    password: str | None

    @property
    def auth_set(self) -> bool:
        return bool(self.username or self.password)

    @property
    def proxy_enabled(self) -> bool:
        return bool(self.raw_url)

    @property
    def bridge_required(self) -> bool:
        return bool(self.scheme and self.scheme.startswith("socks"))


@dataclass
class BrowserProxyRuntime:
    playwright_proxy_url: str | None
    bridge: "LocalProxyBridge | None"
    proxy_enabled: bool
    proxy_bridge_enabled: bool
    proxy_scheme: str | None
    proxy_auth_set: bool


def parse_proxy_config_details(proxy_url: str | None) -> ProxyConfigDetails:
    if not proxy_url:
        return ProxyConfigDetails(None, None, None, None, None, None)
    trimmed = str(proxy_url).strip()
    if not trimmed:
        return ProxyConfigDetails(None, None, None, None, None, None)
    if "://" not in trimmed:
        return ProxyConfigDetails(trimmed, None, trimmed, None, None, None)
    parsed = urlsplit(trimmed)
    return ProxyConfigDetails(
        raw_url=trimmed,
        scheme=(parsed.scheme or None),
        host=parsed.hostname,
        port=parsed.port,
        username=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
    )


def describe_proxy_configuration(proxy_url: str | None) -> dict[str, Any]:
    details = parse_proxy_config_details(proxy_url)
    return {
        "proxy_enabled": details.proxy_enabled,
        "proxy_bridge_enabled": details.bridge_required,
        "proxy_scheme": details.scheme,
        "proxy_auth_set": details.auth_set,
    }


class _BridgeTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, request_handler_class, *, bridge: "LocalProxyBridge") -> None:
        self.bridge = bridge
        super().__init__(server_address, request_handler_class)


class _BridgeRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(10)
        upstream = None
        try:
            host, port, leftover = self.server.bridge.read_connect_request(self.request)  # type: ignore[attr-defined]
            upstream = self.server.bridge.open_socks_tunnel(host, port)  # type: ignore[attr-defined]
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if leftover:
                upstream.sendall(leftover)
            self.server.bridge.relay(self.request, upstream)  # type: ignore[attr-defined]
        except Exception:
            if upstream is None:
                try:
                    self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                except Exception:
                    pass
        finally:
            if upstream is not None:
                try:
                    upstream.close()
                except Exception:
                    pass


class LocalProxyBridge:
    def __init__(self, proxy_url: str) -> None:
        details = parse_proxy_config_details(proxy_url)
        if not details.bridge_required or not details.host or not details.port:
            raise ValueError("SOCKS proxy bridge requires a valid socks proxy URL with host and port")
        self.details = details
        self._server: _BridgeTCPServer | None = None
        self._thread: threading.Thread | None = None
        self.local_proxy_url: str | None = None

    def start(self) -> str:
        if self._server is not None and self.local_proxy_url:
            return self.local_proxy_url
        server = _BridgeTCPServer(("127.0.0.1", 0), _BridgeRequestHandler, bridge=self)
        host, port = server.server_address
        self._server = server
        self.local_proxy_url = f"http://{host}:{port}"
        self._thread = threading.Thread(target=server.serve_forever, name="wb-site-price-proxy-bridge", daemon=True)
        self._thread.start()
        return self.local_proxy_url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.local_proxy_url = None

    def read_connect_request(self, client_socket: socket.socket) -> tuple[str, int, bytes]:
        buffer = bytearray()
        while b"\r\n\r\n" not in buffer:
            chunk = client_socket.recv(4096)
            if not chunk:
                raise RuntimeError("Proxy client closed before CONNECT request was fully read")
            buffer.extend(chunk)
            if len(buffer) > 65536:
                raise RuntimeError("Proxy client request headers too large")
        header_bytes, leftover = bytes(buffer).split(b"\r\n\r\n", 1)
        lines = header_bytes.decode("latin1").split("\r\n")
        request_line = lines[0]
        parts = request_line.split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            raise RuntimeError("Local proxy bridge only supports CONNECT requests")
        host, port = self._split_connect_target(parts[1])
        return host, port, leftover

    def _split_connect_target(self, target: str) -> tuple[str, int]:
        if target.startswith("[") and "]:" in target:
            host, port_text = target[1:].split("]:", 1)
            return host, int(port_text)
        if ":" not in target:
            raise RuntimeError("CONNECT target is missing port")
        host, port_text = target.rsplit(":", 1)
        return host, int(port_text)

    def open_socks_tunnel(self, target_host: str, target_port: int) -> socket.socket:
        upstream = socket.create_connection((str(self.details.host), int(self.details.port)), timeout=15)
        upstream.settimeout(15)
        methods = [0x00]
        if self.details.auth_set:
            methods.insert(0, 0x02)
        upstream.sendall(bytes([0x05, len(methods), *methods]))
        version, method = self._recv_exact(upstream, 2)
        if version != 0x05 or method == 0xFF:
            raise RuntimeError("SOCKS5 upstream rejected authentication methods")
        if method == 0x02:
            self._authenticate_socks5(upstream)
        elif method != 0x00:
            raise RuntimeError("SOCKS5 upstream selected unsupported auth method")

        request = self._build_socks_connect_request(target_host, target_port)
        upstream.sendall(request)
        response = self._recv_exact(upstream, 4)
        version, reply_code, _reserved, address_type = response
        if version != 0x05 or reply_code != 0x00:
            raise RuntimeError(f"SOCKS5 upstream connect failed with code {reply_code}")
        self._discard_socks_bound_address(upstream, address_type)
        upstream.settimeout(None)
        return upstream

    def _authenticate_socks5(self, upstream: socket.socket) -> None:
        username = (self.details.username or "").encode("utf-8")
        password = (self.details.password or "").encode("utf-8")
        if len(username) > 255 or len(password) > 255:
            raise RuntimeError("SOCKS5 username/password too long")
        payload = bytes([0x01, len(username)]) + username + bytes([len(password)]) + password
        upstream.sendall(payload)
        version, status = self._recv_exact(upstream, 2)
        if version != 0x01 or status != 0x00:
            raise RuntimeError("SOCKS5 upstream rejected username/password authentication")

    def _build_socks_connect_request(self, target_host: str, target_port: int) -> bytes:
        try:
            ip_obj = ipaddress.ip_address(target_host)
        except ValueError:
            host_bytes = target_host.encode("idna")
            if len(host_bytes) > 255:
                raise RuntimeError("CONNECT target host is too long for SOCKS5 domain encoding")
            return bytes([0x05, 0x01, 0x00, 0x03, len(host_bytes)]) + host_bytes + target_port.to_bytes(2, "big")

        if isinstance(ip_obj, ipaddress.IPv4Address):
            return bytes([0x05, 0x01, 0x00, 0x01]) + ip_obj.packed + target_port.to_bytes(2, "big")
        return bytes([0x05, 0x01, 0x00, 0x04]) + ip_obj.packed + target_port.to_bytes(2, "big")

    def _discard_socks_bound_address(self, upstream: socket.socket, address_type: int) -> None:
        if address_type == 0x01:
            to_read = 4
        elif address_type == 0x04:
            to_read = 16
        elif address_type == 0x03:
            domain_length = self._recv_exact(upstream, 1)[0]
            to_read = domain_length
        else:
            raise RuntimeError("SOCKS5 upstream returned unsupported address type")
        self._recv_exact(upstream, to_read + 2)

    def _recv_exact(self, sock: socket.socket, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                raise RuntimeError("Unexpected EOF while reading from SOCKS5 upstream")
            chunks.extend(chunk)
        return bytes(chunks)

    def relay(self, client_socket: socket.socket, upstream: socket.socket) -> None:
        client_socket.settimeout(None)
        sockets = [client_socket, upstream]
        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, 1.0)
            if exceptional:
                return
            for source in readable:
                data = source.recv(65536)
                if not data:
                    return
                destination = upstream if source is client_socket else client_socket
                destination.sendall(data)


def prepare_browser_proxy_runtime(proxy_url: str | None) -> BrowserProxyRuntime:
    details = parse_proxy_config_details(proxy_url)
    if not details.proxy_enabled:
        return BrowserProxyRuntime(None, None, False, False, None, False)
    if details.bridge_required:
        bridge = LocalProxyBridge(str(details.raw_url))
        local_proxy_url = bridge.start()
        return BrowserProxyRuntime(local_proxy_url, bridge, True, True, details.scheme, details.auth_set)
    return BrowserProxyRuntime(str(details.raw_url), None, True, False, details.scheme, details.auth_set)


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
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    return proxy


def build_browser_launch_kwargs(*, headless: bool, proxy_url: str | None) -> dict[str, Any]:
    launch_kwargs: dict[str, Any] = {
        "headless": bool(headless),
        "args": list(DEFAULT_BROWSER_ARGS),
    }
    proxy_config = build_playwright_proxy_config(proxy_url)
    if proxy_config:
        launch_kwargs["proxy"] = proxy_config
    return launch_kwargs


def build_browser_context_kwargs() -> dict[str, Any]:
    return dict(DEFAULT_BROWSER_CONTEXT_KWARGS)


def import_playwright_sync_api():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright as playwright_sync_playwright

    return PlaywrightTimeoutError, playwright_sync_playwright


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
    normalized_input = (
        unescape(str(value))
        .replace("\u00A0", " ")
        .replace("\u202F", " ")
    )
    match = _PRICE_TEXT_RE.search(normalized_input)
    if not match:
        return None
    normalized = re.sub(r"\s+", "", match.group(1)).replace(",", ".")
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


def _build_price_candidate(source: str, text: str, value: Decimal) -> dict[str, Any]:
    return {
        "source": source,
        "text": text,
        "value": str(value),
    }


def _append_candidate(candidates: list[dict[str, Any]], source: str, text: str | None, value: Decimal | None) -> None:
    if text in (None, "") or value is None:
        return
    candidate = _build_price_candidate(source, str(text), value)
    if candidate not in candidates:
        candidates.append(candidate)


def _extract_json_ld_price_candidates(html: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
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
                        _append_candidate(candidates, "json_ld", str(price_value), price)
                stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
            elif isinstance(item, list):
                stack.extend(item)
    return candidates


def _extract_embedded_json_price_candidates(html: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for matcher in (_SALE_PRICE_U_RE, _PRICE_U_RE):
        for match in matcher.finditer(html):
            raw_value = match.group(1)
            price = _parse_minor_units(raw_value)
            _append_candidate(candidates, "embedded_json", raw_value, price)
    return candidates


def _extract_title_price_candidates(title: str | None) -> list[dict[str, Any]]:
    if not title:
        return []
    candidates: list[dict[str, Any]] = []
    for match in _TITLE_PRICE_RE.finditer(title):
        raw_value = match.group(1)
        price = parse_price_text(raw_value)
        _append_candidate(candidates, "page_title", match.group(0), price)
    return candidates


def _extract_html_regex_price_candidates(html: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for match in _HTML_PRICE_RE.finditer(html):
        raw_value = match.group(1)
        price = parse_price_text(raw_value)
        _append_candidate(candidates, "html_regex", match.group(0), price)
    return candidates


def _extract_dom_price_candidates(page) -> list[dict[str, Any]]:
    if page is None:
        return []
    candidates: list[dict[str, Any]] = []
    selectors = [
        "main ins",
        "main .product-page__aside ins",
        "main .product-page__aside-price ins",
        "main .price-block ins",
        ".price-block__final-price",
        ".product-page__price-block .price-block__final-price",
        "main [class*='price-block'] [class*='final-price']",
    ]
    for selector in selectors:
        try:
            raw_text = page.locator(selector).first.text_content(timeout=1_000)
        except Exception:
            continue
        price = parse_price_text(raw_text)
        _append_candidate(candidates, "dom_selector", raw_text, price)
    return candidates


def extract_buyer_visible_price(page, html: str, title: str | None) -> tuple[Decimal | None, str | None, str | None, list[dict[str, Any]]]:
    ordered_candidates: list[dict[str, Any]] = []
    for group in (
        _extract_dom_price_candidates(page),
        _extract_json_ld_price_candidates(html),
        _extract_embedded_json_price_candidates(html),
        _extract_title_price_candidates(title),
        _extract_html_regex_price_candidates(html),
    ):
        ordered_candidates.extend(group)
    if not ordered_candidates:
        return None, None, None, []
    chosen = ordered_candidates[0]
    chosen_value = parse_price_text(chosen["value"])
    return chosen_value, str(chosen["text"]), str(chosen["source"]), ordered_candidates


def derive_availability_status(*, html: str, price: Decimal | None) -> str:
    if price is not None:
        return "available"
    if _NO_STOCK_RE.search(html):
        return "unavailable"
    return "unknown"


def html_contains_price_markers(html: str) -> bool:
    return any(
        marker in html
        for marker in (
            '"salePriceU"',
            '"priceU"',
            "application/ld+json",
            "final-price",
            "price-block",
            "wallet-price",
        )
    )


def capture_page_state(page) -> dict[str, Any]:
    state: dict[str, Any] = {
        "page_url_after_load": None,
        "page_title": None,
        "html": None,
    }
    try:
        state["page_url_after_load"] = getattr(page, "url", None)
    except Exception:
        pass
    try:
        state["page_title"] = page.title()
    except Exception:
        pass
    try:
        state["html"] = page.content()
    except Exception:
        pass
    return state


def build_page_diagnostics(*, target_url: str, current_url: str | None, title: str | None, html: str | None) -> dict[str, Any]:
    html_text = html or ""
    title_text = title or ""
    current_url_text = current_url or ""
    combined_text = " ".join(filter(None, [title_text, current_url_text, html_text[:4000]]))
    return {
        "page_url_after_load": current_url,
        "page_title": title,
        "blocked_detected": bool(_BLOCKED_RE.search(combined_text)),
        "captcha_detected": bool(_CAPTCHA_RE.search(combined_text)),
        "interstitial_detected": bool(_INTERSTITIAL_RE.search(combined_text)),
        "redirect_detected": bool(current_url and current_url != target_url),
        "html_contains_price_markers": html_contains_price_markers(html_text),
    }


def save_debug_artifacts(
    *,
    snapshot_date: str,
    nm_id: int,
    html: str | None,
    page,
    debug_output_dir: Path,
) -> tuple[str | None, str | None]:
    debug_output_dir.mkdir(parents=True, exist_ok=True)
    html_path = debug_output_dir / f"{snapshot_date}_{nm_id}.html"
    png_path = debug_output_dir / f"{snapshot_date}_{nm_id}.png"

    if html is not None:
        html_path.write_text(html, encoding="utf-8")
    try:
        page.screenshot(path=str(png_path), full_page=True)
    except Exception:
        png_path = None

    return (
        str(html_path) if html is not None else None,
        str(png_path) if png_path is not None else None,
    )


def build_failure_snapshot_row(
    target: dict[str, Any],
    *,
    snapshot_at: datetime,
    fetch_status: str,
    error: str,
    proxy_used: bool,
    raw_payload: dict[str, Any] | None = None,
    page_url_after_load: str | None = None,
    page_title: str | None = None,
    blocked_detected: bool = False,
    captcha_detected: bool = False,
    interstitial_detected: bool = False,
    redirect_detected: bool = False,
    html_contains_price_markers: bool = False,
    price_extract_source: str | None = None,
    price_candidates: list[dict[str, Any]] | None = None,
    debug_html_path: str | None = None,
    debug_png_path: str | None = None,
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
        "price_extract_source": price_extract_source,
        "availability_status": "unknown",
        "fetch_status": fetch_status,
        "error": error,
        "proxy_used": proxy_used,
        "raw_payload": raw_payload or {},
        "price_candidates": list(price_candidates or []),
        "page_url_after_load": page_url_after_load,
        "page_title": page_title,
        "blocked_detected": blocked_detected,
        "captcha_detected": captcha_detected,
        "interstitial_detected": interstitial_detected,
        "redirect_detected": redirect_detected,
        "html_contains_price_markers": html_contains_price_markers,
        "debug_html_path": debug_html_path,
        "debug_png_path": debug_png_path,
    }


def _load_product_page_state(
    page,
    *,
    url: str,
    timeout_ms: int,
) -> tuple[str | None, str, str | None, Decimal | None, str | None, str | None, list[dict[str, Any]], dict[str, Any]]:
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(PRODUCT_WAIT_MS)
    try:
        page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 10_000))
    except Exception:
        pass
    title = page.title()
    html = page.content()
    current_url = page.url
    price, raw_price_text, price_source, price_candidates = extract_buyer_visible_price(page, html, title)
    diagnostics = build_page_diagnostics(
        target_url=url,
        current_url=current_url,
        title=title,
        html=html,
    )
    return current_url, html, title, price, raw_price_text, price_source, price_candidates, diagnostics


def fetch_wb_site_price_snapshots_with_playwright(
    targets: Sequence[dict[str, Any]],
    *,
    headless: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    proxy_url: str | None = None,
    debug_artifacts: bool = False,
    debug_output_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    proxy_meta = describe_proxy_configuration(proxy_url)
    if not targets:
        return [], {
            "success": True,
            **proxy_meta,
            "region_detected": None,
            "fetch_status_counts": {},
        }

    try:
        PlaywrightTimeoutError, playwright_sync_playwright = import_playwright_sync_api()
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("Playwright is not installed for WB site price monitor") from exc

    results: list[dict[str, Any]] = []
    fetch_status_counts: dict[str, int] = {}
    region_detected: str | None = None
    proxy_used = bool(proxy_meta["proxy_enabled"])
    resolved_debug_output_dir = debug_output_dir or DEFAULT_DEBUG_OUTPUT_DIR
    proxy_runtime = prepare_browser_proxy_runtime(proxy_url)

    try:
        with playwright_sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                **build_browser_launch_kwargs(headless=headless, proxy_url=proxy_runtime.playwright_proxy_url)
            )
            context = browser.new_context(**build_browser_context_kwargs())
            page = context.new_page()
            try:
                for target in targets:
                    snapshot_at = utc_now()
                    snapshot_date_iso = snapshot_at.date().isoformat()
                    url = target.get("product_url") or build_wb_product_url(int(target["nm_id"]))
                    try:
                        home_response = page.goto(WB_HOMEPAGE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                        page.wait_for_timeout(HOMEPAGE_WAIT_MS)
                        if home_response is None:
                            raise RuntimeError("WB homepage did not return a response")

                        current_url, html, title, price, raw_price_text, price_source, price_candidates, diagnostics = _load_product_page_state(
                            page,
                            url=url,
                            timeout_ms=timeout_ms,
                        )
                        if diagnostics["interstitial_detected"] and price is None:
                            page.wait_for_timeout(INTERSTITIAL_RETRY_WAIT_MS)
                            current_url, html, title, price, raw_price_text, price_source, price_candidates, diagnostics = _load_product_page_state(
                                page,
                                url=url,
                                timeout_ms=timeout_ms,
                            )
                        if region_detected is None:
                            region_detected = None
                            try:
                                region_detected = page.locator("[data-link*='address']").first.text_content(timeout=1_000)
                            except Exception:
                                region_detected = None

                        blocked = diagnostics["blocked_detected"]
                        availability_status = derive_availability_status(html=html, price=price)
                        if blocked and price is None:
                            debug_html_path = None
                            debug_png_path = None
                            if debug_artifacts:
                                debug_html_path, debug_png_path = save_debug_artifacts(
                                    snapshot_date=snapshot_date_iso,
                                    nm_id=int(target["nm_id"]),
                                    html=html,
                                    page=page,
                                    debug_output_dir=resolved_debug_output_dir,
                                )
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
                                    "price_candidates": price_candidates,
                                    "site_region_text": region_detected,
                                },
                                price_extract_source=price_source,
                                price_candidates=price_candidates,
                                debug_html_path=debug_html_path,
                                debug_png_path=debug_png_path,
                                **diagnostics,
                            )
                        elif diagnostics["interstitial_detected"] and price is None:
                            debug_html_path = None
                            debug_png_path = None
                            if debug_artifacts:
                                debug_html_path, debug_png_path = save_debug_artifacts(
                                    snapshot_date=snapshot_date_iso,
                                    nm_id=int(target["nm_id"]),
                                    html=html,
                                    page=page,
                                    debug_output_dir=resolved_debug_output_dir,
                                )
                            row = build_failure_snapshot_row(
                                target,
                                snapshot_at=snapshot_at,
                                fetch_status="wb_interstitial",
                                error="wb_interstitial_wait",
                                proxy_used=proxy_used,
                                raw_payload={
                                    "title": title,
                                    "current_url": current_url,
                                    "price_source": price_source,
                                    "price_candidates": price_candidates,
                                    "site_region_text": region_detected,
                                    "availability_status": availability_status,
                                },
                                price_extract_source=price_source,
                                price_candidates=price_candidates,
                                debug_html_path=debug_html_path,
                                debug_png_path=debug_png_path,
                                **diagnostics,
                            )
                            row["availability_status"] = availability_status
                        elif price is None:
                            debug_html_path = None
                            debug_png_path = None
                            if debug_artifacts:
                                debug_html_path, debug_png_path = save_debug_artifacts(
                                    snapshot_date=snapshot_date_iso,
                                    nm_id=int(target["nm_id"]),
                                    html=html,
                                    page=page,
                                    debug_output_dir=resolved_debug_output_dir,
                                )
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
                                    "price_candidates": price_candidates,
                                    "site_region_text": region_detected,
                                    "availability_status": availability_status,
                                },
                                price_extract_source=price_source,
                                price_candidates=price_candidates,
                                debug_html_path=debug_html_path,
                                debug_png_path=debug_png_path,
                                **diagnostics,
                            )
                            row["availability_status"] = availability_status
                        else:
                            row = {
                                "snapshot_at": snapshot_at.isoformat(),
                                "snapshot_date": snapshot_date_iso,
                                "nm_id": int(target["nm_id"]),
                                "item_label": target.get("item_label"),
                                "lifecycle_status": target.get("lifecycle_status"),
                                "product_url": current_url or url,
                                "buyer_visible_price": str(price),
                                "currency": RUB_CURRENCY,
                                "price_text_raw": raw_price_text,
                                "price_extract_source": price_source,
                                "availability_status": availability_status,
                                "fetch_status": "success",
                                "error": None,
                                "proxy_used": proxy_used,
                                "price_candidates": price_candidates,
                                "raw_payload": {
                                    "title": title,
                                    "current_url": current_url,
                                    "price_source": price_source,
                                    "price_candidates": price_candidates,
                                    "site_region_text": region_detected,
                                },
                                **diagnostics,
                                "debug_html_path": None,
                                "debug_png_path": None,
                            }
                    except PlaywrightTimeoutError:
                        page_state = capture_page_state(page)
                        diagnostics = build_page_diagnostics(
                            target_url=url,
                            current_url=page_state.get("page_url_after_load"),
                            title=page_state.get("page_title"),
                            html=page_state.get("html"),
                        )
                        debug_html_path = None
                        debug_png_path = None
                        if debug_artifacts:
                            debug_html_path, debug_png_path = save_debug_artifacts(
                                snapshot_date=snapshot_date_iso,
                                nm_id=int(target["nm_id"]),
                                html=page_state.get("html"),
                                page=page,
                                debug_output_dir=resolved_debug_output_dir,
                            )
                        row = build_failure_snapshot_row(
                            target,
                            snapshot_at=snapshot_at,
                            fetch_status="timeout",
                            error="page_timeout",
                            proxy_used=proxy_used,
                            raw_payload={"target_url": url},
                            debug_html_path=debug_html_path,
                            debug_png_path=debug_png_path,
                            **diagnostics,
                        )
                    except Exception as exc:  # pragma: no cover - defensive branch
                        page_state = capture_page_state(page)
                        diagnostics = build_page_diagnostics(
                            target_url=url,
                            current_url=page_state.get("page_url_after_load"),
                            title=page_state.get("page_title"),
                            html=page_state.get("html"),
                        )
                        debug_html_path = None
                        debug_png_path = None
                        if debug_artifacts:
                            debug_html_path, debug_png_path = save_debug_artifacts(
                                snapshot_date=snapshot_date_iso,
                                nm_id=int(target["nm_id"]),
                                html=page_state.get("html"),
                                page=page,
                                debug_output_dir=resolved_debug_output_dir,
                            )
                        row = build_failure_snapshot_row(
                            target,
                            snapshot_at=snapshot_at,
                            fetch_status="failed",
                            error=str(exc),
                            proxy_used=proxy_used,
                            raw_payload={"target_url": url},
                            debug_html_path=debug_html_path,
                            debug_png_path=debug_png_path,
                            **diagnostics,
                        )

                    fetch_status = str(row["fetch_status"])
                    fetch_status_counts[fetch_status] = fetch_status_counts.get(fetch_status, 0) + 1
                    results.append(row)
            finally:
                context.close()
                browser.close()
    finally:
        if proxy_runtime.bridge is not None:
            proxy_runtime.bridge.stop()

    return results, {
        "success": True,
        **proxy_meta,
        "region_detected": region_detected,
        "fetch_status_counts": fetch_status_counts,
    }


def resolve_proxy_url(explicit_proxy_url: str | None = None) -> str | None:
    return explicit_proxy_url if explicit_proxy_url is not None else settings.wb_site_price_proxy_url
