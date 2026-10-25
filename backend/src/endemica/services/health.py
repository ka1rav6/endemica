"""Health reporting.

Collects the status of each subsystem so ``GET /health`` can tell an operator
*what* is wrong, not merely that something is. Required components (the
database) degrade the overall status; optional ones (TinyFish) do not.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from endemica import __version__
from endemica.core.clock import utc_now
from endemica.core.config import Settings
from endemica.schemas.health import ComponentHealth, HealthResponse

logger = logging.getLogger(__name__)


def check_database(session: Session) -> ComponentHealth:
    """Verify the database answers a trivial query."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # The exception text can contain the connection URL, so log it at
        # debug level only and return a generic message to the caller.
        logger.warning("database health check failed", extra={"error": type(exc).__name__})
        logger.debug("database health check detail", exc_info=exc)
        return ComponentHealth(
            name="database",
            status="unavailable",
            detail="PostgreSQL did not answer; start it with `just db-up`.",
        )
    return ComponentHealth(name="database", status="ok", detail="PostgreSQL reachable")


def check_tinyfish(settings: Settings) -> ComponentHealth:
    """Report whether the optional TinyFish integration is configured.

    No network call is made: a health probe must not spend billable credits or
    depend on a third party's availability.
    """
    if settings.tinyfish_enabled:
        return ComponentHealth(
            name="tinyfish",
            status="ok",
            detail="API key configured; Agent extraction enabled",
        )
    return ComponentHealth(
        name="tinyfish",
        status="not_configured",
        detail=(
            "No TINYFISH_API_KEY set. Ingestion runs in direct_fetch mode: "
            "WHO pages are read over plain HTTPS and parsed deterministically."
        ),
    )


def build_health_response(session: Session, settings: Settings) -> HealthResponse:
    """Assemble the full health payload.

    Args:
        session: Database session used for the connectivity probe.
        settings: Application settings, used to report optional integrations.

    Returns:
        A :class:`HealthResponse` whose ``status`` is ``ok`` only when every
        required component is healthy.
    """
    components = [check_database(session), check_tinyfish(settings)]

    # Only required components can degrade the overall status. TinyFish being
    # absent is a supported configuration, not a fault.
    required_failing = [c for c in components if c.name == "database" and c.status != "ok"]
    status: str = "unavailable" if required_failing else "ok"
    if not required_failing and any(c.status == "degraded" for c in components):
        status = "degraded"

    return HealthResponse(
        status=status,  # type: ignore[arg-type]
        version=__version__,
        environment=settings.env,
        checked_at=utc_now(),
        components=components,
        data=[],
    )
