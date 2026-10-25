"""The 0–10 travel-risk index is a weighted mean, not a forecast."""

from __future__ import annotations

import inspect
import math
from datetime import UTC, datetime, timedelta

import pytest

from endemica.epidemiology.travel_index import (
    CONNECTIVITY_RATE_CAP,
    CONNECTIVITY_RATE_FLOOR,
    LARGE_CONFIRMED_CASES,
    NOTE,
    PROBABILITY_CAP,
    PROBABILITY_FLOOR,
    WEIGHTS,
    TravelComponentScore,
    TravelIndexInputs,
    TravelIndexResult,
    band_for,
    compute_travel_index,
    round_tenths,
    score_connectivity,
    score_probability,
)

AS_OF = datetime(2026, 10, 24, tzinfo=UTC)


def _index(**overrides: object) -> TravelIndexResult:
    payload = {
        "presence_status": "not_estimable",
        "as_of": AS_OF,
    }
    payload.update(overrides)
    return compute_travel_index(TravelIndexInputs(**payload))  # type: ignore[arg-type]


def _component(result: TravelIndexResult, key: str) -> TravelComponentScore:
    return next(component for component in result.components if component.key == key)


class TestPresence:
    def test_no_report_scores_zero_and_is_not_treated_as_missing(self) -> None:
        # The presence term itself is measured: nothing was reported here.
        result = _index(presence_status="not_reported", importation_probability=0.01)
        presence = _component(result, "presence")
        assert presence.available is True
        assert presence.score == 0
        assert result.score is not None

    def test_nothing_but_an_absent_presence_is_not_an_index(self) -> None:
        # "Not reported here" and nothing else is absence of evidence. Scoring
        # it 0.0 Low reads as a finding of no risk, and reads the same for a
        # neighbour of the outbreak as for an island on the far side of the
        # world. This is what made most diseases show 0.0 everywhere.
        result = _index(presence_status="not_reported")
        assert result.score is None
        assert result.band is None
        assert _component(result, "presence").score == 0

    def test_a_country_that_has_reported_still_scores_on_presence_alone(self) -> None:
        # A positive presence term is a real measurement of local risk, so it
        # stands on its own even when nothing else can be estimated.
        result = _index(presence_status="reported")
        assert result.score is not None
        assert result.score > 0

    def test_unknown_status_is_omitted(self) -> None:
        result = _index(presence_status="not_estimable")
        assert _component(result, "presence").available is False
        assert result.score is None
        assert result.band is None

    def test_report_older_than_90_days_scores_4_even_with_a_large_count(self) -> None:
        result = _index(
            presence_status="reported",
            last_reported_at=AS_OF - timedelta(days=91),
            cases_confirmed=10_000,
        )
        assert _component(result, "presence").score == 4
        assert result.score == 4

    def test_unknown_report_date_is_not_treated_as_recent(self) -> None:
        result = _index(presence_status="reported", last_reported_at=None, cases_confirmed=500)
        assert _component(result, "presence").score == 4

    def test_exactly_90_days_still_counts_as_recent(self) -> None:
        result = _index(
            presence_status="reported",
            last_reported_at=AS_OF - timedelta(days=90),
            cases_confirmed=10,
        )
        assert _component(result, "presence").score == 7

    def test_one_second_past_90_days_is_stale(self) -> None:
        result = _index(
            presence_status="reported",
            last_reported_at=AS_OF - timedelta(days=90, seconds=1),
            cases_confirmed=LARGE_CONFIRMED_CASES,
        )
        assert _component(result, "presence").score == 4

    def test_recent_report_with_100_confirmed_scores_9(self) -> None:
        result = _index(
            presence_status="reported",
            last_reported_at=AS_OF - timedelta(days=1),
            cases_confirmed=100,
        )
        assert _component(result, "presence").score == 9

    def test_recent_report_below_the_case_threshold_scores_7(self) -> None:
        result = _index(
            presence_status="reported",
            last_reported_at=AS_OF - timedelta(days=1),
            cases_confirmed=99,
        )
        assert _component(result, "presence").score == 7

    def test_recent_report_without_a_case_figure_scores_7(self) -> None:
        result = _index(
            presence_status="reported",
            last_reported_at=AS_OF - timedelta(days=1),
            cases_confirmed=None,
        )
        assert _component(result, "presence").score == 7

    def test_naive_timestamps_are_read_as_utc(self) -> None:
        result = _index(
            presence_status="reported",
            last_reported_at=datetime(2026, 10, 20),
            as_of=datetime(2026, 10, 24),
            cases_confirmed=5,
        )
        assert _component(result, "presence").score == 7


class TestProbabilities:
    def test_probability_is_scored_on_orders_of_magnitude(self) -> None:
        # Floor 1e-6 and cap 0.1 are five decades apart, so 1e-3.5 is halfway.
        assert _component(_index(importation_probability=10**-3.5), "importation").score == (
            pytest.approx(5)
        )
        assert (
            _component(_index(importation_probability=PROBABILITY_FLOOR), "importation").score == 0
        )
        assert (
            _component(_index(importation_probability=PROBABILITY_CAP), "importation").score == 10
        )

    def test_probability_above_the_cap_is_clamped(self) -> None:
        result = _index(importation_probability=1.4)
        assert _component(result, "importation").score == 10

    def test_small_probabilities_still_separate_destinations(self) -> None:
        # The whole point of the log scale: a thousandfold difference in
        # probability must not collapse onto the same displayed score.
        raw = [
            _component(_index(importation_probability=p), "importation").score
            for p in (1e-5, 1e-4, 1e-3)
        ]
        assert all(score is not None for score in raw)
        scores = [float(score) for score in raw if score is not None]
        assert scores == sorted(scores)
        assert len(set(scores)) == 3

    def test_a_real_zero_is_kept(self) -> None:
        result = _index(establishment_probability=0.0)
        establishment = _component(result, "establishment")
        assert establishment.available is True
        assert establishment.score == 0
        assert result.score == 0

    def test_missing_probability_is_omitted_rather_than_scored_as_zero(self) -> None:
        result = _index(presence_status="reported", last_reported_at=AS_OF, cases_confirmed=10)
        assert _component(result, "importation").available is False
        assert _component(result, "establishment").available is False
        # 7, not 7 × 0.40. The missing terms do not dilute the score.
        assert result.score == 7

    def test_nan_probability_is_missing(self) -> None:
        result = _index(importation_probability=math.nan, establishment_probability=math.nan)
        assert _component(result, "importation").available is False
        assert result.score is None


class TestConnectivity:
    def test_endpoints_of_the_log_scale(self) -> None:
        assert score_connectivity(0) == 0
        assert score_connectivity(-3) == 0
        assert score_connectivity(CONNECTIVITY_RATE_FLOOR) == 0
        assert score_connectivity(CONNECTIVITY_RATE_CAP) == 10
        assert score_connectivity(25) == 10

    def test_midpoint_of_the_log_span_is_5(self) -> None:
        # Floor 1e-6 and cap 1 are six decades apart. Three decades up is halfway.
        assert score_connectivity(1e-3) == pytest.approx(5)

    def test_the_scale_rises_with_rate(self) -> None:
        rates = [0, 1e-6, 1e-4, 1e-2, 0.1, 1, 4]
        scores = [score_connectivity(rate) for rate in rates]
        assert scores == sorted(scores)
        assert scores[0] == 0
        assert scores[-1] == 10

    def test_rate_of_zero_scores_zero(self) -> None:
        result = _index(arrival_rate_per_day=0, top_origin_share=1)
        connectivity = _component(result, "connectivity")
        assert connectivity.available is True
        assert connectivity.score == 0

    def test_share_without_a_rate_is_not_invented_as_zero_or_as_a_score(self) -> None:
        result = _index(top_origin_share=0.8)
        assert _component(result, "connectivity").available is False
        assert result.score is None

    def test_origin_rates_are_used_only_when_the_aggregate_is_missing(self) -> None:
        from_origins = _index(origin_rates=(0.5, 0.5), top_origin_share=0.5)
        assert _component(from_origins, "connectivity").score == 10
        # A listed origin must not override the aggregate, even if it is larger.
        capped = _index(arrival_rate_per_day=1e-3, origin_rates=(50,), top_origin_share=1)
        assert _component(capped, "connectivity").score == pytest.approx(5)

    def test_nan_aggregate_falls_through_to_origin_rates(self) -> None:
        result = _index(arrival_rate_per_day=math.nan, origin_rates=(1.0,))
        assert _component(result, "connectivity").score == 10


class TestCombination:
    def test_nominal_weights_when_every_input_exists(self) -> None:
        result = _index(
            presence_status="not_reported",
            importation_probability=10**-3.5,
            establishment_probability=10**-4.5,
            arrival_rate_per_day=1e-3,
        )
        # 0×0.40 + 5×0.30 + 3×0.15 + 5×0.15 = 2.7
        assert result.score == pytest.approx(2.7)
        assert result.band == "Low"
        for key, weight in WEIGHTS.items():
            component = _component(result, key)
            assert component.available is True
            assert component.weight == pytest.approx(weight)
        assert [component.key for component in result.components] == list(WEIGHTS)

    def test_weights_are_renormalised_over_the_inputs_that_exist(self) -> None:
        result = _index(presence_status="not_reported", importation_probability=0.0)
        presence = _component(result, "presence")
        importation = _component(result, "importation")
        assert presence.weight == pytest.approx(0.40 / 0.70)
        assert importation.weight == pytest.approx(0.30 / 0.70)
        assert _component(result, "establishment").weight == 0
        assert _component(result, "connectivity").weight == 0
        # (0×0.40 + 0×0.30) / 0.70 = 0, not a diluted non-zero.
        assert result.score == 0

    def test_a_high_presence_score_is_not_pulled_down_by_missing_inputs(self) -> None:
        result = _index(
            presence_status="reported",
            last_reported_at=AS_OF,
            cases_confirmed=100,
        )
        assert result.score == 9
        assert _component(result, "presence").weight == pytest.approx(1)

    def test_nothing_available_is_not_estimable(self) -> None:
        result = _index()
        assert result.score is None
        assert result.band is None
        assert all(component.available is False for component in result.components)
        assert all(component.score is None for component in result.components)

    def test_displayed_scores_are_one_decimal_half_up(self) -> None:
        assert round_tenths(1.25) == pytest.approx(1.3)
        assert round_tenths(2.94) == pytest.approx(2.9)
        assert round_tenths(2.95) == pytest.approx(3.0)
        # The mean is taken on the unrounded component scores, then rounded once.
        result = _index(establishment_probability=0.023, importation_probability=0.0018)
        establishment = score_probability(0.023)
        importation = score_probability(0.0018)
        assert establishment is not None
        assert importation is not None
        assert _component(result, "establishment").score == pytest.approx(
            round_tenths(establishment)
        )
        raw = (importation * 0.30 + establishment * 0.15) / 0.45
        assert result.score == pytest.approx(round_tenths(raw))

    @pytest.mark.parametrize(
        ("score", "band"),
        [
            (0, "Low"),
            (2.9, "Low"),
            (3.0, "Moderate"),
            (5.9, "Moderate"),
            (6.0, "High"),
            (7.9, "High"),
            (8.0, "Very high"),
            (10, "Very high"),
        ],
    )
    def test_bands_follow_the_rounded_index(self, score: float, band: str) -> None:
        assert band_for(score) == band

    def test_the_note_refuses_forecast_status(self) -> None:
        result = _index(presence_status="not_reported")
        assert result.note == NOTE
        assert "composite scenario index" in result.note
        assert "not a forecast" in result.note
        assert "official travel advice" in result.note
        assert "calibrated" not in result.note.lower()

    def test_the_next_country_model_is_not_an_input(self) -> None:
        parameters = inspect.signature(compute_travel_index).parameters
        assert "forecast" not in parameters
        assert "next_country" not in parameters
        assert set(parameters) == {"inputs"}
