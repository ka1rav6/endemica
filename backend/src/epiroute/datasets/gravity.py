from __future__ import annotations

import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from epiroute.core.errors import DataUnavailableError

logger = logging.getLogger(__name__)

FEATURE_NAMES: tuple[str, ...] = (
    "log10_pop_origin",
    "log10_pop_dest",
    "log10_distance_km",
    "log10_route_count",
    "log10_airline_count",
)

SPECIFICATION = (
    "log10(passengers_per_day) = b0 + b1*log10(pop_origin) + b2*log10(pop_dest) "
    "+ b3*log10(distance_km) + b4*log10(1 + direct_routes) "
    "+ b5*log10(1 + airlines)"
)

MIN_TRAINING_ROWS = 100
DEFAULT_TEST_FRACTION = 0.2
DEFAULT_SEED = 20261024

# Cap on the multiplicative band so a poorly-fitted route cannot widen the
# risk band to meaninglessness.
MAX_UNCERTAINTY_FACTOR = 100.0

# Pairs with no scheduled direct route in OpenFlights are extrapolation rather
# than interpolation: the dominant feature is zero and the topology data is a
# decade old, so a route that exists today may be absent from it. The residual
# spread is widened accordingly.
NO_ROUTE_EXTRAPOLATION_PENALTY = 1.5


@dataclass(frozen=True, slots=True)
class PairFeatures:
    origin_iso3: str
    dest_iso3: str
    pop_origin: int
    pop_dest: int
    distance_km: float
    route_count: int
    airline_count: int

    def to_vector(self) -> list[float]:
        return [
            math.log10(max(self.pop_origin, 1)),
            math.log10(max(self.pop_dest, 1)),
            math.log10(max(self.distance_km, 1.0)),
            math.log10(1.0 + self.route_count),
            math.log10(1.0 + self.airline_count),
        ]


@dataclass(frozen=True, slots=True)
class GravityMetrics:
    r2_log: float
    mae_log10: float
    rmse_log10: float
    median_ratio_error: float
    within_factor_2: float
    within_factor_5: float
    within_factor_10: float

    def as_dict(self) -> dict[str, float]:
        return {
            "r2_log": self.r2_log,
            "mae_log10": self.mae_log10,
            "rmse_log10": self.rmse_log10,
            "median_ratio_error": self.median_ratio_error,
            "within_factor_2": self.within_factor_2,
            "within_factor_5": self.within_factor_5,
            "within_factor_10": self.within_factor_10,
        }


@dataclass(frozen=True, slots=True)
class GravityFit:
    intercept: float
    coefficients: dict[str, float]
    n_train: int
    n_test: int
    random_seed: int
    residual_sigma_log10: float
    test_metrics: GravityMetrics
    train_metrics: GravityMetrics
    training_source: str
    training_period: str
    feature_names: tuple[str, ...] = FEATURE_NAMES
    specification: str = SPECIFICATION
    excluded_rows: int = 0
    notes: dict[str, object] = field(default_factory=dict)

    def predict_log10(self, features: PairFeatures) -> float:
        vector = features.to_vector()
        total = self.intercept
        for name, value in zip(self.feature_names, vector, strict=True):
            total += self.coefficients[name] * value
        return total

    def predict_passengers_per_day(self, features: PairFeatures) -> float:
        """Return the mean flow, not the median of the log-linear fit.

        The regression predicts log10(passengers). Exponentiating that is the
        median. For a log10-normal residual with standard deviation sigma,
        the mean is larger by ``10 ** (0.5 * sigma^2 * ln(10))``.
        """
        median = 10.0 ** self.predict_log10(features)
        sigma = self.residual_sigma_log10
        correction = 10.0 ** (0.5 * sigma * sigma * math.log(10.0))
        return float(median * correction)

    @property
    def uncertainty_factor(self) -> float:
        return self.uncertainty_factor_for(has_direct_routes=True)

    def uncertainty_factor_for(self, *, has_direct_routes: bool) -> float:
        sigma = self.residual_sigma_log10
        strata = self.notes.get("test_metrics_by_stratum")
        label = "with_direct_routes" if has_direct_routes else "without_direct_routes"
        if isinstance(strata, dict):
            stratum = strata.get(label)
            if isinstance(stratum, dict):
                rmse = stratum.get("rmse_log10")
                if isinstance(rmse, (int, float)) and rmse > 0:
                    sigma = float(rmse)
        if not has_direct_routes:
            sigma *= NO_ROUTE_EXTRAPOLATION_PENALTY
        return float(min(10.0 ** (2.0 * sigma), MAX_UNCERTAINTY_FACTOR))


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> GravityMetrics:
    residual = predicted - actual
    ss_res = float(np.sum(residual**2))
    ss_tot = float(np.sum((actual - actual.mean()) ** 2))
    ratio_error = np.abs(residual)
    return GravityMetrics(
        r2_log=1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0,
        mae_log10=float(np.mean(np.abs(residual))),
        rmse_log10=float(np.sqrt(np.mean(residual**2))),
        median_ratio_error=float(10.0 ** np.median(ratio_error)),
        within_factor_2=float(np.mean(ratio_error <= math.log10(2.0))),
        within_factor_5=float(np.mean(ratio_error <= math.log10(5.0))),
        within_factor_10=float(np.mean(ratio_error <= math.log10(10.0))),
    )


def fit_gravity_model(
    observations: Sequence[tuple[PairFeatures, float]],
    *,
    training_source: str,
    training_period: str,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    seed: int = DEFAULT_SEED,
) -> GravityFit:
    usable: list[tuple[PairFeatures, float]] = []
    excluded = 0
    for features, passengers_per_day in observations:
        if passengers_per_day <= 0 or not math.isfinite(passengers_per_day):
            excluded += 1
            continue
        if features.pop_origin <= 0 or features.pop_dest <= 0:
            excluded += 1
            continue
        if not math.isfinite(features.distance_km) or features.distance_km <= 0:
            excluded += 1
            continue
        usable.append((features, passengers_per_day))

    if len(usable) < MIN_TRAINING_ROWS:
        msg = (
            f"only {len(usable)} usable observed flows; at least {MIN_TRAINING_ROWS} "
            f"are required to fit the gravity model"
        )
        raise DataUnavailableError("observed_passenger_flows", msg)

    design = np.array([[1.0, *f.to_vector()] for f, _ in usable], dtype=float)
    target = np.array([math.log10(v) for _, v in usable], dtype=float)

    # Hold out unordered country pairs, so A→B and B→A cannot sit on opposite
    # sides of the split and leak the same route into the test score.
    pair_groups: dict[tuple[str, str], list[int]] = {}
    for index, (features, _) in enumerate(usable):
        first, second = sorted((features.origin_iso3, features.dest_iso3))
        pair = (first, second)
        pair_groups.setdefault(pair, []).append(index)
    rng = np.random.default_rng(seed)
    group_order = rng.permutation(len(pair_groups))
    n_test_groups = max(1, round(len(pair_groups) * test_fraction))
    test_pairs = {list(pair_groups)[int(i)] for i in group_order[:n_test_groups]}
    test_index = np.array(
        [i for pair, rows in pair_groups.items() if pair in test_pairs for i in rows]
    )
    train_index = np.array(
        [i for pair, rows in pair_groups.items() if pair not in test_pairs for i in rows]
    )
    n_test = len(test_index)

    solution, *_ = np.linalg.lstsq(design[train_index], target[train_index], rcond=None)

    train_pred = design[train_index] @ solution
    test_pred = design[test_index] @ solution
    train_metrics = _metrics(target[train_index], train_pred)
    test_metrics = _metrics(target[test_index], test_pred)

    test_residual = target[test_index] - test_pred
    residual_sigma = float(np.std(test_residual, ddof=1)) if n_test > 1 else 0.0

    has_route = np.array([f.route_count > 0 for f, _ in usable], dtype=bool)
    strata: dict[str, dict[str, float]] = {}
    for label, mask in (
        ("with_direct_routes", has_route[test_index]),
        ("without_direct_routes", ~has_route[test_index]),
    ):
        if int(mask.sum()) > 1:
            strata[label] = {
                "n": float(int(mask.sum())),
                **_metrics(target[test_index][mask], test_pred[mask]).as_dict(),
            }

    fit = GravityFit(
        intercept=float(solution[0]),
        coefficients=dict(zip(FEATURE_NAMES, (float(c) for c in solution[1:]), strict=True)),
        n_train=len(train_index),
        n_test=n_test,
        random_seed=seed,
        residual_sigma_log10=residual_sigma,
        test_metrics=test_metrics,
        train_metrics=train_metrics,
        training_source=training_source,
        training_period=training_period,
        excluded_rows=excluded,
        notes={
            "test_fraction": test_fraction,
            "excluded_rows": excluded,
            "train_metrics": train_metrics.as_dict(),
            "test_metrics_by_stratum": strata,
            "training_rows_with_direct_routes": float(has_route[train_index].mean()),
        },
    )
    logger.info(
        "gravity model fitted",
        extra={
            "n_train": fit.n_train,
            "n_test": fit.n_test,
            "test_r2_log": round(test_metrics.r2_log, 4),
            "test_mae_log10": round(test_metrics.mae_log10, 4),
            "residual_sigma_log10": round(residual_sigma, 4),
        },
    )
    return fit


def build_feature_table(
    pairs: Sequence[tuple[str, str]],
    populations: Mapping[str, int],
    centroids: Mapping[str, tuple[float, float]],
    topology: Mapping[tuple[str, str], tuple[int, int]],
) -> dict[tuple[str, str], PairFeatures]:
    from epiroute.datasets.geo import great_circle_km

    table: dict[tuple[str, str], PairFeatures] = {}
    for origin, dest in pairs:
        if origin == dest:
            continue
        pop_origin = populations.get(origin)
        pop_dest = populations.get(dest)
        origin_centroid = centroids.get(origin)
        dest_centroid = centroids.get(dest)
        if not (pop_origin and pop_dest and origin_centroid and dest_centroid):
            continue
        routes, airlines = topology.get((origin, dest), (0, 0))
        table[(origin, dest)] = PairFeatures(
            origin_iso3=origin,
            dest_iso3=dest,
            pop_origin=pop_origin,
            pop_dest=pop_dest,
            distance_km=great_circle_km(*origin_centroid, *dest_centroid),
            route_count=routes,
            airline_count=airlines,
        )
    return table
