"""Complementary log-log hazard fitted to historical first reports.

``P = 1 - exp(-exp(b0 + b1 * log(lambda) + g * log10(population)) * horizon)``.

``b1`` is kept at or above zero, so a higher arrival rate cannot lower the
probability. ``b0`` is fitted per outbreak. A live outbreak uses the spread of
those values as its low-to-high band.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class HazardCoefficients:
    b0: float
    b1: float
    g: float


def probability(
    coefficients: HazardCoefficients,
    log_lambda: np.ndarray,
    log_population: np.ndarray,
    horizon_days: float,
) -> np.ndarray:
    eta = coefficients.b0 + coefficients.b1 * log_lambda + coefficients.g * log_population
    rate = np.exp(np.clip(eta, -40.0, 40.0))
    return 1.0 - np.exp(-rate * horizon_days)


def _negative_log_likelihood(
    coefficients: HazardCoefficients,
    log_lambda: np.ndarray,
    log_population: np.ndarray,
    labels: np.ndarray,
    horizon_days: float,
) -> float:
    predicted = np.clip(
        probability(coefficients, log_lambda, log_population, horizon_days), 1e-6, 1.0 - 1e-6
    )
    return float(
        -np.sum(labels * np.log(predicted) + (1.0 - labels) * np.log(1.0 - predicted))
    )


def fit_hazard(
    log_lambda: np.ndarray,
    log_population: np.ndarray,
    labels: np.ndarray,
    *,
    horizon_days: float,
    b1_min: float = 0.0,
) -> HazardCoefficients:
    """Grid search, then a small local refinement. ``b1`` cannot go below ``b1_min``."""
    best = HazardCoefficients(0.0, 1.0, 0.0)
    best_loss = _negative_log_likelihood(best, log_lambda, log_population, labels, horizon_days)
    for b0 in np.linspace(-12.0, 2.0, 29):
        for b1 in np.linspace(b1_min, 2.0, 9):
            for g in np.linspace(-1.0, 1.0, 5):
                candidate = HazardCoefficients(float(b0), float(b1), float(g))
                loss = _negative_log_likelihood(
                    candidate, log_lambda, log_population, labels, horizon_days
                )
                if loss < best_loss:
                    best, best_loss = candidate, loss

    step = 0.25
    for _ in range(8):
        improved = False
        for delta_b0 in (-step, step):
            for delta_b1 in (-step, 0.0, step):
                for delta_g in (-step, 0.0, step):
                    candidate = HazardCoefficients(
                        best.b0 + delta_b0,
                        max(b1_min, best.b1 + delta_b1),
                        best.g + delta_g,
                    )
                    loss = _negative_log_likelihood(
                        candidate, log_lambda, log_population, labels, horizon_days
                    )
                    if loss < best_loss - 1e-9:
                        best, best_loss = candidate, loss
                        improved = True
        if not improved:
            step /= 2.0
    return best


def fit_b0_by_outbreak(
    outbreaks: np.ndarray,
    log_lambda: np.ndarray,
    log_population: np.ndarray,
    labels: np.ndarray,
    *,
    horizon_days: float,
) -> tuple[dict[str, float], float, float]:
    """Shared slope, one intercept per outbreak.

    The shared ``b1`` and ``g`` come from the pooled fit. Each outbreak then
    gets the intercept that fits it best with those slopes held fixed.
    """
    pooled = fit_hazard(log_lambda, log_population, labels, horizon_days=horizon_days)
    intercepts: dict[str, float] = {}
    for outbreak in sorted(set(outbreaks.tolist())):
        mask = outbreaks == outbreak
        best_b0 = pooled.b0
        best_loss = float("inf")
        for b0 in np.linspace(pooled.b0 - 4.0, pooled.b0 + 4.0, 33):
            candidate = HazardCoefficients(float(b0), pooled.b1, pooled.g)
            loss = _negative_log_likelihood(
                candidate,
                log_lambda[mask],
                log_population[mask],
                labels[mask],
                horizon_days,
            )
            if loss < best_loss:
                best_b0, best_loss = float(b0), loss
        intercepts[str(outbreak)] = best_b0
    return intercepts, pooled.b1, pooled.g
