import asyncio
import logging
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


def _unique_statement_name() -> str:
    return f"__asyncpg_{uuid4()}__"


def build_engine_kwargs(settings: Settings) -> dict[str, Any]:
    """Engine options; the Supabase transaction pooler (6543) cannot reuse prepared statements."""
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if settings.uses_transaction_pooler:
        kwargs["poolclass"] = NullPool
        kwargs["connect_args"] = {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": _unique_statement_name,
        }
    return kwargs


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.DATABASE_URL, **build_engine_kwargs(settings))


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped AsyncSession."""
    async with get_sessionmaker()() as session:
        yield session


async def check_database() -> bool:
    """Run ``SELECT 1`` with a timeout; used by the readiness probe."""

    async def _ping() -> None:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_ping(), timeout=get_settings().DB_CHECK_TIMEOUT_SECONDS)
    except Exception as exc:  # readiness must report, not raise
        logger.warning("Database check failed: %s", exc)
        return False
    return True


async def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
