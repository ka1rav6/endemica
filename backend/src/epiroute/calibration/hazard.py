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
    return float(-np.sum(labels * np.log(predicted) + (1.0 - labels) * np.log(1.0 - predicted)))


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


# ---------------------------------------------------------------------------
# The general fit
#
# The three-parameter grid search above is kept because the gates and the tests
# are written against it, but a grid cannot be widened: a fourth feature at the
# same resolution is 29 x 9 x 5 x 5 evaluations and a fifth is hopeless, and the
# spacing of the grid becomes the precision of the answer.
#
# This is projected gradient ascent on the penalised log-likelihood with an
# Armijo backtracking line search. The objective is smooth, the step is
# accepted only when it improves, the starting point is fixed, and nothing is
# random, so two machines fitting the same panel get the same coefficients to
# the last bit. scipy would do the same job, but it is not a dependency of this
# project and one optimiser for one concave problem is not worth adding it for.
# ---------------------------------------------------------------------------

# Ridge on the slopes, never on the intercept. With two outbreaks the slopes
# are the parameters a fold can swing wildly, and the intercept is the one
# that has to absorb the base rate. The value is small enough not to bias a
# well-identified slope and large enough to stop an unidentified one running
# to the edge of the space.
DEFAULT_RIDGE = 1e-3

_MAX_STEPS = 2000
_TOLERANCE = 1e-9


def cloglog_rate(design: np.ndarray, beta: np.ndarray, horizon_days: float) -> np.ndarray:
    """``horizon * exp(eta)``, clipped so the exponential cannot overflow."""
    eta = np.clip(design @ beta, -40.0, 40.0)
    return horizon_days * np.exp(eta)


def cloglog_probability(design: np.ndarray, beta: np.ndarray, horizon_days: float) -> np.ndarray:
    """Chance of at least one arrival in the horizon, under a Poisson count."""
    return 1.0 - np.exp(-cloglog_rate(design, beta, horizon_days))


def _penalised_log_likelihood(
    design: np.ndarray,
    labels: np.ndarray,
    beta: np.ndarray,
    horizon_days: float,
    ridge: float,
) -> float:
    rate = cloglog_rate(design, beta, horizon_days)
    # log(1 - exp(-rate)) underflows for a tiny rate, where it is log(rate).
    survival = np.exp(-rate)
    event = np.log(np.clip(1.0 - survival, 1e-300, None))
    total = float(np.sum(labels * event - (1.0 - labels) * rate))
    penalty = ridge * float(np.sum(beta[1:] ** 2))
    return total - penalty


def _gradient(
    design: np.ndarray,
    labels: np.ndarray,
    beta: np.ndarray,
    horizon_days: float,
    ridge: float,
) -> np.ndarray:
    rate = cloglog_rate(design, beta, horizon_days)
    survival = np.exp(-rate)
    # d/d-eta of the log-likelihood for one row. The ratio below tends to 1 as
    # the rate goes to zero, which is where almost every row of this panel sits.
    ratio = np.where(
        rate > 1e-8,
        survival / np.clip(1.0 - survival, 1e-300, None),
        1.0 / np.clip(rate, 1e-300, None),
    )
    d_eta = rate * (labels * ratio - (1.0 - labels))
    gradient = design.T @ d_eta
    gradient[1:] -= 2.0 * ridge * beta[1:]
    return gradient


def fit_cloglog(
    design: np.ndarray,
    labels: np.ndarray,
    *,
    horizon_days: float,
    monotone_columns: tuple[int, ...] = (),
    ridge: float = DEFAULT_RIDGE,
) -> np.ndarray:
    """Coefficients for ``design``, intercept first. Deterministic.

    ``monotone_columns`` are projected back to zero whenever a step would make
    them negative, which is a constraint on the answer rather than a nudge in
    the objective: the fitted value is either zero or a genuine interior
    optimum, never a compromise between the data and a penalty.

    The columns are centred and scaled before fitting. One scalar step along
    the raw gradient cannot suit a matrix whose columns are a column of ones,
    a log population around 7 and a log rate around -20: the well-scaled
    directions converge and the others crawl, and the fit stops with the mean
    probability right and the individual slopes still near their starting
    values. Standardising makes one step size appropriate for every direction.
    Coefficients are returned on the original scale.
    """
    design, mean, scale = _standardise(design)
    beta = np.zeros(design.shape[1], dtype=float)
    # Start the intercept at the rate that reproduces the observed base rate
    # with every slope at zero. A fit that cannot improve on that is visible
    # as a model that learned nothing, rather than one that failed to converge.
    base = float(np.clip(np.mean(labels), 1e-6, 1.0 - 1e-6))
    beta[0] = float(np.log(-np.log(1.0 - base) / horizon_days))
    best = _penalised_log_likelihood(design, labels, beta, horizon_days, ridge)
    step = 1.0 / max(float(len(labels)), 1.0)

    for _ in range(_MAX_STEPS):
        gradient = _gradient(design, labels, beta, horizon_days, ridge)
        norm = float(np.linalg.norm(gradient))
        if not np.isfinite(norm) or norm < _TOLERANCE:
            break
        improved = False
        trial_step = step
        for _ in range(40):
            candidate = beta + trial_step * gradient
            for column in monotone_columns:
                candidate[column] = max(0.0, candidate[column])
            value = _penalised_log_likelihood(design, labels, candidate, horizon_days, ridge)
            if np.isfinite(value) and value > best + 1e-12:
                beta, best = candidate, value
                step = trial_step * 1.5
                improved = True
                break
            trial_step /= 2.0
        if not improved:
            break
    return _unstandardise(beta, mean, scale)


def _standardise(design: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Centre and scale every column but the intercept. A constant column keeps a scale of one."""
    mean = design.mean(axis=0)
    scale = design.std(axis=0)
    mean[0] = 0.0
    scale[0] = 1.0
    scale = np.where(scale > 1e-12, scale, 1.0)
    scaled = design.copy()
    scaled[:, 1:] = (design[:, 1:] - mean[1:]) / scale[1:]
    return scaled, mean, scale


def _unstandardise(beta: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Map coefficients fitted on the scaled matrix back onto the real columns."""
    out = beta / scale
    out[0] = beta[0] - float(np.sum(beta[1:] * mean[1:] / scale[1:]))
    return out
