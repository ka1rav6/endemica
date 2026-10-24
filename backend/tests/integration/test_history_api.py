"""The archive-wide views, and the rule that picks a destination's disease.

A destination used to be answered about whatever disease was published most
recently anywhere, so every country looked alike and two infected countries
could not be told apart. These tests pin the replacement behaviour.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from epiroute.core.config import Settings, get_settings
from epiroute.db.models import (
    Country,
    CountryFlow,
    IngestionRun,
    OutbreakObservation,
    OutbreakReport,
)
from epiroute.db.session import get_db
from epiroute.main import create_app
from epiroute.schemas.common import ExtractionMethod, ExtractionStatus, ValueType

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)

# Two countries that each report a different disease, plus one that reports
# nothing. ``ZZA`` also carries an outbreak that ended long ago.
ALPHA = "ZZA"
BETA = "ZZB"
QUIET = "ZZQ"


def _report(
    session: Session,
    run_id: uuid.UUID,
    *,
    index: int,
    disease_key: str,
    disease_name: str,
    pathogen_key: str,
    published_at: datetime,
    iso3: str,
    cases: int | None,
    deaths: int | None,
) -> None:
    narrative = (
        f"A cumulative total of {cases} confirmed cases and {deaths} deaths."
        if cases is not None and deaths is not None
        else "No figure could be grounded."
    )
    report = OutbreakReport(
        source_name="Test source",
        source_identifier=f"HIST-{index}",
        source_url=f"https://example.invalid/report/{index}",
        published_at=published_at,
        retrieved_at=NOW,
        title=f"{disease_name} - {iso3}",
        disease_label=disease_name,
        disease_key=disease_key,
        disease_name=disease_name,
        disease_family="Test family",
        pathogen_key=pathogen_key,
        narrative_text=narrative,
        content_sha256=f"{index:064d}",
        extraction_method=ExtractionMethod.DETERMINISTIC_PARSER,
        extraction_status=ExtractionStatus.VERIFIED,
        run_id=run_id,
    )
    session.add(report)
    session.flush()
    session.add(
        OutbreakObservation(
            report_id=report.id,
            country_iso3=iso3,
            cases_confirmed=cases,
            deaths=deaths,
            evidence_text=narrative,
            grounding_status=(
                ExtractionStatus.VERIFIED if cases is not None else ExtractionStatus.NOT_ATTEMPTED
            ),
            value_type=ValueType.OBSERVED if cases is not None else ValueType.UNKNOWN,
        )
    )


@pytest.fixture
def seeded(db_session: Session) -> Session:
    db_session.add_all(
        [
            Country(
                iso3=ALPHA,
                name="Alpha Land",
                population=20_000_000,
                population_year=2024,
                centroid_lat=0.0,
                centroid_lon=10.0,
            ),
            Country(
                iso3=BETA,
                name="Beta Land",
                population=30_000_000,
                population_year=2024,
                centroid_lat=20.0,
                centroid_lon=30.0,
            ),
            Country(
                iso3=QUIET,
                name="Quiet Land",
                population=5_000_000,
                population_year=2024,
                centroid_lat=-10.0,
                centroid_lon=-40.0,
            ),
        ]
    )
    db_session.flush()
    db_session.add(
        CountryFlow(
            origin_iso3=ALPHA,
            dest_iso3=BETA,
            passengers_per_day=1500.0,
            value_type=ValueType.OBSERVED,
            source="test_observed",
        )
    )
    run = IngestionRun(
        id=uuid.uuid4(),
        mode="direct_fetch",
        status="succeeded",
        started_at=NOW - timedelta(minutes=5),
        finished_at=NOW,
    )
    db_session.add(run)
    db_session.flush()

    # "redfever" is the newest thing published anywhere and belongs to ALPHA.
    _report(
        db_session,
        run.id,
        index=0,
        disease_key="redfever",
        disease_name="Red fever",
        pathogen_key="respiratory_default",
        published_at=NOW - timedelta(days=18),
        iso3=ALPHA,
        cases=1000,
        deaths=50,
    )
    _report(
        db_session,
        run.id,
        index=1,
        disease_key="redfever",
        disease_name="Red fever",
        pathogen_key="respiratory_default",
        published_at=NOW - timedelta(days=3),
        iso3=ALPHA,
        cases=2400,
        deaths=110,
    )
    # BETA reports a different disease, slightly older.
    _report(
        db_session,
        run.id,
        index=2,
        disease_key="bluepox",
        disease_name="Blue pox",
        pathogen_key="vector_borne",
        published_at=NOW - timedelta(days=30),
        iso3=BETA,
        cases=300,
        deaths=4,
    )
    # An outbreak that ran years ago, to prove history is not only "now".
    _report(
        db_session,
        run.id,
        index=3,
        disease_key="oldplague",
        disease_name="Old plague",
        pathogen_key="respiratory_default",
        published_at=datetime(2004, 5, 1, tzinfo=UTC),
        iso3=ALPHA,
        cases=80,
        deaths=9,
    )
    _report(
        db_session,
        run.id,
        index=4,
        disease_key="oldplague",
        disease_name="Old plague",
        pathogen_key="respiratory_default",
        published_at=datetime(2006, 9, 1, tzinfo=UTC),
        iso3=BETA,
        cases=None,
        deaths=None,
    )
    db_session.flush()
    return db_session


@pytest.fixture
def client(seeded: Session) -> Iterator[TestClient]:
    settings = Settings()
    app = create_app(settings)
    app.dependency_overrides[get_db] = lambda: seeded
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client


def _get(client: TestClient, path: str, **params: Any) -> dict[str, Any]:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _list(client: TestClient, path: str) -> list[dict[str, Any]]:
    response = client.get(path)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


class TestDestinationDecidesItsOwnDisease:
    def test_each_country_is_answered_about_the_disease_it_reports(
        self, client: TestClient
    ) -> None:
        alpha = _get(client, f"/api/v1/risk/{ALPHA}")
        beta = _get(client, f"/api/v1/risk/{BETA}")
        assert alpha["pathogen"]["disease_key"] == "redfever"
        assert beta["pathogen"]["disease_key"] == "bluepox"
        assert alpha["pathogen"]["disease_source"] == "destination_record"
        assert beta["pathogen"]["disease_source"] == "destination_record"

    def test_both_countries_report_presence_for_their_own_disease(self, client: TestClient) -> None:
        """The bug: BETA was asked about ALPHA's disease and came back empty."""
        assert _get(client, f"/api/v1/risk/{ALPHA}")["presence"]["status"] == "reported"
        assert _get(client, f"/api/v1/risk/{BETA}")["presence"]["status"] == "reported"

    def test_a_country_with_no_report_falls_back_and_says_so(self, client: TestClient) -> None:
        body = _get(client, f"/api/v1/risk/{QUIET}")
        assert body["presence"]["status"] == "not_reported"
        assert body["pathogen"]["disease_source"] == "global_latest"
        codes = {warning["code"] for warning in body["warnings"]}
        assert "disease_inferred_globally" in codes

    def test_an_explicit_disease_puts_both_countries_on_one_question(
        self, client: TestClient
    ) -> None:
        alpha = _get(client, f"/api/v1/risk/{ALPHA}", disease_key="redfever")
        beta = _get(client, f"/api/v1/risk/{BETA}", disease_key="redfever")
        assert alpha["pathogen"]["disease_key"] == beta["pathogen"]["disease_key"] == "redfever"
        assert alpha["pathogen"]["disease_source"] == "requested"
        assert alpha["presence"]["status"] == "reported"
        assert beta["presence"]["status"] == "not_reported"

    def test_an_unknown_disease_key_is_a_404(self, client: TestClient) -> None:
        assert (
            client.get(f"/api/v1/risk/{ALPHA}", params={"disease_key": "nope"}).status_code == 404
        )

    def test_origins_are_drawn_from_the_same_disease(self, client: TestClient) -> None:
        """ALPHA flies to BETA, so BETA can import ALPHA's disease but not its own."""
        body = _get(client, f"/api/v1/risk/{BETA}", disease_key="redfever")
        origins = [origin["origin_iso3"] for origin in body["importation"]["top_origins"]]
        assert origins == [ALPHA]


class TestDiseaseHistory:
    def test_lists_diseases_that_ended_years_ago(self, client: TestClient) -> None:
        keys = {entry["disease_key"] for entry in _list(client, "/api/v1/diseases/history")}
        assert {"redfever", "bluepox", "oldplague"} <= keys

    def test_reports_the_full_span_of_an_old_outbreak(self, client: TestClient) -> None:
        entries = _list(client, "/api/v1/diseases/history")
        old = next(entry for entry in entries if entry["disease_key"] == "oldplague")
        assert old["first_published_at"].startswith("2004")
        assert old["last_published_at"].startswith("2006")
        assert old["country_count"] == 2

    def test_cases_sum_per_country_peaks_rather_than_per_report(self, client: TestClient) -> None:
        entries = _list(client, "/api/v1/diseases/history")
        red = next(entry for entry in entries if entry["disease_key"] == "redfever")
        # Two cumulative reports for one country: 1000 then 2400, not 3400.
        assert red["cases_confirmed"] == 2400
        assert red["deaths"] == 110


class TestDiseaseSpread:
    def test_countries_come_back_in_order_of_arrival(self, client: TestClient) -> None:
        body = _get(client, "/api/v1/diseases/oldplague/spread")
        order = [country["country_iso3"] for country in body["countries"]]
        assert order == [ALPHA, BETA]
        assert [country["arrival_order"] for country in body["countries"]] == [1, 2]

    def test_a_country_with_no_grounded_count_still_appears(self, client: TestClient) -> None:
        body = _get(client, "/api/v1/diseases/oldplague/spread")
        beta = next(c for c in body["countries"] if c["country_iso3"] == BETA)
        assert beta["grounded"] is False
        assert beta["cases_confirmed"] is None
        assert beta["first_published_at"].startswith("2006")

    def test_the_timeline_accumulates_newly_reached_countries(self, client: TestClient) -> None:
        body = _get(client, "/api/v1/diseases/oldplague/spread")
        years = {point["year"]: point for point in body["timeline"]}
        assert years[2004]["cumulative_country_count"] == 1
        assert years[2006]["new_country_count"] == 1
        assert years[2006]["cumulative_country_count"] == 2

    def test_an_old_outbreak_is_not_marked_active(self, client: TestClient) -> None:
        assert _get(client, "/api/v1/diseases/oldplague/spread")["is_active"] is False
        assert _get(client, "/api/v1/diseases/redfever/spread")["is_active"] is True

    def test_an_unknown_disease_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/diseases/nope/spread").status_code == 404


class TestCountryProfile:
    def test_lists_every_disease_ever_reported_there(self, client: TestClient) -> None:
        body = _get(client, f"/api/v1/countries/{ALPHA}/profile")
        keys = {disease["disease_key"] for disease in body["diseases"]}
        assert keys == {"redfever", "oldplague"}

    def test_separates_what_is_active_now_from_what_is_history(self, client: TestClient) -> None:
        body = _get(client, f"/api/v1/countries/{ALPHA}/profile")
        by_key = {disease["disease_key"]: disease for disease in body["diseases"]}
        assert by_key["redfever"]["is_active"] is True
        assert by_key["oldplague"]["is_active"] is False
        assert body["active_disease_count"] == 1

    def test_orders_by_most_recent_activity(self, client: TestClient) -> None:
        body = _get(client, f"/api/v1/countries/{ALPHA}/profile")
        assert body["diseases"][0]["disease_key"] == "redfever"

    def test_a_country_with_no_report_is_empty_rather_than_an_error(
        self, client: TestClient
    ) -> None:
        body = _get(client, f"/api/v1/countries/{QUIET}/profile")
        assert body["diseases"] == []
        assert body["report_count"] == 0

    def test_an_unknown_country_is_a_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/countries/ZZZ/profile").status_code == 404


class TestAllActiveDiseasesAtOnce:
    """The "active" view: every current disease answered as one question."""

    def test_the_summary_lists_only_currently_reported_diseases(self, client: TestClient) -> None:
        body = _get(client, "/api/v1/diseases/active")
        keys = {disease["disease_key"] for disease in body["diseases"]}
        assert {"redfever", "bluepox"} <= keys
        assert "oldplague" not in keys

    def test_the_summary_says_which_countries_and_which_diseases(self, client: TestClient) -> None:
        body = _get(client, "/api/v1/diseases/active")
        by_iso3 = {country["country_iso3"]: country for country in body["countries"]}
        assert by_iso3[ALPHA]["disease_names"] == ["Red fever"]
        assert by_iso3[BETA]["disease_names"] == ["Blue pox"]
        assert QUIET not in by_iso3

    def test_a_country_case_total_sums_its_active_diseases(self, client: TestClient) -> None:
        body = _get(client, "/api/v1/diseases/active")
        alpha = next(c for c in body["countries"] if c["country_iso3"] == ALPHA)
        # Two cumulative Red fever reports, so the peak counts once.
        assert alpha["cases_confirmed"] == 2400

    def test_importation_covers_every_active_disease_at_once(self, client: TestClient) -> None:
        single = _get(client, f"/api/v1/risk/{BETA}", disease_key="redfever")
        aggregate = _get(client, f"/api/v1/risk/{BETA}", scope="active")
        assert aggregate["pathogen"]["scope"] == "active"
        assert {"Red fever", "Blue pox"} <= set(aggregate["pathogen"]["active_diseases"])
        # Adding a disease can only add arrivals, never remove them.
        assert (
            aggregate["importation"]["arrival_rate_per_day"]["central"]
            >= single["importation"]["arrival_rate_per_day"]["central"]
        )

    def test_each_origin_is_labelled_with_the_disease_it_carries(self, client: TestClient) -> None:
        body = _get(client, f"/api/v1/risk/{BETA}", scope="active")
        origins = body["importation"]["top_origins"]
        assert origins, "ALPHA flies to BETA and reports an active disease"
        assert {origin["disease_name"] for origin in origins} == {"Red fever"}

    def test_presence_reports_every_active_disease_found_here(self, client: TestClient) -> None:
        body = _get(client, f"/api/v1/risk/{ALPHA}", scope="active")
        assert body["presence"]["status"] == "reported"
        assert "Red fever" in body["presence"]["detail"]

    def test_establishment_is_withheld_rather_than_averaged(self, client: TestClient) -> None:
        """Pathogens have different R and k, so one combined figure means nothing."""
        body = _get(client, f"/api/v1/risk/{BETA}", scope="active")
        establishment = body["establishment"]
        assert establishment["probability_within_horizon"]["central"] is None
        assert (
            establishment["probability_within_horizon"]["unavailable_reason"]
            == "model_not_applicable"
        )

    def test_the_aggregate_scope_is_declared_in_the_warnings(self, client: TestClient) -> None:
        body = _get(client, f"/api/v1/risk/{ALPHA}", scope="active")
        codes = {warning["code"] for warning in body["warnings"]}
        assert "aggregate_scope" in codes

    def test_an_unknown_scope_is_rejected(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/risk/{ALPHA}", params={"scope": "everything"})
        assert response.status_code == 422
