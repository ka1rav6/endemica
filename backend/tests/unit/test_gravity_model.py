from __future__ import annotations

import math

import numpy as np
import pytest

from endemica.core.errors import DataUnavailableError
from endemica.datasets.geo import great_circle_km
from endemica.datasets.gravity import (
    FEATURE_NAMES,
    MAX_UNCERTAINTY_FACTOR,
    MIN_TRAINING_ROWS,
    GravityFit,
    PairFeatures,
    build_feature_table,
    fit_gravity_model,
)


def _features(
    origin: str = "AAA",
    dest: str = "BBB",
    pop_origin: int = 10_000_000,
    pop_dest: int = 20_000_000,
    distance_km: float = 1000.0,
    route_count: int = 10,
    airline_count: int = 3,
) -> PairFeatures:
    return PairFeatures(origin, dest, pop_origin, pop_dest, distance_km, route_count, airline_count)


def _synthetic_observations(n: int = 600, seed: int = 7) -> list[tuple[PairFeatures, float]]:
    rng = np.random.default_rng(seed)
    rows: list[tuple[PairFeatures, float]] = []
    for i in range(n):
        pop_o = int(10 ** rng.uniform(6, 9))
        pop_d = int(10 ** rng.uniform(6, 9))
        distance = float(10 ** rng.uniform(2.5, 4.1))
        routes = int(rng.integers(0, 60))
        airlines = int(rng.integers(0, 12))
        features = PairFeatures(f"O{i:04d}", f"D{i:04d}", pop_o, pop_d, distance, routes, airlines)
        log_value = (
            1.0
            + 0.3 * math.log10(pop_o)
            + 0.2 * math.log10(pop_d)
            - 0.5 * math.log10(distance)
            + 0.8 * math.log10(1 + routes)
            + float(rng.normal(0, 0.1))
        )
        rows.append((features, 10.0**log_value))
    return rows


class TestGreatCircleDistance:
    def test_zero_distance_to_self(self) -> None:
        assert great_circle_km(10.0, 20.0, 10.0, 20.0) == pytest.approx(0.0)

    def test_quarter_circumference_between_pole_and_equator(self) -> None:
        assert great_circle_km(0.0, 0.0, 90.0, 0.0) == pytest.approx(10007.5, rel=1e-3)

    def test_known_city_pair(self) -> None:
        london_to_new_york = great_circle_km(51.4700, -0.4543, 40.6413, -73.7781)
        assert london_to_new_york == pytest.approx(5539, rel=0.01)

    def test_symmetric(self) -> None:
        a = great_circle_km(12.0, 34.0, -56.0, 78.0)
        b = great_circle_km(-56.0, 78.0, 12.0, 34.0)
        assert a == pytest.approx(b)

    def test_antipodal_is_half_circumference(self) -> None:
        assert great_circle_km(0.0, 0.0, 0.0, 180.0) == pytest.approx(20015, rel=1e-3)


class TestPairFeatures:
    def test_vector_order_matches_feature_names(self) -> None:
        assert len(_features().to_vector()) == len(FEATURE_NAMES)

    def test_zero_route_count_is_representable(self) -> None:
        vector = _features(route_count=0, airline_count=0).to_vector()
        assert vector[3] == 0.0
        assert vector[4] == 0.0

    def test_zero_population_does_not_produce_minus_infinity(self) -> None:
        vector = _features(pop_origin=0).to_vector()
        assert all(math.isfinite(v) for v in vector)


class TestFit:
    def test_recovers_known_coefficients_from_synthetic_data(self) -> None:
        fit = fit_gravity_model(
            _synthetic_observations(), training_source="synthetic", training_period="test"
        )
        assert fit.coefficients["log10_pop_origin"] == pytest.approx(0.3, abs=0.05)
        assert fit.coefficients["log10_pop_dest"] == pytest.approx(0.2, abs=0.05)
        assert fit.coefficients["log10_distance_km"] == pytest.approx(-0.5, abs=0.05)
        assert fit.coefficients["log10_route_count"] == pytest.approx(0.8, abs=0.05)
        assert fit.test_metrics.r2_log > 0.9

    def test_split_sizes_add_up(self) -> None:
        observations = _synthetic_observations(500)
        fit = fit_gravity_model(observations, training_source="s", training_period="t")
        assert fit.n_train + fit.n_test == len(observations)
        assert fit.n_test == pytest.approx(100, abs=1)

    def test_split_is_deterministic_for_a_given_seed(self) -> None:
        observations = _synthetic_observations()
        a = fit_gravity_model(observations, training_source="s", training_period="t", seed=42)
        b = fit_gravity_model(observations, training_source="s", training_period="t", seed=42)
        assert a.coefficients == b.coefficients
        assert a.residual_sigma_log10 == b.residual_sigma_log10

    def test_different_seeds_give_different_splits(self) -> None:
        observations = _synthetic_observations()
        a = fit_gravity_model(observations, training_source="s", training_period="t", seed=1)
        b = fit_gravity_model(observations, training_source="s", training_period="t", seed=2)
        assert a.coefficients != b.coefficients

    def test_held_out_metrics_are_computed_on_unseen_rows(self) -> None:
        """A near-perfect train score with a weak test score must be visible."""
        fit = fit_gravity_model(_synthetic_observations(), training_source="s", training_period="t")
        assert fit.test_metrics.r2_log <= fit.train_metrics.r2_log + 0.15

    def test_non_positive_targets_are_excluded_not_logged(self) -> None:
        observations = _synthetic_observations()
        observations.append((_features(), 0.0))
        observations.append((_features(), -5.0))
        fit = fit_gravity_model(observations, training_source="s", training_period="t")
        assert fit.excluded_rows == 2

    def test_rows_with_missing_population_are_excluded(self) -> None:
        observations = _synthetic_observations()
        observations.append((_features(pop_origin=0), 100.0))
        fit = fit_gravity_model(observations, training_source="s", training_period="t")
        assert fit.excluded_rows == 1

    def test_too_few_rows_raises_rather_than_fitting(self) -> None:
        with pytest.raises(DataUnavailableError, match="at least"):
            fit_gravity_model(
                _synthetic_observations(MIN_TRAINING_ROWS - 1),
                training_source="s",
                training_period="t",
            )

    def test_stratified_metrics_are_recorded(self) -> None:
        fit = fit_gravity_model(_synthetic_observations(), training_source="s", training_period="t")
        strata = fit.notes["test_metrics_by_stratum"]
        assert isinstance(strata, dict)
        assert "with_direct_routes" in strata


class TestPrediction:
    @pytest.fixture
    def fit(self) -> GravityFit:
        return fit_gravity_model(
            _synthetic_observations(), training_source="s", training_period="t"
        )

    def test_prediction_is_positive_and_finite(self, fit: GravityFit) -> None:
        value = fit.predict_passengers_per_day(_features())
        assert value > 0
        assert math.isfinite(value)

    def test_more_routes_predicts_more_passengers(self, fit: GravityFit) -> None:
        low = fit.predict_passengers_per_day(_features(route_count=1))
        high = fit.predict_passengers_per_day(_features(route_count=50))
        assert high > low

    def test_greater_distance_predicts_fewer_passengers(self, fit: GravityFit) -> None:
        near = fit.predict_passengers_per_day(_features(distance_km=500))
        far = fit.predict_passengers_per_day(_features(distance_km=10000))
        assert far < near

    def test_larger_populations_predict_more_passengers(self, fit: GravityFit) -> None:
        small = fit.predict_passengers_per_day(_features(pop_origin=10**6, pop_dest=10**6))
        large = fit.predict_passengers_per_day(_features(pop_origin=10**9, pop_dest=10**9))
        assert large > small

    def test_uncertainty_factor_is_at_least_one_and_capped(self, fit: GravityFit) -> None:
        assert 1.0 <= fit.uncertainty_factor <= MAX_UNCERTAINTY_FACTOR


class TestFeatureTable:
    def test_pairs_without_population_are_dropped(self) -> None:
        table = build_feature_table(
            [("AAA", "BBB")], {"AAA": 1000}, {"AAA": (0.0, 0.0), "BBB": (1.0, 1.0)}, {}
        )
        assert table == {}

    def test_pairs_without_centroid_are_dropped(self) -> None:
        table = build_feature_table(
            [("AAA", "BBB")], {"AAA": 1000, "BBB": 2000}, {"AAA": (0.0, 0.0)}, {}
        )
        assert table == {}

    def test_self_pairs_are_dropped(self) -> None:
        table = build_feature_table([("AAA", "AAA")], {"AAA": 1000}, {"AAA": (0.0, 0.0)}, {})
        assert table == {}

    def test_missing_topology_becomes_zero_routes_not_an_error(self) -> None:
        table = build_feature_table(
            [("AAA", "BBB")],
            {"AAA": 1000, "BBB": 2000},
            {"AAA": (0.0, 0.0), "BBB": (10.0, 10.0)},
            {},
        )
        assert table[("AAA", "BBB")].route_count == 0

    def test_distance_is_computed_from_centroids(self) -> None:
        table = build_feature_table(
            [("AAA", "BBB")],
            {"AAA": 1000, "BBB": 2000},
            {"AAA": (0.0, 0.0), "BBB": (0.0, 90.0)},
            {},
        )
        assert table[("AAA", "BBB")].distance_km == pytest.approx(10007.5, rel=1e-3)
