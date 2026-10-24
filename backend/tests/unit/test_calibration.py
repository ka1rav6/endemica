"""The hazard rises with lambda, and two sources either agree or they don't."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from epiroute.calibration.gates import all_passed, evaluate_gates
from epiroute.calibration.hazard import HazardCoefficients, fit_hazard, probability
from epiroute.datasets.dot_t100 import agreement_rate, direct_flows, undirected_country_totals
from epiroute.datasets.eurostat import ObservedFlow
from epiroute.datasets.openflights import Airport
from epiroute.datasets.worldbank import compare
from epiroute.ingestion.corroborate import CountPoint, corroborate


def test_a_higher_arrival_rate_raises_the_probability() -> None:
    coefficients = HazardCoefficients(-2.0, 1.0, 0.0)
    low = probability(coefficients, np.array([-8.0]), np.array([7.0]), 28.0)
    high = probability(coefficients, np.array([-2.0]), np.array([7.0]), 28.0)
    assert high[0] > low[0]


def test_the_fitted_slope_on_lambda_does_not_go_negative() -> None:
    rng = np.random.default_rng(0)
    log_lambda = rng.normal(size=200)
    labels = (log_lambda + rng.normal(scale=0.5, size=200) > 0).astype(float)
    fitted = fit_hazard(log_lambda, np.full(200, 7.0), labels, horizon_days=28.0)
    assert fitted.b1 >= 0


def test_gates_fail_a_model_that_is_no_better_than_the_baseline() -> None:
    labels = np.array([0.0, 1.0, 0.0, 1.0])
    predicted = np.array([0.5, 0.5, 0.5, 0.5])
    results = evaluate_gates(
        labels=labels,
        predicted=predicted,
        uncalibrated=predicted,
        best_simple=predicted,
        monotone=True,
    )
    assert not all_passed(results)


def test_counts_within_ten_percent_are_corroborated() -> None:
    moment = datetime(2026, 10, 1, tzinfo=UTC)
    primary = CountPoint("who_don", "covid_19", "KEN", "cases", 100, moment)
    other = CountPoint("ecdc_cdtr", "covid_19", "KEN", "cases", 108, moment)
    assert corroborate(primary, other).verdict == "corroborated"


def test_a_large_disagreement_is_held_for_review() -> None:
    moment = datetime(2026, 10, 1, tzinfo=UTC)
    primary = CountPoint("who_don", "measles", "NGA", "cases", 100, moment)
    other = CountPoint("ecdc_cdtr", "measles", "NGA", "cases", 400, moment)
    assert corroborate(primary, other).verdict == "gross_conflict"


def test_dot_total_is_compared_with_both_eurostat_directions(tmp_path) -> None:
    path = tmp_path / "dot.csv"
    path.write_text("usg_apt,fg_apt,sum_total\nJFK,LHR,200\n", encoding="utf-8")
    airports = {
        "JFK": Airport("JFK", None, "Kennedy", "USA", 40.6, -73.8),
        "LHR": Airport("LHR", None, "Heathrow", "GBR", 51.5, -0.5),
    }
    eurostat = {
        ("USA", "GBR"): ObservedFlow("USA", "GBR", 120, 2024, 1),
        ("GBR", "USA"): ObservedFlow("GBR", "USA", 80, 2024, 1),
    }
    _directed, checks = direct_flows(undirected_country_totals(path, airports), eurostat, year=2024)
    assert agreement_rate(checks) == 1.0


def test_population_gap_above_five_percent_is_flagged() -> None:
    flagged = compare(
        {"KEN": 50_000_000, "FRA": 68_000_000}, {"KEN": 40_000_000, "FRA": 68_100_000}
    )
    assert [row["iso3"] for row in flagged] == ["KEN"]
