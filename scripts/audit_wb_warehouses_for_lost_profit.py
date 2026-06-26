from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
from decimal import Decimal

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select, func
from src.db.session import session_scope
from src.db.models import (
    FactStockWarehouseSnapshot,
    SettingsLostProfitWarehouseArea,
    SettingsLostProfitMarketArea,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit WB warehouses in stock snapshots compared to configurations.")
    parser.add_argument(
        "--output",
        type=str,
        help="Optional path to output the audit results as a CSV file.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass  # Python versions < 3.7 or sys.stdout doesn't support reconfigure

    with session_scope() as session:
        # 1. Fetch mapping settings
        mapping_stmt = select(
            SettingsLostProfitWarehouseArea.warehouse_name,
            SettingsLostProfitWarehouseArea.market_area_code,
            SettingsLostProfitMarketArea.population_share_pct,
        ).outerjoin(
            SettingsLostProfitMarketArea,
            SettingsLostProfitWarehouseArea.market_area_code == SettingsLostProfitMarketArea.market_area_code,
        )
        mappings = {
            row.warehouse_name: (row.market_area_code, row.population_share_pct)
            for row in session.execute(mapping_stmt).all()
        }

        # 2. Fetch warehouse statistics from snapshots
        stats_stmt = select(
            FactStockWarehouseSnapshot.warehouse_id,
            FactStockWarehouseSnapshot.warehouse_name,
            func.min(FactStockWarehouseSnapshot.snapshot_date).label("first_snapshot_date"),
            func.max(FactStockWarehouseSnapshot.snapshot_date).label("last_snapshot_date"),
            func.count().label("rows_count"),
            func.count(FactStockWarehouseSnapshot.nm_id.distinct()).label("distinct_nm_count"),
        ).group_by(
            FactStockWarehouseSnapshot.warehouse_id,
            FactStockWarehouseSnapshot.warehouse_name,
        ).order_by(
            func.count().desc()
        )
        warehouse_stats = session.execute(stats_stmt).all()

    audit_results = []
    total_warehouses = 0
    mapped_warehouses_count = 0
    unmapped_warehouses_count = 0
    unmapped_warehouses_list = []

    for row in warehouse_stats:
        wh_id = row.warehouse_id
        wh_name = row.warehouse_name or ""
        first_date = str(row.first_snapshot_date)
        last_date = str(row.last_snapshot_date)
        rows_count = row.rows_count
        distinct_nm = row.distinct_nm_count

        mapping = mappings.get(wh_name)
        if mapping:
            mapped_to_market_area = "yes"
            market_area_code = mapping[0]
            pop_share = mapping[1]
            mapped_warehouses_count += 1
        else:
            mapped_to_market_area = "no"
            market_area_code = None
            pop_share = None
            unmapped_warehouses_count += 1
            if wh_name:
                unmapped_warehouses_list.append(wh_name)

        total_warehouses += 1

        audit_results.append({
            "warehouse_id": wh_id,
            "warehouse_name": wh_name,
            "first_snapshot_date": first_date,
            "last_snapshot_date": last_date,
            "rows_count": rows_count,
            "distinct_nm_count": distinct_nm,
            "mapped_to_market_area": mapped_to_market_area,
            "market_area_code": market_area_code or "",
            "population_share_pct": float(pop_share) if pop_share is not None else "",
        })

    # Output detailed table to stdout
    print(f"{'warehouse_id':<12} | {'warehouse_name':<35} | {'first_date':<10} | {'last_date':<10} | {'rows':<8} | {'nm_count':<8} | {'mapped':<6} | {'market_area':<25} | {'pop_share':<10}")
    print("-" * 140)
    for res in audit_results:
        pop_str = f"{res['population_share_pct']:.3f}%" if res['population_share_pct'] != "" else ""
        print(
            f"{res['warehouse_id']:<12} | "
            f"{res['warehouse_name']:<35} | "
            f"{res['first_snapshot_date']:<10} | "
            f"{res['last_snapshot_date']:<10} | "
            f"{res['rows_count']:<8} | "
            f"{res['distinct_nm_count']:<8} | "
            f"{res['mapped_to_market_area']:<6} | "
            f"{res['market_area_code']:<25} | "
            f"{pop_str:<10}"
        )

    print("\n" + "=" * 60)
    print(f"total_warehouses: {total_warehouses}")
    print(f"mapped_warehouses_count: {mapped_warehouses_count}")
    print(f"unmapped_warehouses_count: {unmapped_warehouses_count}")
    print(f"unmapped_warehouses_list: {unmapped_warehouses_list}")
    print("=" * 60)

    # Optional CSV Export
    if args.output:
        output_path = Path(args.output)
        # Ensure parent directories exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, mode="w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "warehouse_id",
                    "warehouse_name",
                    "first_snapshot_date",
                    "last_snapshot_date",
                    "rows_count",
                    "distinct_nm_count",
                    "mapped_to_market_area",
                    "market_area_code",
                    "population_share_pct",
                ],
            )
            writer.writeheader()
            for res in audit_results:
                writer.writerow(res)
        print(f"\nAudit results successfully exported to CSV: {output_path.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
