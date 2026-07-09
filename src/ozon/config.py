from __future__ import annotations

import csv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRACKED_ARTICLES_CSV = PROJECT_ROOT / "data" / "config" / "ozon_tracked_articles.csv"


def load_tracked_articles() -> set[str]:
    """Loads tracked Ozon articles (offer_id values) from the CSV configuration file.

    Handles UTF-8-sig (with BOM) and attempts to find a column named
    'offer_id', 'offerid', 'article', 'артикул', or 'id'.
    If no matching column header is found, uses the first column.
    """
    if not TRACKED_ARTICLES_CSV.exists():
        return set()

    articles: set[str] = set()
    try:
        # Open with utf-8-sig to automatically handle BOM if present
        with TRACKED_ARTICLES_CSV.open("r", encoding="utf-8-sig") as f:
            content = f.read()
            if not content.strip():
                return set()

            # Reset file pointer
            f.seek(0)
            
            # Simple check for header presence
            # We will read the first row to check for known headers
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return set()

            target_idx = 0
            has_header = False
            header_lower = [h.strip().lower() for h in header]
            for col_name in ["offer_id", "offerid", "article", "артикул", "id"]:
                if col_name in header_lower:
                    target_idx = header_lower.index(col_name)
                    has_header = True
                    break

            if not has_header:
                # If there's no recognizable header, treat the first row's value as data
                val = header[0].strip()
                if val:
                    articles.add(val)

            # Read remaining rows
            for row in reader:
                if len(row) > target_idx:
                    val = row[target_idx].strip()
                    if val:
                        articles.add(val)
    except Exception as exc:
        print(f"[WARN] Failed to load tracked articles from {TRACKED_ARTICLES_CSV}: {exc}")

    return articles


def load_tracked_articles_with_categories() -> list[dict[str, str]]:
    """Loads tracked Ozon articles as a list of dicts with 'offer_id' and 'category'.

    Preserves duplicates and ordering from the CSV configuration file.
    """
    if not TRACKED_ARTICLES_CSV.exists():
        return []

    rows: list[dict[str, str]] = []
    try:
        with TRACKED_ARTICLES_CSV.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            # Find matching column for offer_id
            offer_col = None
            if reader.fieldnames:
                for col_name in ["offer_id", "offerid", "article", "артикул", "id"]:
                    for fn in reader.fieldnames:
                        if fn.strip().lower() == col_name:
                            offer_col = fn
                            break
                    if offer_col:
                        break

            # Find matching column for category
            category_col = None
            if reader.fieldnames:
                for col_name in ["category", "категория"]:
                    for fn in reader.fieldnames:
                        if fn.strip().lower() == col_name:
                            category_col = fn
                            break
                    if category_col:
                        break

            for r in reader:
                oid = r.get(offer_col or "") if offer_col else next(iter(r.values()), None)
                if oid:
                    oid = oid.strip()
                cat = r.get(category_col or "") if category_col else ""
                if cat:
                    cat = cat.strip()
                if oid:
                    rows.append({"offer_id": oid, "category": cat or "без категории"})
    except Exception as exc:
        print(f"[WARN] Failed to load tracked articles with categories from {TRACKED_ARTICLES_CSV}: {exc}")

    return rows
