"""Numeric gates a model must pass before the app calls it calibrated."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from epiroute.calibration.metrics import (
    brier_skill,
    calibration_line,
    roc_auc,
    spearman,
    top_k_recall,
)


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
            "top_20_recall",
            bool(np.isfinite(recall) and recall >= 0.5),
            recall,
            "at least 0.5",
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
