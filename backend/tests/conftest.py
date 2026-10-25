"""Shared pytest fixtures.

The default test run must not need PostgreSQL, the network or any credential
(AGENTS.md section 8.2). Tests that do are marked `integration` or `network`
and are excluded from `just test`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def pytest_configure(config: pytest.Config) -> None:
    """Exclude externally-dependent tests unless explicitly selected."""
    expr = config.getoption("-m")
    if not expr:
        config.option.markexpr = "not integration and not network"


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test a predictable configuration.

    The repository `.env` is bypassed so a developer's local settings (and any
    real TinyFish key) cannot change test behaviour, and the settings cache is
    cleared around each test.
    """
    from endemica.core.config import Settings, get_settings

    for key in list(os.environ):
        if key.startswith(("ENDEMICA_", "POSTGRES_", "TINYFISH_")):
            monkeypatch.delenv(key, raising=False)

    # `model_config` is a plain dict; setitem (not setattr) is the way to
    # neutralise the .env file for the duration of the test.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("ENDEMICA_ENV", "test")
    monkeypatch.setenv("ENDEMICA_LOG_LEVEL", "WARNING")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fixture_path() -> Any:
    """Return a callable resolving a name inside tests/fixtures."""

    def _resolve(name: str) -> Path:
        path = FIXTURE_DIR / name
        if not path.exists():
            msg = f"fixture '{name}' does not exist at {path}"
            raise FileNotFoundError(msg)
        return path

    return _resolve


@pytest.fixture
def load_json_fixture(fixture_path: Any) -> Any:
    """Return a callable loading and parsing a JSON fixture."""

    def _load(name: str) -> Any:
        return json.loads(fixture_path(name).read_text(encoding="utf-8"))

    return _load
