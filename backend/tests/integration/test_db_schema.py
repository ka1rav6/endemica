"""The database constraints that enforce data correctness.

These test real PostgreSQL behaviour: a CHECK constraint that exists only in
the model definition is not a constraint. Marked `integration` because they
need a live database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from endemica.db.models import (
    Country,
    CountryFlow,
    GravityModelFit,
    IngestionRun,
    OutbreakObservation,
    OutbreakReport,
    PolicyFlag,
)
from endemica.schemas.common import ExtractionMethod, ExtractionStatus, ValueType

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def _country(session: Session, iso3: str = "ZZA", **kwargs: object) -> Country:
    country = Country(iso3=iso3, name=f"Test {iso3}", **kwargs)
    session.add(country)
    session.flush()
    return country


def _report(session: Session, identifier: str = "TEST-DON-1") -> OutbreakReport:
    report = OutbreakReport(
        source_name="Test source",
        source_identifier=identifier,
        source_url="https://example.invalid/report",
        retrieved_at=NOW,
        title="Test outbreak",
        content_sha256="0" * 64,
        extraction_method=ExtractionMethod.DETERMINISTIC_PARSER,
        extraction_status=ExtractionStatus.VERIFIED,
    )
    session.add(report)
    session.flush()
    return report


class TestCountryConstraints:
    def test_negative_population_is_rejected(self, db_session: Session) -> None:
        with pytest.raises(IntegrityError, match="population_non_negative"):
            _country(db_session, population=-1)

    @pytest.mark.parametrize(("lat", "lon"), [(91.0, 0.0), (-91.0, 0.0), (0.0, 181.0)])
    def test_out_of_range_centroid_is_rejected(
        self, db_session: Session, lat: float, lon: float
    ) -> None:
        with pytest.raises(IntegrityError, match="in_range"):
            _country(db_session, centroid_lat=lat, centroid_lon=lon)

    def test_zero_population_is_allowed(self, db_session: Session) -> None:
        """Zero is a legal observation; only negative values are impossible."""
        c = _country(db_session, population=0)
        assert c.population == 0


class TestObservationConstraints:
    def test_negative_case_count_is_rejected(self, db_session: Session) -> None:
        _country(db_session)
        report = _report(db_session)
        db_session.add(
            OutbreakObservation(
                report_id=report.id,
                country_iso3="ZZA",
                cases_confirmed=-5,
                grounding_status=ExtractionStatus.VERIFIED,
                value_type=ValueType.OBSERVED,
            )
        )
        with pytest.raises(IntegrityError, match="cases_confirmed_non_negative"):
            db_session.flush()

    def test_reversed_period_is_rejected(self, db_session: Session) -> None:
        _country(db_session)
        report = _report(db_session)
        db_session.add(
            OutbreakObservation(
                report_id=report.id,
                country_iso3="ZZA",
                period_start=date(2026, 5, 1),
                period_end=date(2026, 4, 1),
                grounding_status=ExtractionStatus.VERIFIED,
                value_type=ValueType.OBSERVED,
            )
        )
        with pytest.raises(IntegrityError, match="period_ordered"):
            db_session.flush()

    def test_all_counts_may_be_null(self, db_session: Session) -> None:
        """A report may name a place without stating any number."""
        _country(db_session)
        report = _report(db_session)
        obs = OutbreakObservation(
            report_id=report.id,
            country_iso3="ZZA",
            grounding_status=ExtractionStatus.UNVERIFIED,
            value_type=ValueType.UNKNOWN,
        )
        db_session.add(obs)
        db_session.flush()
        assert obs.cases_confirmed is None
        assert obs.deaths is None

    def test_duplicate_place_and_period_within_a_report_is_rejected(
        self, db_session: Session
    ) -> None:
        _country(db_session)
        report = _report(db_session)
        for _ in range(2):
            db_session.add(
                OutbreakObservation(
                    report_id=report.id,
                    country_iso3="ZZA",
                    subnational_name="Province A",
                    period_text="Jan 2026",
                    grounding_status=ExtractionStatus.VERIFIED,
                    value_type=ValueType.OBSERVED,
                )
            )
        with pytest.raises(IntegrityError, match="uq_observation_report_place_period"):
            db_session.flush()

    def test_observation_requires_a_known_country(self, db_session: Session) -> None:
        """An unmappable country name must not create a phantom country row."""
        report = _report(db_session)
        db_session.add(
            OutbreakObservation(
                report_id=report.id,
                country_iso3="QQQ",
                grounding_status=ExtractionStatus.VERIFIED,
                value_type=ValueType.OBSERVED,
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()


class TestReportConstraints:
    def test_same_identifier_from_the_same_source_is_rejected(self, db_session: Session) -> None:
        """Re-ingesting a bulletin must update, not duplicate."""
        _report(db_session, "DON-DUP")
        with pytest.raises(IntegrityError, match="uq_report_source_identifier"):
            _report(db_session, "DON-DUP")

    def test_deleting_a_report_cascades_to_its_observations(self, db_session: Session) -> None:
        _country(db_session)
        report = _report(db_session)
        db_session.add(
            OutbreakObservation(
                report_id=report.id,
                country_iso3="ZZA",
                cases_confirmed=3,
                grounding_status=ExtractionStatus.VERIFIED,
                value_type=ValueType.OBSERVED,
            )
        )
        db_session.flush()
        db_session.delete(report)
        db_session.flush()
        assert db_session.query(OutbreakObservation).filter_by(report_id=report.id).count() == 0

    def test_a_failed_run_does_not_remove_its_reports(self, db_session: Session) -> None:
        """AGENTS.md 9.5: a failed extraction must not erase valid records."""
        run = IngestionRun(mode="direct_fetch", status="running", started_at=NOW)
        db_session.add(run)
        db_session.flush()
        report = _report(db_session, "DON-KEEP")
        report.run_id = run.id
        db_session.flush()

        db_session.delete(run)
        db_session.flush()
        db_session.refresh(report)
        assert report.id is not None
        assert report.run_id is None  # ON DELETE SET NULL


class TestFlowConstraints:
    def test_self_flow_is_rejected(self, db_session: Session) -> None:
        _country(db_session, "ZZA")
        db_session.add(
            CountryFlow(
                origin_iso3="ZZA",
                dest_iso3="ZZA",
                passengers_per_day=10.0,
                value_type=ValueType.OBSERVED,
                source="test",
            )
        )
        with pytest.raises(IntegrityError, match="no_self_flow"):
            db_session.flush()

    def test_negative_passengers_is_rejected(self, db_session: Session) -> None:
        _country(db_session, "ZZA")
        _country(db_session, "ZZB")
        db_session.add(
            CountryFlow(
                origin_iso3="ZZA",
                dest_iso3="ZZB",
                passengers_per_day=-1.0,
                value_type=ValueType.OBSERVED,
                source="test",
            )
        )
        with pytest.raises(IntegrityError, match="passengers_non_negative"):
            db_session.flush()

    def test_uncertainty_factor_below_one_is_rejected(self, db_session: Session) -> None:
        """A multiplicative spread factor below 1 would invert the band."""
        _country(db_session, "ZZA")
        _country(db_session, "ZZB")
        db_session.add(
            CountryFlow(
                origin_iso3="ZZA",
                dest_iso3="ZZB",
                passengers_per_day=5.0,
                value_type=ValueType.ESTIMATED,
                source="gravity_model",
                uncertainty_factor=0.5,
            )
        )
        with pytest.raises(IntegrityError, match="uncertainty_factor_at_least_one"):
            db_session.flush()

    def test_directed_pair_is_the_primary_key(self, db_session: Session) -> None:
        """A->B and B->A are different flows and must both be storable."""
        _country(db_session, "ZZA")
        _country(db_session, "ZZB")
        db_session.add_all(
            [
                CountryFlow(
                    origin_iso3="ZZA",
                    dest_iso3="ZZB",
                    passengers_per_day=5.0,
                    value_type=ValueType.OBSERVED,
                    source="test",
                ),
                CountryFlow(
                    origin_iso3="ZZB",
                    dest_iso3="ZZA",
                    passengers_per_day=7.0,
                    value_type=ValueType.OBSERVED,
                    source="test",
                ),
            ]
        )
        db_session.flush()
        assert db_session.query(CountryFlow).count() >= 2


class TestPolicyFlagConstraints:
    def test_unknown_measure_is_rejected(self, db_session: Session) -> None:
        _country(db_session)
        db_session.add(
            PolicyFlag(
                country_iso3="ZZA",
                measure="total_lockdown",
                source_url="https://example.invalid/policy",
                retrieved_at=NOW,
            )
        )
        with pytest.raises(IntegrityError, match="measure_known"):
            db_session.flush()

    def test_sigma_outside_the_documented_range_is_rejected(self, db_session: Session) -> None:
        """The research note bounds screening effectiveness at about 0.9."""
        _country(db_session)
        db_session.add(
            PolicyFlag(
                country_iso3="ZZA",
                measure="entry_screening",
                sigma_if_confirmed=0.99,
                source_url="https://example.invalid/policy",
                retrieved_at=NOW,
            )
        )
        with pytest.raises(IntegrityError, match="sigma_in_documented_range"):
            db_session.flush()

    def test_a_new_flag_defaults_to_pending_review(self, db_session: Session) -> None:
        """An extracted policy claim must not take effect before a human confirms it."""
        _country(db_session)
        flag = PolicyFlag(
            country_iso3="ZZA",
            measure="entry_screening",
            source_url="https://example.invalid/policy",
            retrieved_at=NOW,
        )
        db_session.add(flag)
        db_session.flush()
        assert flag.status == "pending_review"


class TestGravityFitConstraints:
    def test_a_fit_must_have_training_rows(self, db_session: Session) -> None:
        db_session.add(
            GravityModelFit(
                id=uuid.uuid4(),
                fitted_at=NOW,
                specification="log10 F ~ 1",
                feature_names=["const"],
                coefficients={"const": 1.0},
                intercept=0.0,
                training_source="test",
                n_train=0,
                n_test=0,
                random_seed=0,
                metrics={"r2_log": 0.0},
                residual_sigma_log10=0.0,
            )
        )
        with pytest.raises(IntegrityError, match="n_train_positive"):
            db_session.flush()
