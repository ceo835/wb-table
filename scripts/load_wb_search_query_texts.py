#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.wb_search_query_text_loader import (
    DEFAULT_SEARCH_TEXT_LIMIT,
    load_search_scope_products,
    load_search_text_rows,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load WB search query texts into fact_wb_search_query_text_day.")
    parser.add_argument("--date", required=True, help="Target date in YYYY-MM-DD.")
    parser.add_argument("--nm-id", dest="nm_ids", action="append", type=int, help="Restrict scope to nm_id. Repeatable.")
    parser.add_argument("--tracked-products", action="store_true", help="Use tracked_products.csv scope.")
    parser.add_argument("--problem-products", action="store_true", help="Use problem-products scope from latest warehouse snapshot.")
    parser.add_argument("--known-query-group-only", action="store_true", help="Exclude null/unknown query_group.")
    parser.add_argument("--limit", type=int, default=DEFAULT_SEARCH_TEXT_LIMIT, help="WB API limit. Default: 100.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run mode.")
    parser.add_argument("--apply", action="store_true", help="Write rows to PostgreSQL.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    apply = bool(args.apply and not args.dry_run)
    tracked_scope = bool(args.tracked_products or (not args.nm_ids and not args.problem_products))

    products: list[dict[str, object]] = []
    if args.nm_ids:
        for nm_id in args.nm_ids:
            products.extend(
                load_search_scope_products(
                    nm_id=nm_id,
                    known_query_group_only=bool(args.known_query_group_only),
                )
            )
    else:
        products = load_search_scope_products(
            tracked_products=tracked_scope,
            problem_products=bool(args.problem_products),
            known_query_group_only=bool(args.known_query_group_only),
        )

    deduped_products = list({int(product["nm_id"]): product for product in products if product.get("nm_id") is not None}.values())
    summary = load_search_text_rows(
        target_day=date.fromisoformat(args.date),
        products=deduped_products,
        apply=apply,
        limit=int(args.limit),
    )
    summary["scope_mode"] = (
        "nm_id"
        if args.nm_ids
        else "problem_products"
        if args.problem_products
        else "tracked_products"
        if tracked_scope
        else "settings_products_active"
    )
    summary["known_query_group_only"] = bool(args.known_query_group_only)
    summary["apply"] = apply
    summary["dry_run"] = not apply
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if summary.get("api_status") in {"200", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
