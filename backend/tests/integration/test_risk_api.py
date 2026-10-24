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
ORIGIN = "ZZO"
DEST = "ZZD"
OTHER = "ZZX"


@pytest.fixture
def seeded(db_session: Session) -> Session:
    db_session.add_all(
        [
            Country(
                iso3=ORIGIN,
                name="Origin Land",
                population=20_000_000,
                population_year=2024,
                centroid_lat=0.0,
                centroid_lon=10.0,
            ),
            Country(
                iso3=DEST,
                name="Destination Land",
                population=50_000_000,
                population_year=2024,
                centroid_lat=40.0,
                centroid_lon=0.0,
            ),
            Country(
                iso3=OTHER,
                name="Unconnected Land",
                population=1_000_000,
                population_year=2024,
                centroid_lat=-20.0,
                centroid_lon=50.0,
            ),
        ]
    )
    db_session.flush()
    db_session.add_all(
        [
            CountryFlow(
                origin_iso3=ORIGIN,
                dest_iso3=DEST,
                passengers_per_day=2000.0,
                value_type=ValueType.OBSERVED,
                source="test_observed",
                reference_period="2019",
            ),
            CountryFlow(
                origin_iso3=DEST,
                dest_iso3=ORIGIN,
                passengers_per_day=1900.0,
                value_type=ValueType.OBSERVED,
                source="test_observed",
            ),
        ]
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

    # Two reports a fortnight apart per pathogen, so incidence differencing applies.
    # The vector-borne pair exists so that "importation estimable, establishment
    # not estimable" can be tested as a real combination rather than by absence.
    plan = [
        ("respiratory_default", timedelta(days=20), 1000, 50),
        ("respiratory_default", timedelta(days=4), 2400, 110),
        ("vector_borne", timedelta(days=18), 500, 2),
        ("vector_borne", timedelta(days=3), 900, 4),
    ]
    for index, (pathogen_key, offset, cases, deaths) in enumerate(plan):
        report = OutbreakReport(
            source_name="Test source",
            source_identifier=f"TEST-{index}",
            source_url=f"https://example.invalid/report/{index}",
            published_at=NOW - offset,
            retrieved_at=NOW,
            title=f"Test {pathogen_key} outbreak - Origin Land",
            disease_label=f"Test {pathogen_key} disease",
            pathogen_key=pathogen_key,
            narrative_text=f"A cumulative total of {cases} confirmed cases and {deaths} deaths.",
            content_sha256=f"{index:064d}",
            extraction_method=ExtractionMethod.DETERMINISTIC_PARSER,
            extraction_status=ExtractionStatus.VERIFIED,
            run_id=run.id,
        )
        db_session.add(report)
        db_session.flush()
        db_session.add(
            OutbreakObservation(
                report_id=report.id,
                country_iso3=ORIGIN,
                cases_confirmed=cases,
                deaths=deaths,
                evidence_text=f"A cumulative total of {cases} confirmed cases and {deaths} deaths.",
                grounding_status=ExtractionStatus.VERIFIED,
                value_type=ValueType.OBSERVED,
            )
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


def _risk(client: TestClient, iso3: str = DEST, **params: Any) -> dict[str, Any]:
    params.setdefault("pathogen", "respiratory_default")
    response = client.get(f"/api/v1/risk/{iso3}", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


class TestThreeQuantitiesStaySeparate:
    def test_presence_is_reported_only_where_cases_were_reported(self, client: TestClient) -> None:
        assert _risk(client, ORIGIN)["presence"]["status"] == "reported"
        assert _risk(client, DEST)["presence"]["status"] == "not_reported"

    def test_flight_connectivity_is_not_evidence_of_presence(self, client: TestClient) -> None:
        """The destination has heavy inbound traffic and still reports no presence."""
        body = _risk(client, DEST)
        assert body["importation"]["probability"]["central"] > 0
        assert body["presence"]["status"] == "not_reported"
        assert "never used as evidence" in body["presence"]["detail"]

    def test_raising_passenger_volume_raises_importation_but_not_presence(
        self, client: TestClient
    ) -> None:
        low = _risk(client, passenger_scale=0.5)
        high = _risk(client, passenger_scale=4.0)
        assert (
            high["importation"]["probability"]["central"]
            > low["importation"]["probability"]["central"]
        )
        assert low["presence"]["status"] == high["presence"]["status"]

    def test_raising_screening_lowers_importation_but_not_presence(
        self, client: TestClient
    ) -> None:
        without = _risk(client, sigma=0.0)
        with_screening = _risk(client, sigma=0.9)
        assert (
            with_screening["importation"]["probability"]["central"]
            < without["importation"]["probability"]["central"]
        )
        assert without["presence"]["status"] == with_screening["presence"]["status"]

    def test_establishment_is_zero_when_r_is_at_most_one(self, client: TestClient) -> None:
        body = _risk(client, reproduction_number=0.9)
        assert body["establishment"]["probability_within_horizon"]["central"] == 0.0
        assert body["establishment"]["subcritical"] is True
        # Importation is unaffected: arrival and establishment are different events.
        assert body["importation"]["probability"]["central"] > 0

    def test_establishment_never_exceeds_importation(self, client: TestClient) -> None:
        for scale in (0.5, 1.0, 5.0):
            body = _risk(client, passenger_scale=scale, reproduction_number=3.0)
            assert (
                body["establishment"]["probability_within_horizon"]["central"]
                <= body["importation"]["probability"]["central"] + 1e-12
            )


class TestBandsAndValueTypes:
    def test_bands_are_ordered(self, client: TestClient) -> None:
        band = _risk(client)["importation"]["probability"]
        assert band["low"] <= band["central"] <= band["high"]

    def test_band_is_labelled_as_a_scenario_range(self, client: TestClient) -> None:
        band = _risk(client)["importation"]["probability"]
        assert "scenario range" in band["band_basis"]
        assert "Not a confidence interval" in band["band_basis"]

    def test_modelled_outputs_are_labelled_modelled(self, client: TestClient) -> None:
        body = _risk(client)
        assert body["importation"]["probability"]["value_type"] == "modelled"
        assert body["establishment"]["probability_per_introduction"]["value_type"] == "modelled"

    def test_observed_presence_is_labelled_observed(self, client: TestClient) -> None:
        assert _risk(client, ORIGIN)["presence"]["value_type"] == "observed"

    def test_wider_underreporting_widens_the_band(self, client: TestClient) -> None:
        narrow = _risk(
            client, underreporting_low=3, underreporting_central=4, underreporting_high=5
        )["importation"]["probability"]
        wide = _risk(
            client, underreporting_low=1, underreporting_central=4, underreporting_high=50
        )["importation"]["probability"]
        assert (wide["high"] - wide["low"]) > (narrow["high"] - narrow["low"])


class TestNotEstimableBehaviour:
    def test_destination_with_no_connected_outbreak_is_not_estimable(
        self, client: TestClient
    ) -> None:
        body = _risk(client, OTHER)
        probability = body["importation"]["probability"]
        assert probability["central"] is None
        assert probability["value_type"] == "unknown"
        assert probability["unavailable_reason"] is not None

    def test_missing_value_is_null_never_zero(self, client: TestClient) -> None:
        probability = _risk(client, OTHER)["importation"]["probability"]
        assert probability["low"] is None
        assert probability["central"] is None
        assert probability["high"] is None

    def test_excluded_origins_are_reported_with_reasons(self, client: TestClient) -> None:
        excluded = _risk(client, OTHER)["importation"]["excluded_origins"]
        assert excluded
        assert all("reason" in entry for entry in excluded)

    def test_vector_borne_establishment_is_not_estimable(self, client: TestClient) -> None:
        body = _risk(client, DEST, pathogen="vector_borne")
        establishment = body["establishment"]["probability_per_introduction"]
        assert establishment["central"] is None
        assert establishment["unavailable_reason"] == "model_not_applicable"
        assert body["pathogen"]["establishment_estimable"] is False
        # Importation remains estimable for a vector-borne pathogen.
        assert body["importation"]["probability"]["central"] is not None


class TestTransparency:
    def test_every_assumption_states_its_source(self, client: TestClient) -> None:
        assumptions = _risk(client)["assumptions"]
        assert assumptions
        assert all(a["source"] for a in assumptions)

    def test_user_supplied_values_are_attributed_to_the_user(self, client: TestClient) -> None:
        assumptions = {a["key"]: a for a in _risk(client, sigma=0.5)["assumptions"]}
        assert assumptions["sigma"]["value"] == 0.5
        assert assumptions["sigma"]["source"] == "user"

    def test_profile_defaults_are_attributed_to_the_profile(self, client: TestClient) -> None:
        assumptions = {a["key"]: a for a in _risk(client)["assumptions"]}
        assert "profile default" in assumptions["alpha"]["source"]

    def test_top_origins_carry_provenance(self, client: TestClient) -> None:
        origins = _risk(client)["importation"]["top_origins"]
        assert origins
        top = origins[0]
        assert top["origin_iso3"] == ORIGIN
        assert top["report_url"]
        assert top["passengers_value_type"] == "observed"
        assert top["passengers_source"] == "test_observed"

    def test_response_carries_the_disclaimer(self, client: TestClient) -> None:
        assert "not an official forecast" in _risk(client)["disclaimer"].lower()

    def test_response_carries_data_freshness(self, client: TestClient) -> None:
        assert _risk(client)["data"]

    def test_scenario_markers_are_labelled_as_scenarios(self, client: TestClient) -> None:
        markers = _risk(client)["scenario_markers"]
        assert markers
        assert all("Scenario marker" in m["detail"] for m in markers)


class TestErrorBehaviour:
    def test_unknown_country_returns_404(self, client: TestClient) -> None:
        response = client.get("/api/v1/risk/QQQ")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    @pytest.mark.parametrize(
        "params",
        [
            {"horizon_days": 0},
            {"horizon_days": 500},
            {"sigma": 1.0},
            {"alpha": 2.0},
            {"threshold": 0},
            {"threshold": 1},
            {"dispersion_k": 0},
            {"passenger_scale": 0},
        ],
    )
    def test_out_of_range_parameters_return_422(
        self, client: TestClient, params: dict[str, Any]
    ) -> None:
        response = client.get(f"/api/v1/risk/{DEST}", params=params)
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_request"

    def test_unknown_pathogen_is_rejected(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/risk/{DEST}", params={"pathogen": "made_up"})
        assert response.status_code == 500
        assert "code" in response.json()


class TestOtherEndpoints:
    def test_countries_lists_seeded_countries(self, client: TestClient) -> None:
        body = client.get("/api/v1/countries").json()
        codes = {c["iso3"] for c in body["items"]}
        assert {ORIGIN, DEST, OTHER} <= codes

    def test_country_with_outbreak_is_flagged(self, client: TestClient) -> None:
        items = {c["iso3"]: c for c in client.get("/api/v1/countries").json()["items"]}
        assert items[ORIGIN]["has_reported_outbreak"] is True
        assert items[DEST]["has_reported_outbreak"] is False

    def test_outbreaks_list_includes_provenance(self, client: TestClient) -> None:
        body = client.get("/api/v1/outbreaks", params={"limit": 10}).json()
        assert body["total"] >= 4
        report = body["items"][0]
        assert report["provenance"]["source_url"]
        assert report["provenance"]["retrieved_at"]
        assert report["extraction_status"]

    def test_outbreak_detail_includes_grounding_verdicts(self, client: TestClient) -> None:
        listing = client.get("/api/v1/outbreaks", params={"limit": 1}).json()
        report_id = listing["items"][0]["id"]
        detail = client.get(f"/api/v1/outbreaks/{report_id}").json()
        assert "narrative_text" in detail
        assert "grounding_fields" in detail

    def test_unknown_outbreak_returns_404(self, client: TestClient) -> None:
        assert client.get(f"/api/v1/outbreaks/{uuid.uuid4()}").status_code == 404

    def test_routes_are_filterable_by_destination(self, client: TestClient) -> None:
        body = client.get("/api/v1/routes", params={"dest": DEST, "limit": 10}).json()
        assert body["items"]
        assert all(item["dest_iso3"] == DEST for item in body["items"])

    def test_routes_state_their_value_type(self, client: TestClient) -> None:
        body = client.get("/api/v1/routes", params={"dest": DEST}).json()
        assert all(item["value_type"] in {"observed", "estimated"} for item in body["items"])

    def test_sources_list_limitations(self, client: TestClient) -> None:
        body = client.get("/api/v1/sources").json()
        assert body["items"]
        assert all(item["limitations"] for item in body["items"])
        assert all(item["licence"] for item in body["items"])

    def test_pathogens_expose_their_references(self, client: TestClient) -> None:
        body = client.get("/api/v1/pathogens").json()
        assert body
        assert all(profile["references"] for profile in body)

    def test_runs_report_ingestion_history(self, client: TestClient) -> None:
        body = client.get("/api/v1/runs").json()
        assert body
        assert body[0]["status"] in {"succeeded", "failed", "running"}
