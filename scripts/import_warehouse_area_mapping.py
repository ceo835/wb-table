from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.session import session_scope
from src.db.lost_profit_settings import upsert_market_area_rows, upsert_warehouse_area_rows
from src.db.connection import ensure_safe_database_environment


def main() -> int:
    csv_path = PROJECT_ROOT / "warehouse_area_mapping.csv"
    if not csv_path.exists():
        sys.stderr.write(f"Error: File not found at {csv_path}\n")
        return 1

    # Ensure we are in a safe database environment before writing
    ensure_safe_database_environment()

    market_areas: dict[str, dict[str, object]] = {}
    warehouse_areas: list[dict[str, object]] = []

    print(f"Reading warehouse mappings from {csv_path}...")
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for idx, row in enumerate(reader):
            # Parse fields
            code = (row.get("market_area_code") or "").strip()
            name = (row.get("market_area_name") or "").strip()
            pop = (row.get("population") or "").strip()
            share = (row.get("population_share_pct") or "").strip()
            wh_name = (row.get("warehouse_name") or "").strip()
            comment = (row.get("comment") or "").strip()

            if not code or not wh_name:
                # Skip invalid rows
                continue

            # Accumulate unique market areas
            if code not in market_areas:
                market_areas[code] = {
                    "market_area_code": code,
                    "market_area_name": name or code,
                    "population_people": int(pop) if pop else 0,
                    "population_share_pct": Decimal(share) if share else Decimal("0.0"),
                    "source": "import_csv_v1",
                    "approval_status": "pending_ivan_review",
                    "comment": "Imported from warehouse_area_mapping.csv",
                }

            # Accumulate warehouse mappings
            warehouse_areas.append({
                "warehouse_name": wh_name,
                "market_area_code": code,
                "approval_status": "pending_ivan_review",
                "comment": comment or "Imported from CSV",
            })

            # Handle potential double-space variations in WB data (e.g. "Ташкент 1  WB" instead of "Ташкент 1 WB")
            if wh_name.endswith(" WB") and not wh_name.endswith("  WB"):
                normalized_wh = wh_name[:-3] + "  WB"
                warehouse_areas.append({
                    "warehouse_name": normalized_wh,
                    "market_area_code": code,
                    "approval_status": "pending_ivan_review",
                    "comment": f"{comment or 'Imported from CSV'} (auto-double-space)",
                })

    print(f"Parsed {len(market_areas)} unique market areas and {len(warehouse_areas)} warehouse mappings.")

    with session_scope() as session:
        print("Writing to database...")
        upserted_market = upsert_market_area_rows(session, list(market_areas.values()))
        upserted_warehouses = upsert_warehouse_area_rows(session, warehouse_areas)

    print("\nImport completed successfully:")
    print(f"  Market Areas upserted: {upserted_market}")
    print(f"  Warehouse Areas upserted: {upserted_warehouses}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
