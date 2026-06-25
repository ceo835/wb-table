from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any


QUERY_GROUP_VALUES = (
    "women_underwear",
    "men_underwear",
    "kids_underwear",
    "women_tshirts",
    "men_tshirts",
    "longsleeves",
    "gift_sets",
    "unknown",
)
QUERY_GROUP_UNKNOWN = "unknown"


def _norm(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip().lower()


def _contains_any(text: str, needles: Sequence[str]) -> bool:
    return any(needle in text for needle in needles)


def classify_product_query_group(product: Mapping[str, Any]) -> str:
    supplier_article = _norm(product.get("supplier_article"))
    title = _norm(product.get("title"))
    subject = _norm(product.get("subject"))
    brand = _norm(product.get("brand"))
    combined = " | ".join(value for value in (supplier_article, title, subject, brand) if value)

    if not combined:
        return QUERY_GROUP_UNKNOWN

    if _contains_any(combined, ("лонгслив", "longsleeve", "long sleeve")):
        return "longsleeves"

    if _contains_any(combined, ("подар", "gift set", "giftbox", "подарочный набор")):
        return "gift_sets"

    if "футбол" in combined or "t-shirt" in combined or "tshirt" in combined:
        if _contains_any(combined, ("муж", "men", "man", "мальчик")):
            return "men_tshirts"
        if _contains_any(combined, ("жен", "women", "wom", "girl", "девоч")):
            return "women_tshirts"
        return QUERY_GROUP_UNKNOWN

    underwear_markers = ("трус", "слип", "боксер", "боксер", "brief", "panties")
    if _contains_any(combined, underwear_markers):
        if _contains_any(combined, ("дет", "девоч", "мальч", "подрост", "kids", "kid", "junior")):
            return "kids_underwear"
        if _contains_any(combined, ("муж", "men", "man", "boxmen", "боксер", "боксеры", "семейн")):
            return "men_underwear"
        if _contains_any(combined, ("жен", "wom", "women", "слип", "стринг", "танга", "girl")):
            return "women_underwear"
        if "трусы" in subject and "women" not in subject and "men" not in subject:
            return QUERY_GROUP_UNKNOWN

    return QUERY_GROUP_UNKNOWN


def build_product_query_group_backfill_plan(
    products: Sequence[Mapping[str, Any]],
    *,
    force: bool = False,
) -> dict[str, Any]:
    update_rows: list[dict[str, Any]] = []
    breakdown: Counter[str] = Counter()
    examples_unknown: list[dict[str, Any]] = []
    skipped_existing_count = 0

    for product in products:
        nm_id = product.get("nm_id")
        predicted = classify_product_query_group(product)
        breakdown[predicted] += 1
        if predicted == QUERY_GROUP_UNKNOWN and len(examples_unknown) < 10:
            examples_unknown.append(
                {
                    "nm_id": int(nm_id),
                    "supplier_article": product.get("supplier_article"),
                    "title": product.get("title"),
                    "subject": product.get("subject"),
                    "brand": product.get("brand"),
                }
            )
        current = _norm(product.get("query_group"))
        normalized_current = current if current in QUERY_GROUP_VALUES else ""
        meaningful_existing = normalized_current not in ("", QUERY_GROUP_UNKNOWN)

        if meaningful_existing and not force:
            skipped_existing_count += 1
            continue

        if normalized_current == predicted and not force:
            continue

        update_rows.append(
            {
                "nm_id": int(nm_id),
                "query_group": predicted,
            }
        )

    return {
        "total_products_checked": len(products),
        "query_group_updated_count": len(update_rows),
        "skipped_existing_count": skipped_existing_count,
        "unknown_count": int(breakdown.get(QUERY_GROUP_UNKNOWN, 0)),
        "breakdown_by_query_group": dict(sorted(breakdown.items())),
        "examples_unknown": examples_unknown,
        "update_rows": update_rows,
    }
