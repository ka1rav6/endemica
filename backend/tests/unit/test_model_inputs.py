"""Which extracted numbers are allowed to become a prevalence input."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from epiroute.db.models import OutbreakObservation
from epiroute.ingestion.validate import validate_location
from epiroute.schemas.common import ExtractionStatus, ValueType
from epiroute.services.outbreaks import _usable_for_models
from epiroute.tinyfish.schemas import ExtractedLocation

SOURCE = "Ituri remains the epicentre, with 7040 cumulative confirmed cases and 3271 deaths."
PUBLISHED = datetime(2026, 10, 23, tzinfo=UTC)


def _observation(**overrides: object) -> OutbreakObservation:
    values: dict[str, object] = {
        "report_id": uuid.uuid4(),
        "country_iso3": "COD",
        "grounding_status": ExtractionStatus.PARTIAL,
        "value_type": ValueType.OBSERVED,
        "cases_confirmed": 7040,
        "deaths": 3271,
    }
    values.update(overrides)
    return OutbreakObservation(**values)


class TestPartialRowsKeepGroundedCounts:
    def test_a_hallucinated_sibling_does_not_drop_the_real_count(self) -> None:
        observation, warnings = validate_location(
            ExtractedLocation(
                country="Democratic Republic of the Congo",
                subnational="Ituri",
                cases_confirmed=7040,
                cases_suspected=9291,
                deaths=3271,
                evidence=SOURCE,
            ),
            source_text=SOURCE,
            report_published_at=PUBLISHED,
        )
        assert observation is not None
        assert observation.grounding_status is ExtractionStatus.PARTIAL
        assert observation.cases_confirmed == 7040
        assert observation.deaths == 3271
        assert observation.cases_suspected is None
        assert observation.value_type is ValueType.OBSERVED
        assert any(warning["field"] == "cases_suspected" for warning in warnings)

    def test_partial_row_with_a_grounded_count_may_feed_the_model(self) -> None:
        assert _usable_for_models(_observation()) is True

    def test_unverified_row_may_not_feed_the_model(self) -> None:
        row = _observation(
            grounding_status=ExtractionStatus.UNVERIFIED,
            value_type=ValueType.UNKNOWN,
            cases_confirmed=9291,
            deaths=None,
        )
        assert _usable_for_models(row) is False

    def test_partial_row_with_nothing_left_may_not_feed_the_model(self) -> None:
        row = _observation(cases_confirmed=None, deaths=None)
        assert _usable_for_models(row) is False
