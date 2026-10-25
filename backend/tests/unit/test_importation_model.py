"""Tests for the Poisson importation model.

Covers everything AGENTS.md section 8.4 requires, and reproduces the reference
values published in the research briefing note. The reference checks are
genuine independent checks: the expected numbers come from the note's chart,
not from re-running this implementation.
"""

from __future__ import annotations

import math

import pytest

from endemica.core.errors import ModelInputError
from endemica.epidemiology.importation import (
    MAX_SIGMA,
    OriginContribution,
    arrival_rate_from_origin,
    days_to_probability_threshold,
    importation_rate,
    is_saturated,
    probability_at_least_one_arrival,
)


class TestReferenceValues:
    """Reproduce the briefing note's 14-day illustrative chart.

    The note states: "At 10 per 100,000, 50 passengers a day is about 3%, and
    2,000 a day is about 75%. At 1,000 per 100,000, a 50-passenger route is
    already about 97%." Model: alpha = 0.5, sigma = 0, T = 14 days.
    """

    HORIZON = 14.0
    ALPHA = 0.5

    @pytest.mark.parametrize(
        ("prevalence_per_100k", "passengers_per_day", "expected_percent"),
        [
            (10, 50, 3.0),
            (10, 2000, 75.0),
            (1000, 50, 97.0),
        ],
    )
    def test_chart_values_are_reproduced(
        self, prevalence_per_100k: float, passengers_per_day: float, expected_percent: float
    ) -> None:
        prevalence = prevalence_per_100k / 100_000
        rate = arrival_rate_from_origin(prevalence, passengers_per_day, self.ALPHA, 0.0)
        probability = probability_at_least_one_arrival(rate, self.HORIZON)
        # The note quotes the values to the nearest whole percent ("about 3%"),
        # so a 0.5 percentage-point tolerance is the right strictness.
        assert probability * 100 == pytest.approx(expected_percent, abs=0.5)

    def test_full_chart_is_monotone_across_both_axes(self) -> None:
        """Probability must rise with both prevalence and passenger volume."""
        volumes = [50, 200, 500, 2000, 8000]
        prevalences = [10 / 1e5, 100 / 1e5, 1000 / 1e5]
        grid = [
            [
                probability_at_least_one_arrival(
                    arrival_rate_from_origin(p, v, self.ALPHA), self.HORIZON
                )
                for v in volumes
            ]
            for p in prevalences
        ]
        for row in grid:
            assert row == sorted(row), "probability must not fall as volume rises"
        for column in zip(*grid, strict=True):
            assert list(column) == sorted(column), "probability must not fall as prevalence rises"


class TestArrivalRate:
    def test_rate_is_the_product_of_its_four_terms(self) -> None:
        assert arrival_rate_from_origin(0.001, 1000.0, 0.5, 0.0) == pytest.approx(0.5)

    def test_screening_reduces_the_rate_proportionally(self) -> None:
        base = arrival_rate_from_origin(0.001, 1000.0, 0.5, 0.0)
        screened = arrival_rate_from_origin(0.001, 1000.0, 0.5, 0.6)
        assert screened == pytest.approx(base * 0.4)

    def test_zero_passengers_gives_zero_rate(self) -> None:
        assert arrival_rate_from_origin(0.5, 0.0, 1.0, 0.0) == 0.0

    def test_zero_prevalence_gives_zero_rate(self) -> None:
        assert arrival_rate_from_origin(0.0, 1e6, 1.0, 0.0) == 0.0

    @pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), float("inf")])
    def test_invalid_prevalence_is_rejected(self, bad: float) -> None:
        with pytest.raises(ModelInputError, match="prevalence"):
            arrival_rate_from_origin(bad, 100.0, 0.5, 0.0)

    @pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan")])
    def test_invalid_alpha_is_rejected(self, bad: float) -> None:
        with pytest.raises(ModelInputError, match="alpha"):
            arrival_rate_from_origin(0.001, 100.0, bad, 0.0)

    def test_sigma_above_the_documented_maximum_is_rejected(self) -> None:
        """sigma = 1 would claim perfect screening; the note caps it near 0.9."""
        with pytest.raises(ModelInputError, match="sigma"):
            arrival_rate_from_origin(0.001, 100.0, 0.5, 1.0)

    def test_sigma_at_the_maximum_is_accepted(self) -> None:
        rate = arrival_rate_from_origin(0.001, 1000.0, 1.0, MAX_SIGMA)
        assert rate == pytest.approx(1.0 * (1 - MAX_SIGMA))

    @pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
    def test_invalid_passenger_flow_is_rejected(self, bad: float) -> None:
        with pytest.raises(ModelInputError, match="passengers_per_day"):
            arrival_rate_from_origin(0.001, bad, 0.5, 0.0)


class TestProbability:
    def test_zero_rate_gives_zero_probability(self) -> None:
        assert probability_at_least_one_arrival(0.0, 14.0) == 0.0

    def test_zero_horizon_gives_zero_probability(self) -> None:
        assert probability_at_least_one_arrival(10.0, 0.0) == 0.0

    @pytest.mark.parametrize("rate", [1e-9, 1e-4, 0.1, 1.0, 10.0, 100.0])
    def test_probability_stays_within_the_valid_range(self, rate: float) -> None:
        for horizon in (0.5, 14.0, 365.0):
            p = probability_at_least_one_arrival(rate, horizon)
            assert 0.0 <= p <= 1.0

    def test_probability_is_non_decreasing_in_rate(self) -> None:
        rates = [0.0, 1e-6, 1e-3, 0.01, 0.1, 1.0, 5.0]
        values = [probability_at_least_one_arrival(r, 14.0) for r in rates]
        assert values == sorted(values)

    def test_probability_is_non_decreasing_in_horizon(self) -> None:
        horizons = [0.0, 1.0, 7.0, 14.0, 30.0, 90.0]
        values = [probability_at_least_one_arrival(0.05, t) for t in horizons]
        assert values == sorted(values)

    def test_tiny_exponents_keep_precision(self) -> None:
        """expm1 must be used: 1 - exp(-1e-12) loses most significant digits."""
        p = probability_at_least_one_arrival(1e-12, 1.0)
        assert p == pytest.approx(1e-12, rel=1e-9)
        assert p > 0.0

    def test_known_analytic_value(self) -> None:
        """At lambda*T = 1, P = 1 - 1/e exactly."""
        assert probability_at_least_one_arrival(0.5, 2.0) == pytest.approx(1 - 1 / math.e)

    @pytest.mark.parametrize(
        ("rate", "horizon"), [(-1.0, 14.0), (1.0, -1.0), (float("nan"), 1.0), (1.0, float("inf"))]
    )
    def test_invalid_inputs_are_rejected(self, rate: float, horizon: float) -> None:
        with pytest.raises(ModelInputError):
            probability_at_least_one_arrival(rate, horizon)

    def test_saturation_is_detected(self) -> None:
        assert is_saturated(100.0, 14.0) is True
        assert is_saturated(0.01, 14.0) is False
        # At saturation the float result is exactly 1.0, which is why the UI
        # needs to know rather than printing "100.0%".
        assert probability_at_least_one_arrival(100.0, 14.0) == 1.0


class TestImportationRateAggregation:
    def _contribution(self, iso3: str, rate: float) -> OriginContribution:
        return OriginContribution(
            origin_iso3=iso3,
            prevalence=0.001,
            passengers_per_day=rate / 0.0005,
            alpha=0.5,
            sigma=0.0,
            rate_per_day=rate,
        )

    def test_total_is_the_sum_of_contributions(self) -> None:
        result = importation_rate([self._contribution("AAA", 0.2), self._contribution("BBB", 0.3)])
        assert result.rate_per_day == pytest.approx(0.5)

    def test_contributions_are_sorted_descending(self) -> None:
        result = importation_rate(
            [
                self._contribution("SMALL", 0.01),
                self._contribution("BIG", 1.0),
                self._contribution("MID", 0.1),
            ]
        )
        assert [c.origin_iso3 for c in result.contributions] == ["BIG", "MID", "SMALL"]

    def test_empty_input_gives_a_zero_rate(self) -> None:
        result = importation_rate([])
        assert result.rate_per_day == 0.0
        assert result.usable_origin_count == 0

    def test_zero_rate_origins_are_kept_but_not_counted_as_usable(self) -> None:
        """A route with no flow is still shown; it just contributes nothing."""
        result = importation_rate([self._contribution("ZERO", 0.0)])
        assert len(result.contributions) == 1
        assert result.usable_origin_count == 0

    def test_summation_is_numerically_stable(self) -> None:
        """fsum must be used: many tiny contributions must not lose magnitude."""
        contributions = [self._contribution(f"C{i:03d}", 1e-10) for i in range(10_000)]
        result = importation_rate(contributions)
        assert result.rate_per_day == pytest.approx(1e-6, rel=1e-12)


class TestThresholdInversion:
    def test_inversion_round_trips(self) -> None:
        """The day returned must actually reach the threshold."""
        rate, threshold = 0.05, 0.5
        day = days_to_probability_threshold(rate, threshold)
        assert day is not None
        assert probability_at_least_one_arrival(rate, day) >= threshold
        # And the day before must not, confirming it is the *first* such day.
        assert probability_at_least_one_arrival(rate, day - 1) < threshold

    def test_zero_rate_has_no_threshold_day(self) -> None:
        assert days_to_probability_threshold(0.0, 0.5) is None

    def test_unreachable_threshold_within_the_horizon_returns_none(self) -> None:
        assert days_to_probability_threshold(1e-6, 0.99, max_days=30.0) is None

    def test_higher_rate_reaches_the_threshold_sooner(self) -> None:
        fast = days_to_probability_threshold(1.0, 0.5)
        slow = days_to_probability_threshold(0.01, 0.5)
        assert fast is not None and slow is not None
        assert fast < slow

    @pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5, float("nan")])
    def test_invalid_threshold_is_rejected(self, bad: float) -> None:
        with pytest.raises(ModelInputError, match="threshold"):
            days_to_probability_threshold(0.1, bad)
