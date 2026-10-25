from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from endemica.core.config import Settings, get_settings
from endemica.core.errors import ConfigurationError, ExternalServiceError
from endemica.core.http import build_client, request_with_retry
from endemica.tinyfish.schemas import (
    AgentRunStarted,
    AgentRunStatus,
    FetchResponse,
    SearchResponse,
)

logger = logging.getLogger(__name__)

SERVICE = "TinyFish"
MAX_FETCH_URLS = 10
FETCH_TIMEOUT_SECONDS = 180.0

STATUS_UNAUTHORISED = 401
STATUS_INSUFFICIENT_CREDITS = 402
STATUS_RATE_LIMITED = 429


class TinyFishNotConfiguredError(ConfigurationError):
    pass


class TinyFishCreditsExhaustedError(ExternalServiceError):
    def __init__(self) -> None:
        super().__init__(
            SERVICE,
            "wallet has insufficient credits; falling back to Fetch-only extraction",
            status_code=STATUS_INSUFFICIENT_CREDITS,
            retryable=False,
        )


class TinyFishAuthError(ExternalServiceError):
    def __init__(self) -> None:
        super().__init__(
            SERVICE, "API key rejected", status_code=STATUS_UNAUTHORISED, retryable=False
        )


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    run_id: str | None
    status: str
    result: dict[str, Any] | None
    steps: int | None
    error: str | None

    @property
    def succeeded(self) -> bool:
        return self.status.upper() == "COMPLETED" and self.result is not None


class TinyFishClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        if not self._settings.tinyfish_enabled:
            msg = "TINYFISH_API_KEY is not set"
            raise TinyFishNotConfiguredError(msg)
        key = self._settings.tinyfish_api_key
        assert key is not None
        self._headers = {"X-API-Key": key.get_secret_value(), "Content-Type": "application/json"}

    def _raise_for_known_status(self, response: httpx.Response) -> None:
        if response.status_code == STATUS_UNAUTHORISED:
            raise TinyFishAuthError
        if response.status_code == STATUS_INSUFFICIENT_CREDITS:
            raise TinyFishCreditsExhaustedError

    def fetch(self, urls: list[str], *, output_format: str = "markdown") -> FetchResponse:
        if not urls:
            return FetchResponse()
        if len(urls) > MAX_FETCH_URLS:
            msg = f"TinyFish Fetch accepts at most {MAX_FETCH_URLS} URLs per call"
            raise ValueError(msg)

        with build_client(
            self._settings, headers=self._headers, timeout_seconds=FETCH_TIMEOUT_SECONDS
        ) as client:
            response = request_with_retry(
                client,
                "POST",
                self._settings.tinyfish_fetch_url,
                service=SERVICE,
                max_retries=self._settings.http_max_retries,
                json={"urls": urls, "format": output_format},
            )
        self._raise_for_known_status(response)
        if response.status_code != 200:
            msg = f"Fetch returned HTTP {response.status_code}"
            raise ExternalServiceError(SERVICE, msg, status_code=response.status_code)
        return FetchResponse.model_validate(response.json())

    def search(
        self,
        query: str,
        *,
        include_domains: list[str] | None = None,
        recency_minutes: int | None = None,
    ) -> SearchResponse:
        params: dict[str, str] = {"query": query}
        if include_domains:
            params["include_domains"] = ",".join(include_domains)
        if recency_minutes is not None:
            params["recency_minutes"] = str(recency_minutes)

        with build_client(self._settings, headers=self._headers) as client:
            response = request_with_retry(
                client,
                "GET",
                self._settings.tinyfish_search_url,
                service=SERVICE,
                max_retries=self._settings.http_max_retries,
                params=params,
            )
        self._raise_for_known_status(response)
        if response.status_code != 200:
            msg = f"Search returned HTTP {response.status_code}"
            raise ExternalServiceError(SERVICE, msg, status_code=response.status_code)
        return SearchResponse.model_validate(response.json())

    def start_agent_run(self, url: str, goal: str, output_schema: dict[str, Any]) -> str:
        with build_client(self._settings, headers=self._headers) as client:
            response = request_with_retry(
                client,
                "POST",
                f"{self._settings.tinyfish_agent_url}/v1/automation/run-async",
                service=SERVICE,
                max_retries=self._settings.http_max_retries,
                json={"url": url, "goal": goal, "output_schema": output_schema},
            )
        self._raise_for_known_status(response)
        if response.status_code != 200:
            msg = f"Agent start returned HTTP {response.status_code}"
            raise ExternalServiceError(SERVICE, msg, status_code=response.status_code)
        started = AgentRunStarted.model_validate(response.json())
        if started.error or not started.run_id:
            msg = started.error or "Agent start returned no run id"
            raise ExternalServiceError(SERVICE, msg)
        return started.run_id

    def get_agent_run(self, run_id: str) -> AgentRunStatus:
        with build_client(self._settings, headers=self._headers) as client:
            response = request_with_retry(
                client,
                "GET",
                f"{self._settings.tinyfish_agent_url}/v1/runs/{run_id}",
                service=SERVICE,
                max_retries=self._settings.http_max_retries,
            )
        self._raise_for_known_status(response)
        if response.status_code != 200:
            msg = f"Agent poll returned HTTP {response.status_code}"
            raise ExternalServiceError(SERVICE, msg, status_code=response.status_code)
        return AgentRunStatus.model_validate(response.json())

    def run_agent(
        self,
        url: str,
        goal: str,
        output_schema: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ) -> AgentOutcome:
        timeout = (
            self._settings.tinyfish_agent_poll_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        interval = (
            self._settings.tinyfish_agent_poll_interval_seconds
            if poll_interval_seconds is None
            else poll_interval_seconds
        )

        try:
            run_id = self.start_agent_run(url, goal, output_schema)
        except ExternalServiceError as exc:
            return AgentOutcome(None, "FAILED", None, None, str(exc))

        deadline = time.monotonic() + timeout
        last: AgentRunStatus | None = None
        while time.monotonic() < deadline:
            try:
                last = self.get_agent_run(run_id)
            except ExternalServiceError as exc:
                return AgentOutcome(run_id, "FAILED", None, None, str(exc))
            if last.is_terminal:
                return AgentOutcome(run_id, last.status, last.result, last.num_of_steps, last.error)
            time.sleep(interval)

        logger.warning("agent run timed out", extra={"run_id": run_id, "timeout": timeout})
        return AgentOutcome(
            run_id,
            "TIMEOUT",
            None,
            last.num_of_steps if last else None,
            f"run did not finish within {timeout:g}s",
        )


def build_client_or_none(settings: Settings | None = None) -> TinyFishClient | None:
    settings = settings or get_settings()
    if not settings.tinyfish_enabled:
        return None
    return TinyFishClient(settings)
