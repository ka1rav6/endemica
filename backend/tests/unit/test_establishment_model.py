"""Tests for the branching-process establishment model.

The important tests here verify the solver against results derived
independently of the implementation:

* k = 1 (geometric offspring) has the closed form q = 1/R.
* k -> infinity reduces to the Poisson case q = exp(-R(1-q)).
* A bisection root-find on g(q) - q is an algorithmically different solver.

A test that merely re-evaluated the same formula would prove nothing
(AGENTS.md section 8.4).
"""

from __future__ import annotations

import math

import pytest

from epiroute.core.errors import ModelInputError
from epiroute.epidemiology.establishment import (
    days_to_establishment_threshold,
    probability_of_establishment_within,
    solve_establishment,
)


def _bisection_extinction_probability(reproduction_number: float, dispersion_k: float) -> float:
    """Smallest root of g(q) = q found by bisection, independent of the solver."""

    def f(q: float) -> float:
        return float((1.0 + reproduction_number * (1.0 - q) / dispersion_k) ** (-dispersion_k) - q)

    low, high = 0.0, 1.0 - 1e-15
    assert f(low) > 0, "g(0) must exceed 0 for a supercritical process"
    for _ in range(300):
        mid = (low + high) / 2.0
        if f(mid) > 0:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


class TestAnalyticBenchmarks:
    @pytest.mark.parametrize("reproduction_number", [1.5, 2.0, 2.5, 4.0, 10.0])
    def test_geometric_offspring_matches_one_over_r(self, reproduction_number: float) -> None:
        """For k = 1 the negative binomial is geometric and q = 1/R exactly."""
        result = solve_establishment(reproduction_number, 1.0)
        assert result.extinction_probability == pytest.approx(1.0 / reproduction_number, abs=1e-10)

    @pytest.mark.parametrize("reproduction_number", [1.5, 2.5, 4.0])
    def test_large_k_matches_the_poisson_limit(self, reproduction_number: float) -> None:
        """As k grows the offspring distribution becomes Poisson."""
        q = 0.0
        for _ in range(100_000):
            q = math.exp(-reproduction_number * (1.0 - q))
        result = solve_establishment(reproduction_number, 1e9)
        assert result.extinction_probability == pytest.approx(q, abs=1e-9)

    @pytest.mark.parametrize(
        ("reproduction_number", "dispersion_k"),
        [(2.5, 0.1), (2.5, 0.5), (1.5, 0.1), (3.0, 0.3), (1.2, 0.2), (5.0, 1.0), (2.0, 10.0)],
    )
    def test_solver_agrees_with_bisection(
        self, reproduction_number: float, dispersion_k: float
    ) -> None:
        expected = _bisection_extinction_probability(reproduction_number, dispersion_k)
        result = solve_establishment(reproduction_number, dispersion_k)
        assert result.extinction_probability == pytest.approx(expected, abs=1e-9)

    def test_covid_like_reference_value(self) -> None:
        """The submission deck quotes 14% for R = 2.5, k = 0.1 (COVID-like)."""
        result = solve_establishment(2.5, 0.1)
        assert result.establishment_probability * 100 == pytest.approx(14.0, abs=0.5)


class TestSubcriticalBehaviour:
    @pytest.mark.parametrize("reproduction_number", [0.0, 0.1, 0.5, 0.99, 1.0])
    def test_establishment_is_exactly_zero_when_r_is_at_most_one(
        self, reproduction_number: float
    ) -> None:
        result = solve_establishment(reproduction_number, 0.3)
        assert result.establishment_probability == 0.0
        assert result.extinction_probability == 1.0
        assert result.subcritical is True

    def test_subcritical_case_needs_no_iteration(self) -> None:
        """The closed form avoids slow convergence towards q = 1."""
        assert solve_establishment(1.0, 0.1).iterations == 0

    def test_just_above_one_is_supercritical_but_tiny(self) -> None:
        result = solve_establishment(1.001, 0.3)
        assert result.subcritical is False
        assert 0.0 < result.establishment_probability < 0.02


class TestQualitativeBehaviour:
    def test_establishment_rises_with_r(self) -> None:
        values = [
            solve_establishment(r, 0.3).establishment_probability for r in (1.1, 1.5, 2.0, 3.0, 5.0)
        ]
        assert values == sorted(values)

    def test_establishment_rises_with_k_at_fixed_r(self) -> None:
        """Less overdispersion means fewer chains die out by chance."""
        values = [
            solve_establishment(2.5, k).establishment_probability
            for k in (0.05, 0.1, 0.5, 1.0, 10.0)
        ]
        assert values == sorted(values)

    def test_overdispersion_matters_a_lot(self) -> None:
        """The point of tracking k: same R, very different per-introduction risk."""
        clustered = solve_establishment(2.5, 0.1).establishment_probability
        poisson_like = solve_establishment(2.5, 1e9).establishment_probability
        assert clustered < 0.2
        assert poisson_like > 0.85

    @pytest.mark.parametrize(
        ("reproduction_number", "dispersion_k"),
        [(1.01, 0.01), (50.0, 0.001), (1.0001, 100.0), (100.0, 100.0)],
    )
    def test_output_stays_a_valid_probability_at_extremes(
        self, reproduction_number: float, dispersion_k: float
    ) -> None:
        result = solve_establishment(reproduction_number, dispersion_k)
        assert 0.0 <= result.extinction_probability <= 1.0
        assert 0.0 <= result.establishment_probability <= 1.0


class TestParameterValidation:
    @pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
    def test_invalid_r_is_rejected(self, bad: float) -> None:
        with pytest.raises(ModelInputError, match="reproduction_number"):
            solve_establishment(bad, 0.3)

    @pytest.mark.parametrize("bad", [0.0, -0.5, float("nan"), float("inf")])
    def test_invalid_k_is_rejected(self, bad: float) -> None:
        with pytest.raises(ModelInputError, match="dispersion_k"):
            solve_establishment(2.0, bad)


class TestEstablishmentOverHorizon:
    def test_poisson_thinning_formula(self) -> None:
        """P = 1 - exp(-lambda*T*(1-q)), checked against a separate computation."""
        rate, horizon, r, k = 0.5, 14.0, 2.5, 0.1
        one_minus_q = solve_establishment(r, k).establishment_probability
        expected = 1.0 - math.exp(-rate * horizon * one_minus_q)
        assert probability_of_establishment_within(rate, horizon, r, k) == pytest.approx(expected)

    def test_zero_when_r_is_subcritical_regardless_of_arrivals(self) -> None:
        """Many arrivals of a non-transmissible pathogen still cannot establish."""
        assert probability_of_establishment_within(1000.0, 365.0, 0.9, 0.1) == 0.0

    def test_zero_arrivals_gives_zero(self) -> None:
        assert probability_of_establishment_within(0.0, 14.0, 2.5, 0.1) == 0.0

    def test_zero_horizon_gives_zero(self) -> None:
        assert probability_of_establishment_within(5.0, 0.0, 2.5, 0.1) == 0.0

    def test_establishment_never_exceeds_importation(self) -> None:
        """A chain cannot establish without an arrival, so P(est) <= P(import)."""
        from epiroute.epidemiology.importation import probability_at_least_one_arrival

        for rate in (0.001, 0.01, 0.1, 1.0, 10.0):
            for horizon in (1.0, 14.0, 90.0):
                imported = probability_at_least_one_arrival(rate, horizon)
                established = probability_of_establishment_within(rate, horizon, 2.5, 0.1)
                assert established <= imported + 1e-12

    def test_rises_with_both_rate_and_horizon(self) -> None:
        by_rate = [
            probability_of_establishment_within(r, 14.0, 2.5, 0.3) for r in (0.0, 0.1, 1.0, 10.0)
        ]
        by_horizon = [
            probability_of_establishment_within(0.5, t, 2.5, 0.3) for t in (0.0, 7.0, 14.0, 60.0)
        ]
        assert by_rate == sorted(by_rate)
        assert by_horizon == sorted(by_horizon)

    @pytest.mark.parametrize(("rate", "horizon"), [(-1.0, 14.0), (1.0, -1.0), (float("nan"), 1.0)])
    def test_invalid_inputs_are_rejected(self, rate: float, horizon: float) -> None:
        with pytest.raises(ModelInputError):
            probability_of_establishment_within(rate, horizon, 2.5, 0.1)


class TestEstablishmentThreshold:
    def test_threshold_day_round_trips(self) -> None:
        day = days_to_establishment_threshold(0.5, 0.5, 2.5, 0.1)
        assert day is not None
        assert probability_of_establishment_within(0.5, day, 2.5, 0.1) >= 0.5
        assert probability_of_establishment_within(0.5, day - 1, 2.5, 0.1) < 0.5

    def test_subcritical_pathogen_has_no_threshold_day(self) -> None:
        assert days_to_establishment_threshold(10.0, 0.5, 0.9, 0.1) is None

    def test_zero_arrival_rate_has_no_threshold_day(self) -> None:
        assert days_to_establishment_threshold(0.0, 0.5, 2.5, 0.1) is None

    def test_establishment_threshold_is_never_earlier_than_import_threshold(self) -> None:
        """Establishment requires an arrival first, so its marker cannot lead."""
        from epiroute.epidemiology.importation import days_to_probability_threshold

        rate = 0.2
        import_day = days_to_probability_threshold(rate, 0.5)
        establish_day = days_to_establishment_threshold(rate, 0.5, 2.5, 0.3)
        assert import_day is not None and establish_day is not None
        assert establish_day >= import_day
