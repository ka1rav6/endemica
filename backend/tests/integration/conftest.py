"""Fixtures for tests that need a real PostgreSQL database.

These tests run against the development container (`just db-up`) inside a
transaction that is rolled back afterwards, so they never leave rows behind.
They are marked `integration` and excluded from the default `just test` run.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

# Captured at import time: the autouse `_isolated_settings` fixture strips
# POSTGRES_* from the environment before each test, so reading them later would
# always yield the defaults.
_PG_ENV = {
    key: os.environ.get(key)
    for key in (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
    )
}


def _database_url() -> str:
    """Build the test database URL from the same variables docker-compose uses."""
    user = _PG_ENV["POSTGRES_USER"] or "epiroute"
    password = _PG_ENV["POSTGRES_PASSWORD"] or "epiroute"
    db = _PG_ENV["POSTGRES_DB"] or "epiroute"
    host = _PG_ENV["POSTGRES_HOST"] or "localhost"
    port = _PG_ENV["POSTGRES_PORT"] or "55433"
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """A session-scoped engine, skipping the suite when PostgreSQL is absent."""
    # The autouse settings fixture strips POSTGRES_* from the environment, so
    # read the real values before it runs by using the original process env.
    url = _database_url()
    eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip(
            "PostgreSQL is not reachable; start it with `just db-up` and apply "
            "migrations with `just db-migrate`."
        )
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session wrapped in a transaction that is always rolled back.

    Nested `session.commit()` calls inside the code under test are confined to
    a SAVEPOINT, so application code can commit normally while the test still
    leaves the database untouched.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
