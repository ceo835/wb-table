from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "probe_ozon_catalog.py"
SPEC = importlib.util.spec_from_file_location("probe_ozon_catalog", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe_ozon_catalog = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe_ozon_catalog
SPEC.loader.exec_module(probe_ozon_catalog)


def test_classify_product_priority() -> None:
    assert probe_ozon_catalog.classify_product({"archived": True}) == "archived"
    assert probe_ozon_catalog.classify_product({"visibility": "HIDDEN"}) == "hidden"
    assert probe_ozon_catalog.classify_product({"visibility": "ACTIVE"}) == "active"
    assert probe_ozon_catalog.classify_product({"status": "inactive"}) == "inactive"


def test_flatten_for_csv_serializes_nested_fields() -> None:
    record = {
        "product_id": 123,
        "offer_id": "ABC-123",
        "details": {
            "brand": "TestBrand",
            "dimensions": {"width": 10, "height": 20},
        },
        "images": [{"url": "https://example.com/1.jpg"}],
    }

    flat = probe_ozon_catalog.flatten_mapping(record)

    assert flat["product_id"] == 123
    assert flat["offer_id"] == "ABC-123"
    assert flat["details__brand"] == "TestBrand"
    assert flat["details__dimensions__width"] == 10
    assert flat["details__dimensions__height"] == 20
    assert flat["images"] == '[{"url": "https://example.com/1.jpg"}]'


def test_count_helpers_detect_missing_and_present_values() -> None:
    stock_record = {"stocks": [{"present": 3, "warehouse_id": 999}, {"present": 4, "warehouse_id": 111}]}
    price_record = {"prices": {"current_price": 1990, "old_price": 2500}}

    assert probe_ozon_catalog.stock_total(stock_record) == 7.0
    assert probe_ozon_catalog.price_value(price_record) == 1990.0


def test_load_tracked_articles_with_headers(tmp_path, monkeypatch) -> None:
    csv_file = tmp_path / "tracked_articles.csv"
    csv_file.write_text("offer_id,name\nABC-123,Product 1\nDEF-456,Product 2\n", encoding="utf-8")

    from src.ozon import config
    monkeypatch.setattr(config, "TRACKED_ARTICLES_CSV", csv_file)

    articles = config.load_tracked_articles()
    assert articles == {"ABC-123", "DEF-456"}


def test_load_tracked_articles_without_headers(tmp_path, monkeypatch) -> None:
    csv_file = tmp_path / "tracked_articles.csv"
    csv_file.write_text("ABC-123\nDEF-456\n", encoding="utf-8")

    from src.ozon import config
    monkeypatch.setattr(config, "TRACKED_ARTICLES_CSV", csv_file)

    articles = config.load_tracked_articles()
    assert articles == {"ABC-123", "DEF-456"}


def test_load_tracked_articles_missing_file(monkeypatch) -> None:
    from src.ozon import config
    monkeypatch.setattr(config, "TRACKED_ARTICLES_CSV", Path("nonexistent_file_path.csv"))

    articles = config.load_tracked_articles()
    assert articles == set()


def test_load_tracked_articles_with_categories_headers(tmp_path, monkeypatch) -> None:
    csv_file = tmp_path / "tracked_articles.csv"
    csv_file.write_text("offer_id,category\nABC-123,женские трусы\nABC-123,детские трусы\nDEF-456,футболки\n", encoding="utf-8")

    from src.ozon import config
    monkeypatch.setattr(config, "TRACKED_ARTICLES_CSV", csv_file)

    rows = config.load_tracked_articles_with_categories()
    assert len(rows) == 3
    assert rows[0] == {"offer_id": "ABC-123", "category": "женские трусы"}
    assert rows[1] == {"offer_id": "ABC-123", "category": "детские трусы"}
    assert rows[2] == {"offer_id": "DEF-456", "category": "футболки"}

