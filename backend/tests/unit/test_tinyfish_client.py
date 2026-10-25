from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from endemica.core.config import Settings
from endemica.core.errors import ExternalServiceError
from endemica.tinyfish.client import (
    MAX_FETCH_URLS,
    TinyFishAuthError,
    TinyFishClient,
    TinyFishCreditsExhaustedError,
    TinyFishNotConfiguredError,
    build_client_or_none,
)
from endemica.tinyfish.schemas import OUTPUT_SCHEMA

FETCH_URL = "https://api.fetch.tinyfish.ai"
AGENT_URL = "https://agent.tinyfish.ai"
SEARCH_URL = "https://api.search.tinyfish.ai"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TinyFishClient:
    monkeypatch.setenv("TINYFISH_API_KEY", "test-key-value")
    monkeypatch.setenv("ENDEMICA_HTTP_MAX_RETRIES", "0")
    return TinyFishClient(Settings())


class TestConfiguration:
    def test_missing_key_raises(self) -> None:
        with pytest.raises(TinyFishNotConfiguredError):
            TinyFishClient(Settings())

    def test_build_client_or_none_returns_none_without_a_key(self) -> None:
        assert build_client_or_none(Settings()) is None

    def test_build_client_or_none_returns_a_client_with_a_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TINYFISH_API_KEY", "k")
        assert build_client_or_none(Settings()) is not None


class TestFetch:
    @respx.mock
    def test_fetch_parses_the_documented_shape(
        self, client: TinyFishClient, load_json_fixture: Any
    ) -> None:
        payload = load_json_fixture("tinyfish/fetch_don622_response.json")
        respx.post(FETCH_URL).mock(return_value=httpx.Response(200, json=payload))
        response = client.fetch(["https://example.invalid/a"])
        assert len(response.results) == 1
        assert response.results[0].text
        assert response.errors == []

    @respx.mock
    def test_api_key_is_sent_as_a_header(self, client: TinyFishClient) -> None:
        route = respx.post(FETCH_URL).mock(return_value=httpx.Response(200, json={"results": []}))
        client.fetch(["https://example.invalid/a"])
        assert route.calls.last.request.headers["X-API-Key"] == "test-key-value"

    @respx.mock
    def test_null_published_date_is_tolerated(self, client: TinyFishClient) -> None:
        """The live API returns null for WHO pages."""
        respx.post(FETCH_URL).mock(
            return_value=httpx.Response(
                200, json={"results": [{"url": "u", "text": "t", "published_date": None}]}
            )
        )
        assert client.fetch(["u"]).results[0].published_date is None

    def test_empty_url_list_does_not_call_the_api(self, client: TinyFishClient) -> None:
        with respx.mock:
            assert client.fetch([]).results == []

    def test_too_many_urls_is_rejected_before_the_call(self, client: TinyFishClient) -> None:
        with pytest.raises(ValueError, match=str(MAX_FETCH_URLS)):
            client.fetch([f"https://example.invalid/{i}" for i in range(MAX_FETCH_URLS + 1)])

    @respx.mock
    def test_401_raises_an_auth_error(self, client: TinyFishClient) -> None:
        respx.post(FETCH_URL).mock(return_value=httpx.Response(401, json={}))
        with pytest.raises(TinyFishAuthError):
            client.fetch(["u"])

    @respx.mock
    def test_402_raises_credits_exhausted(self, client: TinyFishClient) -> None:
        respx.post(FETCH_URL).mock(return_value=httpx.Response(402, json={}))
        with pytest.raises(TinyFishCreditsExhaustedError):
            client.fetch(["u"])

    @respx.mock
    def test_other_errors_raise_external_service_error(self, client: TinyFishClient) -> None:
        respx.post(FETCH_URL).mock(return_value=httpx.Response(400, json={}))
        with pytest.raises(ExternalServiceError):
            client.fetch(["u"])

    @respx.mock
    def test_transport_failure_raises(self, client: TinyFishClient) -> None:
        respx.post(FETCH_URL).mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(ExternalServiceError):
            client.fetch(["u"])


class TestSearch:
    @respx.mock
    def test_search_parses_the_documented_shape(
        self, client: TinyFishClient, load_json_fixture: Any
    ) -> None:
        payload = load_json_fixture("tinyfish/search_who_response.json")
        respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))
        response = client.search("outbreak", include_domains=["who.int"])
        assert response.results
        assert all(r.url for r in response.results)

    @respx.mock
    def test_domain_filter_is_sent(self, client: TinyFishClient) -> None:
        route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"results": []}))
        client.search("q", include_domains=["who.int", "ecdc.europa.eu"])
        assert "who.int" in str(route.calls.last.request.url)


class TestAgent:
    @respx.mock
    def test_successful_run_returns_the_result(
        self, client: TinyFishClient, load_json_fixture: Any
    ) -> None:
        completed = load_json_fixture("tinyfish/agent_run_don622_completed.json")
        respx.post(f"{AGENT_URL}/v1/automation/run-async").mock(
            return_value=httpx.Response(200, json={"run_id": "r1", "error": None})
        )
        respx.get(f"{AGENT_URL}/v1/runs/r1").mock(return_value=httpx.Response(200, json=completed))
        outcome = client.run_agent("https://example.invalid/a", "goal", OUTPUT_SCHEMA)
        assert outcome.succeeded
        assert outcome.result is not None
        assert outcome.steps == 8

    @respx.mock
    def test_polls_until_terminal(self, client: TinyFishClient) -> None:
        respx.post(f"{AGENT_URL}/v1/automation/run-async").mock(
            return_value=httpx.Response(200, json={"run_id": "r1"})
        )
        bodies = [
            {"run_id": "r1", "status": "PENDING"},
            {"run_id": "r1", "status": "RUNNING"},
            {"run_id": "r1", "status": "COMPLETED", "result": {"disease": "x", "locations": []}},
        ]
        calls = iter(bodies)

        def next_body(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=next(calls))

        respx.get(f"{AGENT_URL}/v1/runs/r1").mock(side_effect=next_body)
        outcome = client.run_agent(
            "u", "g", OUTPUT_SCHEMA, poll_interval_seconds=0.0, timeout_seconds=5.0
        )
        assert outcome.succeeded

    @respx.mock
    @pytest.mark.parametrize("status", ["FAILED", "CANCELLED"])
    def test_terminal_failure_is_reported_not_raised(
        self, client: TinyFishClient, status: str
    ) -> None:
        respx.post(f"{AGENT_URL}/v1/automation/run-async").mock(
            return_value=httpx.Response(200, json={"run_id": "r1"})
        )
        respx.get(f"{AGENT_URL}/v1/runs/r1").mock(
            return_value=httpx.Response(
                200, json={"run_id": "r1", "status": status, "error": "site blocked"}
            )
        )
        outcome = client.run_agent("u", "g", OUTPUT_SCHEMA, poll_interval_seconds=0.0)
        assert not outcome.succeeded
        assert outcome.status == status

    @respx.mock
    def test_timeout_is_reported_not_raised(self, client: TinyFishClient) -> None:
        respx.post(f"{AGENT_URL}/v1/automation/run-async").mock(
            return_value=httpx.Response(200, json={"run_id": "r1"})
        )
        respx.get(f"{AGENT_URL}/v1/runs/r1").mock(
            return_value=httpx.Response(200, json={"run_id": "r1", "status": "RUNNING"})
        )
        outcome = client.run_agent(
            "u", "g", OUTPUT_SCHEMA, timeout_seconds=0.01, poll_interval_seconds=0.0
        )
        assert outcome.status == "TIMEOUT"
        assert outcome.error is not None

    @respx.mock
    def test_start_failure_is_reported_not_raised(self, client: TinyFishClient) -> None:
        """An ingestion run must survive the Agent being unavailable."""
        respx.post(f"{AGENT_URL}/v1/automation/run-async").mock(
            return_value=httpx.Response(500, json={})
        )
        outcome = client.run_agent("u", "g", OUTPUT_SCHEMA, poll_interval_seconds=0.0)
        assert outcome.status == "FAILED"
        assert outcome.result is None

    @respx.mock
    def test_start_error_field_is_honoured(self, client: TinyFishClient) -> None:
        respx.post(f"{AGENT_URL}/v1/automation/run-async").mock(
            return_value=httpx.Response(200, json={"run_id": None, "error": "bad schema"})
        )
        outcome = client.run_agent("u", "g", OUTPUT_SCHEMA, poll_interval_seconds=0.0)
        assert outcome.status == "FAILED"
        assert outcome.error is not None and "bad schema" in outcome.error

    @respx.mock
    def test_max_steps_is_never_sent(self, client: TinyFishClient) -> None:
        """max_steps is beta-gated and returns 403 when not enabled."""
        route = respx.post(f"{AGENT_URL}/v1/automation/run-async").mock(
            return_value=httpx.Response(200, json={"run_id": "r1"})
        )
        respx.get(f"{AGENT_URL}/v1/runs/r1").mock(
            return_value=httpx.Response(200, json={"run_id": "r1", "status": "FAILED"})
        )
        client.run_agent("u", "g", OUTPUT_SCHEMA, poll_interval_seconds=0.0)
        import json

        body = json.loads(route.calls.last.request.content)
        assert "max_steps" not in body
        assert set(body) == {"url", "goal", "output_schema"}


class TestSecretHandling:
    @respx.mock
    def test_key_is_not_in_the_client_repr(self, client: TinyFishClient) -> None:
        assert "test-key-value" not in repr(client)

    @respx.mock
    def test_key_is_not_logged(
        self, client: TinyFishClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        respx.post(FETCH_URL).mock(side_effect=httpx.ConnectError("refused"))
        with caplog.at_level("DEBUG"), pytest.raises(ExternalServiceError):
            client.fetch(["https://example.invalid/a"])
        assert "test-key-value" not in caplog.text
