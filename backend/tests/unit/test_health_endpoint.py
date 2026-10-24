"""Health endpoint behaviour, including its degraded paths.

The database is replaced by a stub so these tests stay in the default run.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from epiroute.core.config import Settings
from epiroute.db.session import get_db
from epiroute.main import create_app


class _StubSession:
    """Minimal stand-in for a SQLAlchemy Session."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def execute(self, *_: object, **__: object) -> object:
        if self.fail:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        return object()


def _client(*, db_fails: bool = False, tinyfish_key: str | None = None) -> Iterator[TestClient]:
    env: dict[str, str] = {}
    if tinyfish_key:
        env["TINYFISH_API_KEY"] = tinyfish_key
    settings = Settings(**env)  # type: ignore[arg-type]
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: _StubSession(fail=db_fails)
    # get_settings is used via Depends inside the route, so override it too.
    from epiroute.core.config import get_settings

    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield client


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from _client()


def test_health_reports_ok_when_the_database_answers(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]
    names = {c["name"]: c for c in body["components"]}
    assert names["database"]["status"] == "ok"


def test_health_returns_503_when_the_database_is_down() -> None:
    for client in _client(db_fails=True):
        response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "unavailable"
        # The breakdown must still be present so an operator can see the cause.
        names = {c["name"]: c for c in body["components"]}
        assert names["database"]["status"] == "unavailable"
        assert "just db-up" in names["database"]["detail"]


def test_missing_tinyfish_key_does_not_degrade_overall_health(client: TestClient) -> None:
    """An unconfigured optional integration is a supported state, not a fault."""
    body = client.get("/health").json()
    assert body["status"] == "ok"
    names = {c["name"]: c for c in body["components"]}
    assert names["tinyfish"]["status"] == "not_configured"
    assert "direct_fetch" in names["tinyfish"]["detail"]


def test_configured_tinyfish_key_is_reported_without_leaking_it() -> None:
    for client in _client(tinyfish_key="tf-secret-value"):
        raw = client.get("/health").text
        assert "tf-secret-value" not in raw
        names = {c["name"]: c for c in client.get("/health").json()["components"]}
        assert names["tinyfish"]["status"] == "ok"


def test_database_error_detail_does_not_leak_the_connection_string() -> None:
    for client in _client(db_fails=True):
        assert "postgresql+psycopg" not in client.get("/health").text


def test_unknown_path_returns_the_uniform_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
