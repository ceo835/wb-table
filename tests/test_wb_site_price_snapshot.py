from __future__ import annotations

import io
import socket
import threading
from datetime import date
from pathlib import Path

from scripts.load_wb_site_price_snapshot import emit_summary_json
from src.db.stock_warehouse_loader import build_wb_warehouse_stock_payload
from src.db.wb_site_price_loader import (
    ALERT_STATUS_OK,
    ALERT_STATUS_PRICE_CHANGED_50,
    FETCH_STATUS_WB_INTERSTITIAL,
    build_wb_site_price_alert_rows,
    load_wb_site_price_snapshot,
    prepare_fact_wb_site_price_snapshot_upsert_rows,
    upsert_wb_site_price_alert,
    upsert_wb_site_price_snapshot,
)
from src.wb_site_price_monitor import (
    LocalProxyBridge,
    build_browser_launch_kwargs,
    build_browser_context_kwargs,
    build_playwright_proxy_config,
    describe_proxy_configuration,
    fetch_wb_site_price_snapshots_with_playwright,
    load_price_monitor_targets,
    parse_price_text,
    prepare_browser_proxy_runtime,
)


def test_load_price_monitor_targets_uses_only_tracked_products(tmp_path: Path) -> None:
    tracked_path = tmp_path / "tracked_products.csv"
    tracked_path.write_text(
        "\n".join(
            [
                "nm_id,item_label,is_tracked,lifecycle_status,source",
                "197330807,BlackWOM5,true,active,test",
                "37320545,ЧББ,false,sellout,test",
                "91470767,avokadogirl,true,sellout,test",
            ]
        ),
        encoding="utf-8",
    )

    targets = load_price_monitor_targets(tracked_path=tracked_path)

    assert [target["nm_id"] for target in targets] == [197330807, 91470767]
    assert targets[0]["product_url"].endswith("/197330807/detail.aspx")


def test_parse_price_text_supports_thousand_separators_and_html_nbsp() -> None:
    assert str(parse_price_text("799 ₽")) == "799.00"
    assert str(parse_price_text("1 022 ₽")) == "1022.00"
    assert str(parse_price_text("1&nbsp;022&nbsp;₽")) == "1022.00"
    assert str(parse_price_text("1\u00A0190 ₽")) == "1190.00"
    assert str(parse_price_text("wallet-price red-price\">1\u202F125\u202F₽")) == "1125.00"


def test_build_playwright_proxy_config_isolated_to_site_bot() -> None:
    proxy_url = "http://user:pass@127.0.0.1:8080"

    proxy = build_playwright_proxy_config(proxy_url)
    launch_kwargs = build_browser_launch_kwargs(headless=True, proxy_url=proxy_url)
    wb_api_payload = build_wb_warehouse_stock_payload(snapshot_date=date(2026, 6, 17), limit=100, offset=0, nm_ids=[1])

    assert proxy == {
        "server": "http://127.0.0.1:8080",
        "username": "user",
        "password": "pass",
    }
    assert launch_kwargs["proxy"] == proxy
    assert "proxy" not in wb_api_payload


def test_build_playwright_proxy_config_decodes_credentials_for_socks5() -> None:
    proxy_url = "socks5://user%40name:pa%24%24@127.0.0.1:1080"

    proxy = build_playwright_proxy_config(proxy_url)

    assert proxy == {
        "server": "socks5://127.0.0.1:1080",
        "username": "user@name",
        "password": "pa$$",
    }


def test_prepare_browser_proxy_runtime_enables_local_bridge_for_socks5_with_auth() -> None:
    runtime = prepare_browser_proxy_runtime("socks5://user%40name:pa%24%24@127.0.0.1:1080")

    try:
        assert runtime.proxy_enabled is True
        assert runtime.proxy_bridge_enabled is True
        assert runtime.proxy_scheme == "socks5"
        assert runtime.proxy_auth_set is True
        assert runtime.playwright_proxy_url is not None
        assert runtime.playwright_proxy_url.startswith("http://127.0.0.1:")
        assert runtime.bridge is not None
        assert describe_proxy_configuration("socks5://user%40name:pa%24%24@127.0.0.1:1080") == {
            "proxy_enabled": True,
            "proxy_bridge_enabled": True,
            "proxy_scheme": "socks5",
            "proxy_auth_set": True,
        }
    finally:
        if runtime.bridge is not None:
            runtime.bridge.stop()


def test_local_proxy_bridge_tunnels_connect_through_authenticated_socks5() -> None:
    accepted: dict[str, object] = {}
    ready = threading.Event()

    def fake_socks5_server(server_socket: socket.socket) -> None:
        ready.set()
        conn, _addr = server_socket.accept()
        with conn:
            greeting = conn.recv(4)
            accepted["greeting"] = greeting
            conn.sendall(b"\x05\x02")
            auth_header = conn.recv(2)
            username_len = auth_header[1]
            username = conn.recv(username_len)
            password_len = conn.recv(1)[0]
            password = conn.recv(password_len)
            accepted["username"] = username.decode("utf-8")
            accepted["password"] = password.decode("utf-8")
            conn.sendall(b"\x01\x00")

            request_header = conn.recv(5)
            domain_len = request_header[4]
            domain = conn.recv(domain_len)
            port_bytes = conn.recv(2)
            accepted["target_host"] = domain.decode("ascii")
            accepted["target_port"] = int.from_bytes(port_bytes, "big")
            conn.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x1f\x90")

            payload = conn.recv(4)
            accepted["payload"] = payload
            conn.sendall(payload)

    upstream_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    upstream_server.bind(("127.0.0.1", 0))
    upstream_server.listen(1)
    upstream_host, upstream_port = upstream_server.getsockname()
    upstream_thread = threading.Thread(target=fake_socks5_server, args=(upstream_server,), daemon=True)
    upstream_thread.start()
    ready.wait(timeout=2)

    bridge = LocalProxyBridge(f"socks5://user:pass@{upstream_host}:{upstream_port}")
    local_url = bridge.start()
    local_host_port = local_url.removeprefix("http://")
    local_host, local_port = local_host_port.split(":")

    try:
        with socket.create_connection((local_host, int(local_port)), timeout=5) as client:
            client.sendall(
                b"CONNECT example.com:443 HTTP/1.1\r\n"
                b"Host: example.com:443\r\n"
                b"Proxy-Connection: Keep-Alive\r\n\r\n"
            )
            response = client.recv(1024)
            assert b"200 Connection Established" in response
            client.sendall(b"ping")
            echoed = client.recv(4)
            assert echoed == b"ping"
    finally:
        bridge.stop()
        upstream_server.close()
        upstream_thread.join(timeout=2)

    assert accepted["username"] == "user"
    assert accepted["password"] == "pass"
    assert accepted["target_host"] == "example.com"
    assert accepted["target_port"] == 443
    assert accepted["payload"] == b"ping"


def test_build_browser_launch_kwargs_uses_old_bot_hardening_flags() -> None:
    launch_kwargs = build_browser_launch_kwargs(
        headless=True,
        proxy_url="http://user:pass@127.0.0.1:8080",
    )

    assert launch_kwargs["headless"] is True
    assert "--disable-blink-features=AutomationControlled" in launch_kwargs["args"]
    assert "--no-sandbox" in launch_kwargs["args"]


def test_build_browser_context_kwargs_uses_old_bot_context_defaults() -> None:
    context_kwargs = build_browser_context_kwargs()

    assert context_kwargs["locale"] == "ru-RU"
    assert context_kwargs["timezone_id"] == "Europe/Moscow"
    assert context_kwargs["viewport"] == {"width": 1366, "height": 768}
    assert "Chrome/124.0.0.0" in context_kwargs["user_agent"]


def test_build_wb_site_price_alert_rows_marks_changes_from_50_rub() -> None:
    alert_rows = build_wb_site_price_alert_rows(
        [
            {
                "snapshot_date": date(2026, 6, 17),
                "nm_id": 197330807,
                "buyer_visible_price": "1299.00",
                "fetch_status": "success",
            },
            {
                "snapshot_date": date(2026, 6, 17),
                "nm_id": 37320545,
                "buyer_visible_price": "1210.00",
                "fetch_status": "success",
            },
        ],
        {
            197330807: 1200,
            37320545: 1190,
        },
    )

    assert len(alert_rows) == 1
    assert alert_rows[0]["alert_status"] == ALERT_STATUS_PRICE_CHANGED_50
    assert str(alert_rows[0]["price_delta"]) == "99.00"


def test_build_wb_site_price_alert_rows_skips_rows_without_success_price() -> None:
    alert_rows = build_wb_site_price_alert_rows(
        [
            {
                "snapshot_date": date(2026, 6, 17),
                "nm_id": 91470767,
                "buyer_visible_price": None,
                "fetch_status": FETCH_STATUS_WB_INTERSTITIAL,
            },
            {
                "snapshot_date": date(2026, 6, 17),
                "nm_id": 37320545,
                "buyer_visible_price": None,
                "fetch_status": "no_price_data",
            },
        ],
        {},
    )

    assert alert_rows == []


def test_prepare_snapshot_rows_do_not_create_fake_price_on_error() -> None:
    rows = prepare_fact_wb_site_price_snapshot_upsert_rows(
        [
            {
                "snapshot_at": "2026-06-17T08:00:00+00:00",
                "snapshot_date": "2026-06-17",
                "nm_id": 197330807,
                "item_label": "BlackWOM5",
                "lifecycle_status": "active",
                "product_url": "https://www.wildberries.ru/catalog/197330807/detail.aspx",
                "buyer_visible_price": None,
                "currency": None,
                "price_text_raw": None,
                "availability_status": "unknown",
                "fetch_status": "failed",
                "error": "blocked",
                "proxy_used": True,
                "raw_payload": {"reason": "blocked"},
            }
        ]
    )

    assert rows[0]["buyer_visible_price"] is None
    assert rows[0]["fetch_status"] == "failed"


def test_load_wb_site_price_snapshot_writes_snapshot_and_alert_rows(monkeypatch, tmp_path: Path) -> None:
    state: dict[str, object] = {
        "snapshot_rows": None,
        "alert_rows": None,
    }

    monkeypatch.setattr(
        "src.db.wb_site_price_loader.load_price_monitor_targets",
        lambda **kwargs: [
            {
                "nm_id": 197330807,
                "item_label": "BlackWOM5",
                "lifecycle_status": "active",
                "product_url": "https://www.wildberries.ru/catalog/197330807/detail.aspx",
            }
        ],
    )

    class FakeSession:
        pass

    class FakeSessionScope:
        def __enter__(self):
            return FakeSession()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("src.db.wb_site_price_loader.session_scope", lambda: FakeSessionScope())
    monkeypatch.setattr(
        "src.db.wb_site_price_loader.fetch_previous_success_price_lookup",
        lambda *args, **kwargs: {197330807: 1200},
    )

    def fake_upsert_snapshot(_session, rows):
        state["snapshot_rows"] = rows
        return len(rows)

    def fake_upsert_alert(_session, rows):
        state["alert_rows"] = rows
        return len(rows)

    monkeypatch.setattr("src.db.wb_site_price_loader.upsert_wb_site_price_snapshot", fake_upsert_snapshot)
    monkeypatch.setattr("src.db.wb_site_price_loader.upsert_wb_site_price_alert", fake_upsert_alert)

    def fake_fetcher(targets, **kwargs):
        return (
            [
                {
                    "snapshot_at": "2026-06-17T08:00:00+00:00",
                    "snapshot_date": "2026-06-17",
                    "nm_id": 197330807,
                    "item_label": "BlackWOM5",
                    "lifecycle_status": "active",
                "product_url": targets[0]["product_url"],
                "buyer_visible_price": "1299.00",
                "currency": "RUB",
                "price_text_raw": "1 299 ₽",
                "price_extract_source": "json_ld",
                "availability_status": "available",
                "fetch_status": "success",
                "error": None,
                "proxy_used": True,
                "price_candidates": [
                    {
                        "source": "json_ld",
                        "text": "1299",
                        "value": "1299.00",
                    }
                ],
                "raw_payload": {"price_source": "salePriceU"},
            }
        ],
            {
                "success": True,
                "proxy_enabled": True,
                "region_detected": "Алматы",
                "fetch_status_counts": {"success": 1},
            },
        )

    summary = load_wb_site_price_snapshot(
        tracked_products=True,
        snapshot_date=date(2026, 6, 17),
        write_db=True,
        output_dir=tmp_path,
        fetcher=fake_fetcher,
        proxy_url="http://proxy.local:8080",
    )

    assert summary["success"] is True
    assert summary["success_count"] == 1
    assert summary["alerts_count"] == 1
    assert summary["rows_upserted"] == 1
    assert summary["alerts_upserted"] == 1
    assert state["snapshot_rows"] is not None
    assert state["alert_rows"] is not None
    assert summary["summary_path"]
    saved = Path(summary["summary_path"])
    assert saved.exists()
    saved_text = saved.read_text(encoding="utf-8")
    assert '"summary_path": ""' not in saved_text
    assert summary["items"][0]["nm_id"] == 197330807
    assert summary["items"][0]["fetch_status"] == "success"
    assert summary["items"][0]["price_extract_source"] == "json_ld"
    assert summary["items"][0]["price_candidates"][0]["source"] == "json_ld"


def test_load_wb_site_price_snapshot_keeps_rows_upserted_zero_without_db(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "src.db.wb_site_price_loader.load_price_monitor_targets",
        lambda tracked_path, nm_ids=None, limit=None: [
            {
                "nm_id": 91744473,
                "item_label": "Мишки дети",
                "lifecycle_status": "active",
                "product_url": "https://www.wildberries.ru/catalog/91744473/detail.aspx",
            }
        ],
    )

    def fake_fetcher(*args, **kwargs):
        return (
            [
                {
                    "snapshot_at": "2026-06-17T08:00:00+00:00",
                    "snapshot_date": "2026-06-17",
                    "nm_id": 91744473,
                    "item_label": "Мишки дети",
                    "lifecycle_status": "active",
                    "product_url": "https://www.wildberries.ru/catalog/91744473/detail.aspx",
                    "fetch_status": "success",
                    "buyer_visible_price": "1022.00",
                    "price_text_raw": "1&nbsp;022&nbsp;₽",
                    "price_extract_source": "html_regex",
                    "availability_status": "in_stock",
                    "error": "",
                    "raw_payload": {},
                    "price_candidates": [{"source": "html_regex", "text": "1&nbsp;022&nbsp;₽", "value": "1022.00"}],
                }
            ],
            {"fetch_status_counts": {"success": 1}, "proxy_enabled": False},
        )

    summary = load_wb_site_price_snapshot(
        tracked_products=True,
        output_dir=tmp_path,
        write_db=False,
        fetcher=fake_fetcher,
    )

    assert summary["success"] is True
    assert summary["rows_upserted"] == 0
    assert summary["success_count"] == 1


def test_upsert_wb_site_price_snapshot_falls_back_when_driver_returns_negative_rowcount(monkeypatch) -> None:
    monkeypatch.setattr("src.db.wb_site_price_loader.upsert_rows", lambda *args, **kwargs: -1)

    result = upsert_wb_site_price_snapshot(
        session=None,
        rows=[
            {
                "snapshot_at": "2026-06-17T08:00:00+00:00",
                "snapshot_date": "2026-06-17",
                "nm_id": 91744473,
                "item_label": "Мишки дети",
                "product_url": "https://www.wildberries.ru/catalog/91744473/detail.aspx",
                "fetch_status": "success",
                "buyer_visible_price": "1022.00",
                "availability_status": "in_stock",
            }
        ],
    )

    assert result == 1


def test_upsert_wb_site_price_alert_falls_back_when_driver_returns_negative_rowcount(monkeypatch) -> None:
    monkeypatch.setattr("src.db.wb_site_price_loader.upsert_rows", lambda *args, **kwargs: -1)

    result = upsert_wb_site_price_alert(
        session=None,
        rows=[
            {
                "snapshot_date": date(2026, 6, 17),
                "nm_id": 91744473,
                "alert_status": ALERT_STATUS_OK,
                "current_price": "1022.00",
                "previous_success_price": None,
                "price_delta": None,
            }
        ],
    )

    assert result == 1


def test_emit_summary_json_falls_back_to_utf8_buffer_for_non_ascii_output() -> None:
    class FakeStdout:
        def __init__(self) -> None:
            self.buffer = io.BytesIO()

        def write(self, value: str) -> int:
            if "₽" in value:
                raise UnicodeEncodeError("charmap", value, 0, 1, "cannot encode")
            return len(value)

    stream = FakeStdout()

    emit_summary_json({"price_text_raw": "799 ₽"}, stdout=stream)

    payload = stream.buffer.getvalue().decode("utf-8")
    assert '"price_text_raw": "799 ₽"' in payload


def test_fetch_wb_site_price_snapshots_with_playwright_uses_homepage_then_product(monkeypatch) -> None:
    goto_calls: list[tuple[str, str, int]] = []
    wait_calls: list[int] = []
    closed: dict[str, bool] = {
        "context": False,
        "browser": False,
    }

    class FakePage:
        url = "https://www.wildberries.ru/catalog/197330807/detail.aspx"

        def goto(self, url, wait_until, timeout):
            goto_calls.append((url, wait_until, timeout))

            class FakeResponse:
                status = 200

            return FakeResponse()

        def wait_for_timeout(self, milliseconds):
            wait_calls.append(milliseconds)

        def title(self):
            return "Карточка товара"

        def content(self):
            return '<html><script type="application/ld+json">{"offers":{"price":"1299"}}</script></html>'

        class _Locator:
            def first(self):
                return self

            def text_content(self, timeout):
                return "Алматы"

        def locator(self, _selector):
            return self._Locator()

    class FakeContext:
        def new_page(self):
            return FakePage()

        def close(self):
            closed["context"] = True

    class FakeBrowser:
        def __init__(self):
            self.launch_kwargs = None
            self.context_kwargs = None

        def new_context(self, **kwargs):
            self.context_kwargs = kwargs
            return FakeContext()

        def close(self):
            closed["browser"] = True

    fake_browser = FakeBrowser()

    class FakeChromium:
        def launch(self, **kwargs):
            fake_browser.launch_kwargs = kwargs
            return fake_browser

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeTimeoutError(Exception):
        pass

    monkeypatch.setattr(
        "src.wb_site_price_monitor.import_playwright_sync_api",
        lambda: (FakeTimeoutError, lambda: FakeManager()),
    )

    results, meta = fetch_wb_site_price_snapshots_with_playwright(
        [
            {
                "nm_id": 197330807,
                "item_label": "BlackWOM5",
                "lifecycle_status": "active",
                "product_url": "https://www.wildberries.ru/catalog/197330807/detail.aspx",
            }
        ],
        proxy_url="http://user:pass@127.0.0.1:8080",
        timeout_ms=60_000,
    )

    assert results[0]["fetch_status"] == "success"
    assert results[0]["buyer_visible_price"] == "1299.00"
    assert meta["proxy_enabled"] is True
    assert goto_calls[0][0] == "https://www.wildberries.ru/"
    assert goto_calls[1][0].endswith("/197330807/detail.aspx")
    assert wait_calls == [3_000, 5_000]
    assert "--disable-blink-features=AutomationControlled" in fake_browser.launch_kwargs["args"]
    assert fake_browser.context_kwargs["locale"] == "ru-RU"
    assert closed["context"] is True
    assert closed["browser"] is True


def test_fetch_wb_site_price_snapshots_with_playwright_prefers_dom_selector_price(monkeypatch) -> None:
    class FakePage:
        url = "https://www.wildberries.ru/catalog/197330807/detail.aspx"

        def goto(self, url, wait_until, timeout):
            class FakeResponse:
                status = 200

            return FakeResponse()

        def wait_for_timeout(self, milliseconds):
            return None

        def wait_for_load_state(self, state, timeout):
            return None

        def title(self):
            return "Карточка товара купить за 799 ₽"

        def content(self):
            return "<html><body><div>no embedded price</div></body></html>"

        class _Locator:
            def __init__(self, selector: str):
                self.selector = selector

            @property
            def first(self):
                return self

            def text_content(self, timeout):
                if "address" in self.selector:
                    return "Алматы"
                if self.selector == "main ins":
                    return "1 599 ₽"
                raise RuntimeError("selector not found")

        def locator(self, selector):
            return self._Locator(selector)

    class FakeContext:
        def new_page(self):
            return FakePage()

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self, **kwargs):
            return FakeContext()

        def close(self):
            return None

    class FakeChromium:
        def launch(self, **kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeTimeoutError(Exception):
        pass

    monkeypatch.setattr(
        "src.wb_site_price_monitor.import_playwright_sync_api",
        lambda: (FakeTimeoutError, lambda: FakeManager()),
    )

    rows, meta = fetch_wb_site_price_snapshots_with_playwright(
        [
            {
                "nm_id": 197330807,
                "item_label": "BlackWOM5",
                "lifecycle_status": "active",
                "product_url": "https://www.wildberries.ru/catalog/197330807/detail.aspx",
            }
        ]
    )

    assert meta["fetch_status_counts"] == {"success": 1}
    assert rows[0]["fetch_status"] == "success"
    assert rows[0]["buyer_visible_price"] == "1599.00"
    assert rows[0]["price_text_raw"] == "1 599 ₽"
    assert rows[0]["price_extract_source"] == "dom_selector"
    assert rows[0]["price_candidates"][0]["source"] == "dom_selector"


def test_fetch_wb_site_price_snapshots_with_playwright_falls_back_to_page_title_price(monkeypatch) -> None:
    class FakePage:
        url = "https://www.wildberries.ru/catalog/91470767/detail.aspx"

        def goto(self, url, wait_until, timeout):
            class FakeResponse:
                status = 200

            return FakeResponse()

        def wait_for_timeout(self, milliseconds):
            return None

        def wait_for_load_state(self, state, timeout):
            return None

        def title(self):
            return "Трусы детские подростковые, набор 5 шт купить за 799 ₽ в интернет-магазине Wildberries"

        def content(self):
            return "<html><body><div>plain content without embedded price</div></body></html>"

        class _Locator:
            def __init__(self, selector: str):
                self.selector = selector

            @property
            def first(self):
                return self

            def text_content(self, timeout):
                if "address" in self.selector:
                    return "Алматы"
                raise RuntimeError("selector not found")

        def locator(self, selector):
            return self._Locator(selector)

    class FakeContext:
        def new_page(self):
            return FakePage()

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self, **kwargs):
            return FakeContext()

        def close(self):
            return None

    class FakeChromium:
        def launch(self, **kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeTimeoutError(Exception):
        pass

    monkeypatch.setattr(
        "src.wb_site_price_monitor.import_playwright_sync_api",
        lambda: (FakeTimeoutError, lambda: FakeManager()),
    )

    rows, meta = fetch_wb_site_price_snapshots_with_playwright(
        [
            {
                "nm_id": 91470767,
                "item_label": "avokadogirl",
                "lifecycle_status": "active",
                "product_url": "https://www.wildberries.ru/catalog/91470767/detail.aspx",
            }
        ]
    )

    assert meta["fetch_status_counts"] == {"success": 1}
    assert rows[0]["fetch_status"] == "success"
    assert rows[0]["buyer_visible_price"] == "799.00"
    assert rows[0]["price_extract_source"] == "page_title"
    assert rows[0]["price_candidates"][0]["source"] == "page_title"
    assert "799 ₽" in rows[0]["price_text_raw"]


def test_fetch_wb_site_price_snapshots_with_playwright_saves_debug_artifacts_for_failed_rows(
    monkeypatch, tmp_path: Path
) -> None:
    class FakePage:
        url = "https://www.wildberries.ru/captcha"

        def goto(self, url, wait_until, timeout):
            class FakeResponse:
                status = 200

            return FakeResponse()

        def wait_for_timeout(self, milliseconds):
            return None

        def wait_for_load_state(self, state, timeout):
            return None

        def title(self):
            return "Access denied"

        def content(self):
            return "<html>captcha access denied</html>"

        class _Locator:
            def first(self):
                return self

            def text_content(self, timeout):
                raise RuntimeError("no region")

        def locator(self, _selector):
            return self._Locator()

        def screenshot(self, path, full_page=True):
            Path(path).write_bytes(b"fake-png")

    class FakeContext:
        def new_page(self):
            return FakePage()

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self, **kwargs):
            return FakeContext()

        def close(self):
            return None

    class FakeChromium:
        def launch(self, **kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeTimeoutError(Exception):
        pass

    monkeypatch.setattr(
        "src.wb_site_price_monitor.import_playwright_sync_api",
        lambda: (FakeTimeoutError, lambda: FakeManager()),
    )

    rows, meta = fetch_wb_site_price_snapshots_with_playwright(
        [
            {
                "nm_id": 91470767,
                "item_label": "avokadogirl",
                "lifecycle_status": "active",
                "product_url": "https://www.wildberries.ru/catalog/91470767/detail.aspx",
            }
        ],
        debug_artifacts=True,
        debug_output_dir=tmp_path,
    )

    assert rows[0]["fetch_status"] == "blocked"
    assert rows[0]["blocked_detected"] is True
    assert rows[0]["captcha_detected"] is True
    assert rows[0]["redirect_detected"] is True
    assert rows[0]["debug_html_path"]
    assert rows[0]["debug_png_path"]
    assert Path(rows[0]["debug_html_path"]).exists()
    assert Path(rows[0]["debug_png_path"]).exists()
    assert meta["fetch_status_counts"] == {"blocked": 1}


def test_fetch_wb_site_price_snapshots_with_playwright_marks_interstitial_and_retries_once(monkeypatch) -> None:
    class FakePage:
        url = "https://www.wildberries.ru/catalog/91470767/detail.aspx"

        def __init__(self):
            self.product_goto_calls = 0

        def goto(self, url, wait_until, timeout):
            if "detail.aspx" in url:
                self.product_goto_calls += 1
                self.url = url

            class FakeResponse:
                status = 200

            return FakeResponse()

        def wait_for_timeout(self, milliseconds):
            return None

        def wait_for_load_state(self, state, timeout):
            return None

        def title(self):
            return "Почти готово..."

        def content(self):
            return "<html><body>Подозрительная активность. Пожалуйста, подождите.</body></html>"

        class _Locator:
            def __init__(self, selector: str):
                self.selector = selector

            @property
            def first(self):
                return self

            def text_content(self, timeout):
                raise RuntimeError("no region")

        def locator(self, selector):
            return self._Locator(selector)

    fake_page = FakePage()

    class FakeContext:
        def new_page(self):
            return fake_page

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self, **kwargs):
            return FakeContext()

        def close(self):
            return None

    class FakeChromium:
        def launch(self, **kwargs):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeTimeoutError(Exception):
        pass

    monkeypatch.setattr(
        "src.wb_site_price_monitor.import_playwright_sync_api",
        lambda: (FakeTimeoutError, lambda: FakeManager()),
    )

    rows, meta = fetch_wb_site_price_snapshots_with_playwright(
        [
            {
                "nm_id": 91470767,
                "item_label": "avokadogirl",
                "lifecycle_status": "active",
                "product_url": "https://www.wildberries.ru/catalog/91470767/detail.aspx",
            }
        ]
    )

    assert fake_page.product_goto_calls == 2
    assert rows[0]["fetch_status"] == FETCH_STATUS_WB_INTERSTITIAL
    assert rows[0]["error"] == "wb_interstitial_wait"
    assert meta["fetch_status_counts"] == {FETCH_STATUS_WB_INTERSTITIAL: 1}
