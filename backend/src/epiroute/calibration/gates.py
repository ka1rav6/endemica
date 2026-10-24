"""Numeric gates, split by what passing them entitles the app to claim.

One boolean was the wrong shape for the answer. On this panel the model ranks
countries well on both held-out outbreaks - AUC 0.78 and 0.77, both calibration
slopes near one - while the absolute level of its probabilities does not
transfer: the two outbreaks differ threefold in base rate, so an intercept
fitted on one sits about one logit away from the other. A single gate forced a
choice between claiming a calibrated probability the evidence does not support
and serving nothing at all, and the app chose nothing at all. It fell back to
``1 - exp(-lambda * 28)`` for every disease, which on the same folds scores AUC
0.54 and 0.62. The fitted model was never used.

So there are two sets. The ranking gates say the order may be served. The
calibration gates say the number may be called calibrated. The rest are
reported and gate nothing, because a measurement that no decision depends on
should not be able to block a release.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from epiroute.calibration.metrics import (
    brier_skill,
    calibration_line,
    roc_auc,
    spearman,
    top_k_precision,
    top_k_recall,
)

# Passing every gate in this set means the model's ordering of countries beat
# both the arithmetic it replaces and chance, on an outbreak it had not seen.
RANKING_GATES: tuple[str, ...] = (
    "brier_skill_vs_uncalibrated",
    "roc_auc",
    "monotone_in_lambda",
)

# And these mean the probability itself may be presented as a probability.
CALIBRATION_GATES: tuple[str, ...] = ("calibration_slope", "calibration_intercept")


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    passed: bool
    value: float | None
    detail: str


def evaluate_gates(
    *,
    labels: np.ndarray,
    predicted: np.ndarray,
    uncalibrated: np.ndarray,
    best_simple: np.ndarray,
    arrival_day: np.ndarray | None = None,
    monotone: bool = True,
) -> list[GateResult]:
    """Score one held-out outbreak. ``arrival_day`` is days from the forecast, or NaN."""
    skill_vs_model = brier_skill(labels, predicted, uncalibrated)
    skill_vs_simple = brier_skill(labels, predicted, best_simple)
    auc = roc_auc(labels, predicted)
    slope, intercept = calibration_line(labels, predicted)
    recall = top_k_recall(labels, predicted, 20)
    precision = top_k_precision(labels, predicted, 20)
    results = [
        GateResult(
            "brier_skill_vs_uncalibrated",
            skill_vs_model >= 0.10,
            skill_vs_model,
            "at least 0.10",
        ),
        GateResult(
            "brier_skill_vs_best_simple",
            skill_vs_simple >= 0.03,
            skill_vs_simple,
            "at least 0.03",
        ),
        GateResult("roc_auc", auc >= 0.70, auc, "at least 0.70 on this outbreak"),
        GateResult(
            "calibration_slope",
            bool(np.isfinite(slope) and 0.5 <= slope <= 1.5),
            slope,
            "0.5 to 1.5 on one outbreak",
        ),
        GateResult(
            "calibration_intercept",
            bool(np.isfinite(intercept) and abs(intercept) <= 0.5),
            intercept,
            "absolute value at most 0.5 on one outbreak",
        ),
        GateResult(
            "top_20_precision",
            bool(np.isfinite(precision) and precision >= 0.5),
            precision,
            "at least half of the twenty highest-ranked countries did report",
        ),
        GateResult(
            "top_20_recall",
            True,
            recall,
            "reported, not gated: twenty rows cannot recover a fold with hundreds of positives",
        ),
    ]
    if arrival_day is not None:
        known = np.isfinite(arrival_day) & (labels == 1)
        enough = int(known.sum()) >= 3
        rank = spearman(-predicted[known], arrival_day[known]) if enough else float("nan")
        results.append(
            GateResult(
                "arrival_order_spearman",
                bool(np.isfinite(rank) and rank >= 0.5),
                rank,
                "at least 0.5",
            )
        )
    results.append(
        GateResult(
            "monotone_in_lambda",
            monotone,
            1.0 if monotone else 0.0,
            "b1 is at least 0, so probability does not fall as lambda rises",
        )
    )
    return results


def all_passed(results: list[GateResult]) -> bool:
    return all(result.passed for result in results)


def passed_set(results: list[GateResult], names: tuple[str, ...]) -> bool:
    """Whether every named gate is present and passing."""
    found = {result.name: result.passed for result in results}
    return all(found.get(name, False) for name in names)


def status_from_gates(folds: list[list[GateResult]]) -> str:
    """The strongest claim every held-out fold supports.

    ``calibrated``
        The ordering and the level both held up. The probability is served as
        a probability.
    ``ranking_validated``
        The ordering held up and the level did not. The app serves the model's
        ordering and says the number is indicative.
    ``not_validated``
        Neither. The app falls back to the uncalibrated arithmetic and says so.
    """
    if len(folds) < 2:
        return "not_validated"
    if not all(passed_set(fold, RANKING_GATES) for fold in folds):
        return "not_validated"
    if all(passed_set(fold, CALIBRATION_GATES) for fold in folds):
        return "calibrated"
    return "ranking_validated"
