from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.connection import get_database_url, mask_database_url, test_database_connection


def main() -> int:
    database_url = get_database_url(required=False)
    if not database_url:
        print("DATABASE_URL is not configured. Set it in .env before testing DB connectivity.")
        return 1

    ok, message = test_database_connection()
    print(f"Database URL: {mask_database_url(database_url)}")
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
