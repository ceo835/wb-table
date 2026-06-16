from __future__ import annotations

from datetime import date
from pathlib import Path

from src.db.stock_warehouse_loader import build_wb_warehouse_stock_payload
from src.db.wb_site_price_loader import (
    ALERT_STATUS_OK,
    ALERT_STATUS_PRICE_CHANGED_50,
    build_wb_site_price_alert_rows,
    load_wb_site_price_snapshot,
    prepare_fact_wb_site_price_snapshot_upsert_rows,
)
from src.wb_site_price_monitor import (
    build_browser_launch_kwargs,
    build_playwright_proxy_config,
    load_price_monitor_targets,
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

    assert alert_rows[0]["alert_status"] == ALERT_STATUS_PRICE_CHANGED_50
    assert str(alert_rows[0]["price_delta"]) == "99.00"
    assert alert_rows[1]["alert_status"] == ALERT_STATUS_OK


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
                    "availability_status": "available",
                    "fetch_status": "success",
                    "error": None,
                    "proxy_used": True,
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
