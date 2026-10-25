"""Time source.

Timestamps are produced through :func:`utc_now` rather than
``datetime.now()`` so that provenance times are always timezone-aware UTC and
so tests can freeze time without patching the standard library globally.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Return ``value`` as timezone-aware UTC.

    A naive datetime is interpreted as UTC. External sources (the WHO API, for
    instance) sometimes omit the offset while documenting the value as UTC, so
    assuming UTC is the correct reading rather than a guess at local time.
    """
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
