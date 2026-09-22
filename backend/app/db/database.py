"""
The one connection to Neon.

Three things here are Neon-specific and easy to get wrong:

1. `prepare_threshold=None`
   Neon's POOLED connection string goes through PgBouncer in transaction mode.
   psycopg3 normally starts using server-side prepared statements after a query
   runs 5 times; PgBouncer hands your next query to a different backend, which
   has never heard of that prepared statement, and you get a random
   "prepared statement does not exist" days later. Turning prepared statements
   off removes that whole class of bug.

2. A tiny pool (2 + 2).
   Render's free box has 0.1 CPU. Twenty idle connections would be twenty
   connections Neon bills compute hours for, doing nothing.

3. `pool_recycle=300`
   Neon's compute pauses after 5 idle minutes. A connection held across that
   pause is dead. We throw connections away before they can go stale, and
   `pool_pre_ping` catches any that slip through.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncGenerator, Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.logging import get_logger

log = get_logger("db")


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    """asyncio.run(), but with a scheduler psycopg can use. Scripts call this."""
    #   Q: Why not just asyncio.run(main())?
    #   A: On Windows, Python's default scheduler ("ProactorEventLoop") is one
    #      that psycopg's async mode refuses to work with. You get:
    #        InterfaceError: Psycopg cannot use the 'ProactorEventLoop'...
    #      SelectorEventLoop works. Linux (Render) already uses it, so this only
    #      changes anything on your laptop.
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coro)


def uses_windows_proactor() -> bool:
    """True if the running scheduler is the one psycopg can't use. main.py checks this."""
    return sys.platform == "win32" and isinstance(
        asyncio.get_running_loop(), asyncio.ProactorEventLoop
    )

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        if not settings.DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is empty. Copy backend/.env.example to backend/.env "
                "and paste your Neon pooled connection string."
            )
        _engine = create_async_engine(
            settings.sqlalchemy_url,
            echo=False,
            pool_size=2,
            max_overflow=2,
            pool_timeout=10,
            pool_recycle=300,
            pool_pre_ping=True,
            connect_args={
                "prepare_threshold": None,   # see note 1 above
                "connect_timeout": 10,
                "application_name": "praxon-chatbot",
            },
        )
        log.info("database engine created")
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: `session: AsyncSession = Depends(get_session)`."""
    async with get_sessionmaker()() as session:
        yield session


async def session_scope() -> AsyncSession:
    """
    For background tasks, which have no request to hang a dependency off.
    The caller is responsible for closing it — see leads/extractor.py.
    """
    return get_sessionmaker()()


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        log.info("database engine disposed")
    _engine = None
    _sessionmaker = None


async def ping() -> bool:
    """Wakes Neon and proves the connection works. Used by /api/warmup, never by /health."""
    from sqlalchemy import text

    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("database ping failed: %s", exc)
        return False
