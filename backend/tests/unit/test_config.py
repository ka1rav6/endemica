"""Settings behaviour: defaults, derived values and the production guard."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from epiroute.core.config import Settings


@pytest.fixture
def settings_from_env(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Return a builder that constructs Settings from environment variables.

    Settings are read from the environment rather than passed as keyword
    arguments, because the `EPIROUTE_` prefix only applies to environment
    lookups — this exercises the same path the application uses.
    """

    def _build(**env: str) -> Settings:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return Settings()

    return _build


def test_database_url_is_assembled_from_parts(settings_from_env: Callable[..., Settings]) -> None:
    s = settings_from_env(
        POSTGRES_USER="u",
        POSTGRES_PASSWORD="p",
        POSTGRES_DB="d",
        POSTGRES_HOST="h",
        POSTGRES_PORT="5555",
    )
    assert s.sqlalchemy_url == "postgresql+psycopg://u:p@h:5555/d"


def test_explicit_database_url_overrides_parts(settings_from_env: Callable[..., Settings]) -> None:
    s = settings_from_env(
        EPIROUTE_DATABASE_URL="postgresql+psycopg://a:b@c:1/e",
        POSTGRES_HOST="ignored",
    )
    assert s.sqlalchemy_url == "postgresql+psycopg://a:b@c:1/e"


def test_safe_database_url_redacts_the_password(settings_from_env: Callable[..., Settings]) -> None:
    s = settings_from_env(POSTGRES_PASSWORD="sup3rs3cret")
    assert "sup3rs3cret" not in s.safe_database_url
    assert ":***@" in s.safe_database_url


def test_tinyfish_is_disabled_without_a_key(settings_from_env: Callable[..., Settings]) -> None:
    assert settings_from_env().tinyfish_enabled is False


@pytest.mark.parametrize("key", ["", "   "])
def test_tinyfish_is_disabled_for_a_blank_key(
    key: str, settings_from_env: Callable[..., Settings]
) -> None:
    """A blank value in .env must not count as "configured"."""
    assert settings_from_env(TINYFISH_API_KEY=key).tinyfish_enabled is False


def test_tinyfish_is_enabled_with_a_key(settings_from_env: Callable[..., Settings]) -> None:
    assert settings_from_env(TINYFISH_API_KEY="tf-test-key").tinyfish_enabled is True


def test_secrets_are_not_in_the_repr(settings_from_env: Callable[..., Settings]) -> None:
    """A settings object may be logged by accident; it must not leak the key."""
    s = settings_from_env(TINYFISH_API_KEY="tf-test-key", POSTGRES_PASSWORD="pw")
    assert "tf-test-key" not in repr(s)
    assert "pw" not in repr(s)


def test_production_rejects_the_default_database_password(
    settings_from_env: Callable[..., Settings],
) -> None:
    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD"):
        settings_from_env(EPIROUTE_ENV="production", POSTGRES_PASSWORD="epiroute")


def test_production_accepts_a_changed_password(settings_from_env: Callable[..., Settings]) -> None:
    s = settings_from_env(EPIROUTE_ENV="production", POSTGRES_PASSWORD="changed")
    assert s.docs_enabled is False


def test_cors_origins_are_split_and_trimmed(settings_from_env: Callable[..., Settings]) -> None:
    s = settings_from_env(EPIROUTE_CORS_ORIGINS="http://a ,http://b,")
    assert s.cors_origin_list == ["http://a", "http://b"]


def test_relative_data_dir_resolves_against_the_repository_root(
    settings_from_env: Callable[..., Settings],
) -> None:
    s = settings_from_env(EPIROUTE_DATA_DIR="data")
    assert s.data_dir.is_absolute()
    assert s.raw_data_dir == s.data_dir / "raw"
    assert s.snapshot_data_dir == s.data_dir / "snapshot"
