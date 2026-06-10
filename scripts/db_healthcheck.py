from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.base import Base
from src.db import models as _models  # noqa: F401
from src.db.connection import (
    ensure_safe_database_environment,
    get_database_url,
    get_runtime_environment,
    mask_database_url,
    test_database_connection,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local DB layer health checks.")
    parser.add_argument(
        "--with-connection",
        action="store_true",
        help="Also try a live DB connection if DATABASE_URL is configured.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    environment = get_runtime_environment()
    database_url = get_database_url(required=False)

    print(f"ENV={environment}")
    print(f"DATABASE_URL configured: {'yes' if database_url else 'no'}")
    if database_url:
        print(f"Masked DB URL: {mask_database_url(database_url)}")

    ensure_safe_database_environment()

    table_names = sorted(Base.metadata.tables)
    print(f"Registered SQLAlchemy tables: {len(table_names)}")

    if not args.with_connection:
        print("Healthcheck passed without live DB connection.")
        return 0

    if not database_url:
        print("DATABASE_URL is not configured; cannot run live connectivity check.")
        return 1

    ok, message = test_database_connection()
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
