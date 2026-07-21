from __future__ import annotations

from typing import Any

CATEGORIES_CONFIG: list[dict[str, Any]] = [
    {
        "category_code": "womens_tshirts",
        "category_title": "Женские футболки",
        "search_queries": ["женские футболки"],
        "related_subjects": ["Футболки", "Футболка"],
        "region": None,
        "is_active": True,
    },
    {
        "category_code": "childrens_tshirts",
        "category_title": "Детские футболки",
        "search_queries": ["детские футболки"],
        "related_subjects": ["Футболки детские"],
        "region": None,
        "is_active": True,
    },
    {
        "category_code": "womens_underwear",
        "category_title": "Женское белье",
        "search_queries": ["женские трусы"],
        "related_subjects": ["Трусы"],
        "region": None,
        "is_active": True,
    },
    {
        "category_code": "childrens_underwear",
        "category_title": "Детское белье",
        "search_queries": ["детские трусы"],
        "related_subjects": ["Трусы детские", "Колготки детские"],
        "region": None,
        "is_active": True,
    },
]


def get_queries_for_category(category_code: str) -> list[str]:
    for cat in CATEGORIES_CONFIG:
        if cat["category_code"] == category_code and cat["is_active"]:
            return cat["search_queries"]
    return []


def get_active_categories() -> list[dict[str, Any]]:
    return [cat for cat in CATEGORIES_CONFIG if cat["is_active"]]
