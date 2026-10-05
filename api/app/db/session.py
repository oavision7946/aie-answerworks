"""Engine and session management. The engine is created lazily and can be swapped in tests."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import get_settings

CONNECT_TIMEOUT_SECONDS = 3


def create_db_engine(url: str) -> Engine:
    connect_args = (
        {"connect_timeout": CONNECT_TIMEOUT_SECONDS} if url.startswith("postgresql") else {}
    )
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


@lru_cache
def get_engine() -> Engine:
    return create_db_engine(get_settings().env.database_url)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    with sessionmaker(bind=get_engine(), expire_on_commit=False)() as session:
        yield session


def check_database(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
