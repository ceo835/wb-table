from __future__ import annotations

import argparse
import json
from typing import Sequence

from src.db.product_size_loader import refresh_dim_product_size
from src.tracked_products import get_tracked_nm_ids


def _resolve_nm_ids(args: argparse.Namespace) -> Sequence[int] | None:
    if args.nm_id:
        return [int(value) for value in args.nm_id]
    if args.tracked_products or not args.nm_id:
        return get_tracked_nm_ids()
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load dim_product_size crosswalk from WB Content API.")
    parser.add_argument("--nm-id", dest="nm_id", action="append", type=int, help="Specific nm_id to refresh. Repeatable.")
    parser.add_argument("--tracked-products", action="store_true", help="Refresh tracked products from data/config/tracked_products.csv.")
    parser.add_argument("--apply", action="store_true", help="Write rows to DB.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    nm_ids = _resolve_nm_ids(args)
    summary = refresh_dim_product_size(
        nm_ids=nm_ids,
        write_db=args.apply,
    )
    summary["mode"] = "apply" if args.apply else "dry-run"
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
