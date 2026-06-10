from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic import command
from alembic.config import Config

from src.db.connection import ensure_safe_database_environment, get_database_url, mask_database_url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply Alembic migrations to the configured database.")
    parser.add_argument(
        "--revision",
        default="head",
        help="Alembic revision target, defaults to head.",
    )
    parser.add_argument(
        "--sql",
        action="store_true",
        help="Generate SQL without executing it.",
    )
    return parser.parse_args()


def build_alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    database_url = get_database_url(required=True)
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def main() -> int:
    args = parse_args()
    ensure_safe_database_environment()
    config = build_alembic_config()

    print(f"Applying Alembic revision: {args.revision}")
    print(f"Target DB: {mask_database_url(get_database_url(required=True))}")
    command.upgrade(config, args.revision, sql=args.sql)
    print("Alembic upgrade finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
