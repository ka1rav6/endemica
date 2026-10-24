"""Centralised application settings.

Every configurable value is declared here and read from the environment (or a
``.env`` file at the repository root). Modules import :func:`get_settings`
rather than reading ``os.environ`` directly, so configuration is discoverable
and testable.

Required settings are the PostgreSQL connection parts; everything else has a
development default. Optional integrations (TinyFish) are absent by default and
must never prevent startup — see AGENTS.md section 14.3.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The repository root is three levels above this file:
# backend/src/epiroute/core/config.py -> backend/src/epiroute -> backend/src
# -> backend -> <root>
REPO_ROOT = Path(__file__).resolve().parents[4]

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Runtime configuration, validated once at import time.

    Field names map to environment variables case-insensitively. Fields
    without an ``EPIROUTE_`` prefix (the ``POSTGRES_*`` group, the TinyFish
    group) are shared with ``docker-compose.yml`` and the documented TinyFish
    variable names, so they are declared with explicit aliases.
    """

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_prefix="EPIROUTE_",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -----------------------------------------------------
    env: Environment = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Database --------------------------------------------------------
    # A full URL wins when supplied; otherwise it is assembled from the parts.
    database_url: PostgresDsn | None = None
    postgres_user: str = Field(default="epiroute", alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(default=SecretStr("epiroute"), alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="epiroute", alias="POSTGRES_DB")
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=55433, alias="POSTGRES_PORT")

    # Echo SQL to the log. Useful when debugging a query, noisy otherwise.
    database_echo: bool = False

    # --- TinyFish (optional) ---------------------------------------------
    tinyfish_api_key: SecretStr | None = Field(default=None, alias="TINYFISH_API_KEY")
    tinyfish_fetch_url: str = Field(
        default="https://api.fetch.tinyfish.ai", alias="TINYFISH_FETCH_URL"
    )
    tinyfish_agent_url: str = Field(default="https://agent.tinyfish.ai", alias="TINYFISH_AGENT_URL")
    tinyfish_search_url: str = Field(
        default="https://api.search.tinyfish.ai", alias="TINYFISH_SEARCH_URL"
    )
    tinyfish_webhook_secret: SecretStr | None = Field(default=None, alias="TINYFISH_WEBHOOK_SECRET")
    # The Agent API is billed per step and limited to a small number of
    # concurrent runs, so extraction is capped per ingestion pass.
    tinyfish_agent_max_pages_per_run: int = 5
    tinyfish_agent_poll_timeout_seconds: float = 180.0
    tinyfish_agent_poll_interval_seconds: float = 3.0

    # --- Ingestion -------------------------------------------------------
    who_don_api_url: str = "https://www.who.int/api/news/diseaseoutbreaknews"
    who_don_item_url_template: str = (
        "https://www.who.int/emergencies/disease-outbreak-news/item/{url_name}"
    )
    ingest_max_records: int = 120
    http_timeout_seconds: float = 30.0
    http_max_retries: int = 3
    # Sent on every outbound request so operators of public APIs can identify
    # and contact us; anonymous scraping of public-health sites is impolite.
    http_user_agent: str = (
        "EpiRoute/0.1 (HackIIITD research prototype; +https://github.com/ka1rav6/endemica)"
    )

    # --- Data directories -------------------------------------------------
    data_dir: Path = Path("data")

    @field_validator("data_dir")
    @classmethod
    def _resolve_data_dir(cls, value: Path) -> Path:
        """Resolve a relative data directory against the repository root."""
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()

    @model_validator(mode="after")
    def _check_production_safety(self) -> Settings:
        """Refuse to run in production with the development database password.

        A default credential that works locally must not silently become a
        deployed credential.
        """
        if self.env == "production" and self.postgres_password.get_secret_value() == "epiroute":
            msg = (
                "POSTGRES_PASSWORD must be changed from its development "
                "default when EPIROUTE_ENV=production"
            )
            raise ValueError(msg)
        return self

    # --- Derived values ---------------------------------------------------

    @property
    def sqlalchemy_url(self) -> str:
        """The SQLAlchemy connection URL, assembled from parts if needed."""
        if self.database_url is not None:
            return str(self.database_url)
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def safe_database_url(self) -> str:
        """The connection URL with the password redacted, safe to log."""
        url = self.sqlalchemy_url
        password = self.postgres_password.get_secret_value()
        return url.replace(f":{password}@", ":***@") if password else url

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list, parsed from the comma-separated setting."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def tinyfish_enabled(self) -> bool:
        """Whether a TinyFish API key is configured.

        When false the ingestion pipeline uses its ``direct_fetch`` mode. This
        is a documented degraded mode, not an error.
        """
        key = self.tinyfish_api_key
        return key is not None and bool(key.get_secret_value().strip())

    @property
    def raw_data_dir(self) -> Path:
        """Directory holding untouched downloads."""
        return self.data_dir / "raw"

    @property
    def processed_data_dir(self) -> Path:
        """Directory holding normalised Parquet/JSON tables."""
        return self.data_dir / "processed"

    @property
    def cache_data_dir(self) -> Path:
        """Directory holding derived caches that can be rebuilt at any time."""
        return self.data_dir / "cache"

    @property
    def snapshot_data_dir(self) -> Path:
        """Directory holding the offline demonstration snapshot."""
        return self.data_dir / "snapshot"

    @property
    def docs_enabled(self) -> bool:
        """Whether to expose the interactive API documentation."""
        return self.env != "production"


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings, constructed on first use.

    Cached so the ``.env`` file is read once. Tests that need different values
    should call ``get_settings.cache_clear()`` after patching the environment.
    """
    return Settings()
