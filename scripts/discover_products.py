from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.product_discovery import discover_products, run_content_smoke


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover candidate products for settings_products.")
    parser.add_argument("--dry-run", action="store_true", help="Build report only, do not write settings_products.")
    parser.add_argument("--apply", action="store_true", help="Upsert discovered products into settings_products.")
    parser.add_argument("--content-smoke", action="store_true", help="Run read-only Content API smoke test.")
    parser.add_argument("--limit", type=int, default=10, help="Limit for smoke sample or page size preview.")
    args = parser.parse_args()

    if args.content_smoke:
        result = run_content_smoke(limit=max(1, args.limit))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    apply = bool(args.apply and not args.dry_run)
    result = discover_products(apply=apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
