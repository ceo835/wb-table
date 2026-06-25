from __future__ import annotations

from src.db.product_query_group_backfill import (
    QUERY_GROUP_UNKNOWN,
    build_product_query_group_backfill_plan,
    classify_product_query_group,
)


def test_classify_product_query_group_detects_women_underwear() -> None:
    result = classify_product_query_group(
        {
            "supplier_article": "BlackWOM5",
            "title": "Трусы комплект слипы набор 5 штук",
            "subject": "Трусы",
            "brand": "PALEY",
        }
    )

    assert result == "women_underwear"


def test_classify_product_query_group_detects_men_underwear() -> None:
    result = classify_product_query_group(
        {
            "supplier_article": "BOXMEN7",
            "title": "Трусы мужские боксеры набор",
            "subject": "Трусы",
            "brand": "PALEY",
        }
    )

    assert result == "men_underwear"


def test_classify_product_query_group_detects_unknown_for_unclear_product() -> None:
    result = classify_product_query_group(
        {
            "supplier_article": "MYSTERY1",
            "title": "Аксессуар универсальный",
            "subject": "Аксессуары",
            "brand": "PALEY",
        }
    )

    assert result == QUERY_GROUP_UNKNOWN


def test_build_product_query_group_backfill_plan_does_not_override_existing_without_force() -> None:
    summary = build_product_query_group_backfill_plan(
        [
            {
                "nm_id": 1,
                "supplier_article": "BOXMEN7",
                "title": "Трусы мужские боксеры набор",
                "subject": "Трусы",
                "brand": "PALEY",
                "query_group": "women_underwear",
            }
        ],
        force=False,
    )

    assert summary["query_group_updated_count"] == 0
    assert summary["skipped_existing_count"] == 1
    assert summary["update_rows"] == []


def test_build_product_query_group_backfill_plan_replaces_unknown_and_counts_unknown_examples() -> None:
    summary = build_product_query_group_backfill_plan(
        [
            {
                "nm_id": 1,
                "supplier_article": "MYSTERY1",
                "title": "Аксессуар универсальный",
                "subject": "Аксессуары",
                "brand": "PALEY",
                "query_group": None,
            },
            {
                "nm_id": 2,
                "supplier_article": "BlackWOM5",
                "title": "Трусы комплект слипы набор 5 штук",
                "subject": "Трусы",
                "brand": "PALEY",
                "query_group": "unknown",
            },
        ],
        force=False,
    )

    assert summary["query_group_updated_count"] == 2
    assert summary["unknown_count"] == 1
    assert summary["breakdown_by_query_group"]["unknown"] == 1
    assert summary["breakdown_by_query_group"]["women_underwear"] == 1
    assert summary["examples_unknown"][0]["nm_id"] == 1
    assert summary["update_rows"][1]["query_group"] == "women_underwear"
