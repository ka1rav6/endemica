"""SQLAlchemy engine and session management.

Endemica uses synchronous SQLAlchemy with psycopg 3. FastAPI route handlers are
declared with ``def`` (not ``async def``) so Starlette runs them in a worker
thread: blocking database calls therefore never occupy the event loop, which is
what AGENTS.md section 7.2 warns against. See
docs/decisions/0002-synchronous-sqlalchemy.md for the trade-off.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from endemica.core.config import Settings, get_settings


@functools.lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide engine, created on first use.

    ``pool_pre_ping`` is enabled because the development database runs in a
    container that may be restarted while the application is running; without
    it the first query after a restart fails on a stale connection.
    """
    settings: Settings = get_settings()
    return create_engine(
        settings.sqlalchemy_url,
        echo=settings.database_echo,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        # Fail fast rather than hanging a request when the database is down.
        connect_args={"connect_timeout": 10},
    )


@functools.lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session for scripts and background work.

    Commits on success, rolls back on any exception, and always closes.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session.

    The session is *not* committed here: write endpoints commit explicitly, so
    a handler that raises after a partial write cannot accidentally persist it.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def reset_engine_cache() -> None:
    """Dispose the cached engine and factory.

    Used by tests that point the application at a different database after
    patching settings.
    """
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
