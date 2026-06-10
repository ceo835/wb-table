from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.config.settings import settings


SAFE_ENVIRONMENTS = {"dev", "test", "local"}


def get_runtime_environment(explicit_env: str | None = None) -> str:
    return (explicit_env or settings.env or "dev").strip().lower()


def is_production_environment(explicit_env: str | None = None) -> bool:
    return get_runtime_environment(explicit_env) == "prod"


def mask_database_url(database_url: str) -> str:
    if not database_url:
        return ""

    parsed = urlsplit(database_url)
    if "@" not in parsed.netloc:
        return database_url

    credentials, host = parsed.netloc.rsplit("@", 1)
    if ":" in credentials:
        username, _password = credentials.split(":", 1)
        safe_netloc = f"{username}:***@{host}"
    else:
        safe_netloc = f"***@{host}"
    return urlunsplit((parsed.scheme, safe_netloc, parsed.path, parsed.query, parsed.fragment))


def normalize_database_url(database_url: str | None) -> str | None:
    if not database_url:
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def get_database_url(database_url: str | None = None, required: bool = False) -> str | None:
    resolved = normalize_database_url(database_url or settings.database_url)
    if required and not resolved:
        raise RuntimeError("DATABASE_URL не задан. Добавьте его в .env или передайте явно.")
    return resolved


def ensure_safe_database_environment(
    explicit_env: str | None = None,
    allow_prod_db: bool | None = None,
) -> None:
    allow_prod = settings.allow_prod_db if allow_prod_db is None else allow_prod_db
    if is_production_environment(explicit_env) and not allow_prod:
        raise RuntimeError(
            "Подключение к prod-базе запрещено по умолчанию. "
            "Установите ALLOW_PROD_DB=true только при осознанном запуске."
        )


def create_db_engine(
    database_url: str | None = None,
    *,
    explicit_env: str | None = None,
    allow_prod_db: bool | None = None,
    echo: bool = False,
    **kwargs: Any,
) -> Engine:
    ensure_safe_database_environment(explicit_env=explicit_env, allow_prod_db=allow_prod_db)
    resolved_url = get_database_url(database_url=database_url, required=True)
    return create_engine(
        resolved_url,
        future=True,
        pool_pre_ping=True,
        echo=echo,
        **kwargs,
    )


def test_database_connection(
    database_url: str | None = None,
    *,
    explicit_env: str | None = None,
    allow_prod_db: bool | None = None,
) -> tuple[bool, str]:
    try:
        engine = create_db_engine(
            database_url=database_url,
            explicit_env=explicit_env,
            allow_prod_db=allow_prod_db,
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, "DB connection OK"
    except Exception as exc:
        return False, str(exc)
