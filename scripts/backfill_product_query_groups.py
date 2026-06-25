from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import select


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.models import FactStockWarehouseSnapshot, SettingsProducts
from src.db.product_query_group_backfill import build_product_query_group_backfill_plan
from src.db.session import session_scope
from src.tracked_products import load_tracked_products


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill settings_products.query_group for current working scope.")
    parser.add_argument("--apply", action="store_true", help="Write updates to DB. Without this flag the script is dry-run.")
    parser.add_argument("--force", action="store_true", help="Overwrite already filled query_group values.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run mode.")
    return parser.parse_args()


def load_scope_products() -> tuple[list[dict[str, Any]], list[int]]:
    tracked_df = load_tracked_products()
    tracked_nm_ids = set()
    if not tracked_df.empty and "nm_id" in tracked_df.columns:
        tracked_nm_ids = set(tracked_df["nm_id"].dropna().astype(int).tolist())

    with session_scope() as session:
        active_nm_ids = set(
            session.execute(select(SettingsProducts.nm_id).where(SettingsProducts.active.is_(True))).scalars().all()
        )
        stock_nm_ids = set(session.execute(select(FactStockWarehouseSnapshot.nm_id).distinct()).scalars().all())
        scope_nm_ids = sorted(tracked_nm_ids | active_nm_ids | stock_nm_ids)

        products = (
            [
                {
                    "nm_id": row.nm_id,
                    "supplier_article": row.supplier_article,
                    "title": row.title,
                    "subject": row.subject,
                    "brand": row.brand,
                    "query_group": row.query_group,
                    "active": row.active,
                }
                for row in session.execute(
                    select(SettingsProducts)
                    .where(SettingsProducts.nm_id.in_(scope_nm_ids))
                    .order_by(SettingsProducts.nm_id.asc())
                )
                .scalars()
                .all()
            ]
            if scope_nm_ids
            else []
        )

    missing_in_settings = [nm_id for nm_id in scope_nm_ids if nm_id not in {row["nm_id"] for row in products}]
    return products, missing_in_settings


def apply_query_group_updates(update_rows: list[dict[str, Any]]) -> int:
    updated = 0
    with session_scope() as session:
        settings_rows = (
            session.execute(
                select(SettingsProducts).where(
                    SettingsProducts.nm_id.in_([int(row["nm_id"]) for row in update_rows])
                )
            )
            .scalars()
            .all()
        )
        by_nm_id = {int(row.nm_id): row for row in settings_rows}
        for row in update_rows:
            model = by_nm_id.get(int(row["nm_id"]))
            if model is None:
                continue
            model.query_group = row["query_group"]
            updated += 1
    return updated


def main() -> int:
    args = parse_args()
    apply = bool(args.apply and not args.dry_run)
    products, missing_in_settings = load_scope_products()
    summary = build_product_query_group_backfill_plan(products, force=args.force)
    summary["scope_missing_in_settings_count"] = len(missing_in_settings)
    summary["scope_missing_in_settings_examples"] = missing_in_settings[:10]
    summary["force"] = bool(args.force)
    summary["apply"] = apply

    if apply:
        summary["query_group_updated_count"] = apply_query_group_updates(summary["update_rows"])

    print("backfill_product_query_groups summary:")
    for key in (
        "total_products_checked",
        "query_group_updated_count",
        "skipped_existing_count",
        "unknown_count",
        "scope_missing_in_settings_count",
        "force",
        "apply",
    ):
        print(f"{key}: {summary[key]}")
    print(f"breakdown_by_query_group: {summary['breakdown_by_query_group']}")
    print(f"examples_unknown: {summary['examples_unknown']}")
    print(f"scope_missing_in_settings_examples: {summary['scope_missing_in_settings_examples']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
