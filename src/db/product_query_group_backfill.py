from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any


QUERY_GROUP_UNKNOWN = "unknown"
QUERY_GROUP_VALUES = (
    "трусы женские",
    "трусы мужские",
    "трусы детские",
    "женская футболка",
    "мужская футболка",
    "лонгслив",
    "подарочный набор",
    "топ детский",
    "детская футболка",
    QUERY_GROUP_UNKNOWN,
)
QUERY_GROUP_ALIASES = {
    "women_underwear": "трусы женские",
    "men_underwear": "трусы мужские",
    "kids_underwear": "трусы детские",
    "women_tshirts": "женская футболка",
    "men_tshirts": "мужская футболка",
    "longsleeves": "лонгслив",
    "gift_sets": "подарочный набор",
    "футболка женская": "женская футболка",
    "футболка мужская": "мужская футболка",
    "лонгсливы": "лонгслив",
    "подарочные наборы": "подарочный набор",
    QUERY_GROUP_UNKNOWN: QUERY_GROUP_UNKNOWN,
}
MANUAL_QUERY_GROUP_OVERRIDES = {
    219107635: "трусы женские",
    593190228: "мужская футболка",
    300841607: "мужская футболка",
    26033523: "топ детский",
    291370302: "детская футболка",
    286727698: "детская футболка",
    286732546: "детская футболка",
    895684197: "детская футболка",
    895655750: "детская футболка",
    895669045: "детская футболка",
    895697737: "детская футболка",
    279857790: "детская футболка",
    895729315: "детская футболка",
    895521471: "детская футболка",
    233922260: "детская футболка",
    286219338: "детская футболка",
}


def _norm(value: Any) -> str:
    if value is None:
        return ""
    try:
        if value == "":
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip().lower()
    if text in {"", "<na>", "nan", "none"}:
        return ""
    return text


def _contains_any(text: str, needles: Sequence[str]) -> bool:
    return any(needle in text for needle in needles)


def normalize_query_group_value(value: Any) -> str | None:
    normalized = _norm(value)
    if not normalized:
        return None
    if normalized in QUERY_GROUP_VALUES:
        return normalized
    return QUERY_GROUP_ALIASES.get(normalized)


def format_query_group_label(value: Any, *, undefined_label: str = "Не определена") -> str:
    normalized = normalize_query_group_value(value)
    if normalized in (None, QUERY_GROUP_UNKNOWN):
        return undefined_label
    return normalized


def _manual_override(product: Mapping[str, Any]) -> str | None:
    nm_id = product.get("nm_id")
    if nm_id in (None, ""):
        return None
    try:
        resolved_nm_id = int(nm_id)
    except (TypeError, ValueError):
        return None
    return MANUAL_QUERY_GROUP_OVERRIDES.get(resolved_nm_id)


def classify_product_query_group(product: Mapping[str, Any]) -> str:
    manual_override = _manual_override(product)
    if manual_override is not None:
        return manual_override

    supplier_article = _norm(product.get("supplier_article"))
    title = _norm(product.get("title"))
    subject = _norm(product.get("subject"))
    brand = _norm(product.get("brand"))
    combined = " | ".join(value for value in (supplier_article, title, subject, brand) if value)

    if not combined:
        return QUERY_GROUP_UNKNOWN

    kids_markers = ("дет", "девоч", "мальч", "подрост", "kids", "kid", "junior")
    women_markers = ("жен", "women", "wom", "girl")
    men_markers = ("муж", "men", "man", "boxmen", "семейн")

    if _contains_any(combined, ("лонгслив", "longsleeve", "long sleeve")):
        return "лонгслив"

    if _contains_any(combined, ("подар", "gift set", "giftbox", "подарочный набор")):
        return "подарочный набор"

    if _contains_any(combined, ("топ", "top")) and _contains_any(combined, kids_markers):
        return "топ детский"

    if "футбол" in combined or "t-shirt" in combined or "tshirt" in combined:
        if _contains_any(combined, kids_markers):
            return "детская футболка"
        if _contains_any(combined, men_markers):
            return "мужская футболка"
        if _contains_any(combined, women_markers):
            return "женская футболка"
        return QUERY_GROUP_UNKNOWN

    underwear_markers = ("трус", "слип", "боксер", "brief", "panties")
    if _contains_any(combined, underwear_markers):
        if _contains_any(combined, kids_markers):
            return "трусы детские"
        if _contains_any(combined, men_markers):
            return "трусы мужские"
        if _contains_any(combined, women_markers + ("стринг", "танга")):
            return "трусы женские"
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
        normalized_current = normalize_query_group_value(product.get("query_group")) or ""
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
