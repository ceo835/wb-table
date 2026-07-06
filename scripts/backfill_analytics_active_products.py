from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sqlalchemy import select


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.models import SettingsProducts
from src.db.session import session_scope
from src.wb_site_price_monitor import load_price_monitor_targets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed settings_products.analytics_active from the current price-monitor target list."
    )
    parser.add_argument("--apply", action="store_true", help="Write analytics_active=true to DB.")
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run mode.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    apply = bool(args.apply and not args.dry_run)
    target_nm_ids = sorted({int(row["nm_id"]) for row in load_price_monitor_targets() if row.get("nm_id") is not None})

    with session_scope() as session:
        settings_rows = (
            session.execute(
                select(SettingsProducts)
                .where(SettingsProducts.nm_id.in_(target_nm_ids))
                .order_by(SettingsProducts.nm_id.asc())
            )
            .scalars()
            .all()
        )
        by_nm_id = {int(row.nm_id): row for row in settings_rows}
        matched_nm_ids = sorted(by_nm_id.keys())
        missing_in_settings = [nm_id for nm_id in target_nm_ids if nm_id not in by_nm_id]
        already_active = [nm_id for nm_id, row in by_nm_id.items() if bool(getattr(row, "analytics_active", False))]
        to_activate = [nm_id for nm_id in matched_nm_ids if nm_id not in already_active]

        updated_count = 0
        if apply:
            for nm_id in to_activate:
                by_nm_id[nm_id].analytics_active = True
                updated_count += 1

    print("backfill_analytics_active_products summary:")
    print(f"price_monitor_target_count: {len(target_nm_ids)}")
    print(f"matched_settings_products_count: {len(matched_nm_ids)}")
    print(f"missing_in_settings_count: {len(missing_in_settings)}")
    print(f"already_active_count: {len(already_active)}")
    print(f"to_activate_count: {len(to_activate)}")
    print(f"apply: {apply}")
    print(f"updated_count: {updated_count}")
    print(f"missing_in_settings_examples: {missing_in_settings[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
