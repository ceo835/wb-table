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
