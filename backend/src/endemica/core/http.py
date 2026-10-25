"""Outbound HTTP with explicit timeouts and bounded retries.

All outbound traffic goes through :func:`build_client` so that timeouts,
retry policy, redirect handling and the User-Agent are set in exactly one
place. AGENTS.md section 7.2 requires explicit timeouts; section 13 requires
bounded retries rather than uncontrolled polling.

Retries cover only transport errors and the status codes that indicate a
transient condition (429, 502, 503, 504). A 4xx other than 429 is a permanent
answer and is returned to the caller rather than retried.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

import httpx

from endemica.core.config import Settings, get_settings
from endemica.core.errors import ExternalServiceError

logger = logging.getLogger(__name__)

# Status codes worth retrying. 429 is included because a rate limit clears;
# every other 4xx is a permanent answer about the request itself.
RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# Base for exponential backoff, in seconds.
_BACKOFF_BASE = 1.5


@contextmanager
def build_client(
    settings: Settings | None = None,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
) -> Iterator[httpx.Client]:
    """Yield a configured :class:`httpx.Client`.

    Args:
        settings: Settings to read the timeout and User-Agent from. Defaults to
            the process-wide settings.
        headers: Extra headers, merged over the defaults. Pass credentials
            here; they are never logged.
        timeout_seconds: Override the configured timeout. TinyFish Fetch
            documents a client timeout of at least 150 s, which is far longer
            than the default.

    Yields:
        A client that is closed when the context exits.
    """
    settings = settings or get_settings()
    merged = {"User-Agent": settings.http_user_agent, "Accept-Encoding": "gzip, deflate"}
    if headers:
        merged.update(headers)
    timeout = httpx.Timeout(timeout_seconds or settings.http_timeout_seconds)
    with httpx.Client(
        timeout=timeout,
        headers=merged,
        follow_redirects=True,
        # A low connection limit is plenty for our request volume and keeps us
        # from hammering a public-health API.
        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
    ) as client:
        yield client


def _sleep_for_retry(attempt: int, response: httpx.Response | None) -> float:
    """Return the delay before the next attempt, honouring ``Retry-After``.

    Jitter is added so that several concurrent callers do not retry in lockstep.
    """
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                # Retry-After may be an HTTP date; fall through to backoff
                # rather than failing on an unparseable header.
                logger.debug("unparseable Retry-After header", extra={"value": retry_after})
    return _BACKOFF_BASE**attempt + random.uniform(0.0, 0.5)


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    service: str,
    max_retries: int | None = None,
    **kwargs: object,
) -> httpx.Response:
    """Perform a request, retrying transient failures with backoff.

    Args:
        client: Client from :func:`build_client`.
        method: HTTP method.
        url: Absolute URL.
        service: Short service name used in errors and logs.
        max_retries: Total attempts beyond the first. Defaults to the
            configured value.
        **kwargs: Passed through to ``client.request``.

    Returns:
        The response. A non-retryable error status is returned as-is, so the
        caller can distinguish, say, a TinyFish 402 from a 500.

    Raises:
        ExternalServiceError: When every attempt failed at the transport level,
            or when a retryable status persisted through all attempts.
    """
    attempts = (max_retries if max_retries is not None else get_settings().http_max_retries) + 1
    last_response: httpx.Response | None = None
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            response = client.request(method, url, **kwargs)  # type: ignore[arg-type]
        except httpx.HTTPError as exc:
            last_error = exc
            logger.warning(
                "request failed at transport level",
                extra={
                    "service": service,
                    "url": url,
                    "attempt": attempt + 1,
                    "error": type(exc).__name__,
                },
            )
        else:
            if response.status_code not in RETRYABLE_STATUS:
                return response
            last_response = response
            logger.warning(
                "retryable status from upstream",
                extra={
                    "service": service,
                    "url": url,
                    "status": response.status_code,
                    "attempt": attempt + 1,
                },
            )

        if attempt < attempts - 1:
            time.sleep(_sleep_for_retry(attempt, last_response))

    if last_response is not None:
        raise ExternalServiceError(
            service,
            f"returned {last_response.status_code} on all {attempts} attempts",
            status_code=last_response.status_code,
            retryable=True,
        )
    raise ExternalServiceError(
        service,
        f"unreachable after {attempts} attempts ({type(last_error).__name__})",
        retryable=True,
    )
