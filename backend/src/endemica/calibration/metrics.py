"""Scores for a binary "first report within the horizon" prediction."""

from __future__ import annotations

import numpy as np


def brier(labels: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean((predicted - labels) ** 2))


def brier_skill(labels: np.ndarray, predicted: np.ndarray, reference: np.ndarray) -> float:
    reference_score = brier(labels, reference)
    if reference_score <= 0:
        return 0.0
    return 1.0 - brier(labels, predicted) / reference_score


def roc_auc(labels: np.ndarray, predicted: np.ndarray) -> float:
    positives = float(np.sum(labels == 1))
    negatives = float(len(labels) - positives)
    if positives == 0 or negatives == 0:
        return float("nan")
    order = np.argsort(predicted, kind="mergesort")
    ranks = np.empty(len(predicted), dtype=float)
    ranks[order] = np.arange(1, len(predicted) + 1)
    sum_positive_ranks = float(np.sum(ranks[labels == 1]))
    return (sum_positive_ranks - positives * (positives + 1) / 2.0) / (positives * negatives)


def calibration_line(labels: np.ndarray, predicted: np.ndarray) -> tuple[float, float]:
    """Slope and intercept of logit(outcome rate) against logit(prediction).

    Ten quantile bins. The intercept is the fitted line at logit 0, which is a
    predicted probability of one half.
    """
    clipped = np.clip(predicted, 1e-4, 1.0 - 1e-4)
    order = np.argsort(clipped)
    bins = np.array_split(order, min(10, len(order)))
    xs: list[float] = []
    ys: list[float] = []
    for indexes in bins:
        if len(indexes) == 0:
            continue
        rate = float(np.mean(labels[indexes]))
        mean_prediction = float(np.mean(clipped[indexes]))
        if rate <= 0 or rate >= 1:
            continue
        xs.append(float(np.log(mean_prediction / (1.0 - mean_prediction))))
        ys.append(float(np.log(rate / (1.0 - rate))))
    if len(xs) < 2:
        return float("nan"), float("nan")
    x = np.array(xs)
    y = np.array(ys)
    # Centre before fitting. The logits span tens of units here, so the raw
    # Vandermonde matrix is ill-conditioned and numpy says so on every call;
    # centring removes the conditioning problem rather than the warning, and
    # the intercept is then put back where it belongs.
    centre = float(np.mean(x))
    shifted_x = x - centre
    # A constant forecast puts every bin at the same predicted logit, so there
    # is no line to fit through them. That is not a failure of the model, it is
    # a model with no ranking in it, and the right answer is no slope.
    if float(np.ptp(shifted_x)) < 1e-9:
        return float("nan"), float("nan")
    try:
        slope, shifted = np.polyfit(shifted_x, y, 1)
    except np.linalg.LinAlgError:
        return float("nan"), float("nan")
    return float(slope), float(shifted - slope * centre)


def spearman(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 2:
        return float("nan")
    left_rank = np.argsort(np.argsort(left)).astype(float)
    right_rank = np.argsort(np.argsort(right)).astype(float)
    left_rank -= left_rank.mean()
    right_rank -= right_rank.mean()
    denominator = float(np.sqrt(np.sum(left_rank**2) * np.sum(right_rank**2)))
    if denominator == 0:
        return float("nan")
    return float(np.sum(left_rank * right_rank) / denominator)


def top_k_recall(labels: np.ndarray, predicted: np.ndarray, k: int = 20) -> float:
    positives = int(np.sum(labels == 1))
    if positives == 0:
        return float("nan")
    chosen = np.argsort(predicted)[::-1][:k]
    return float(np.sum(labels[chosen] == 1) / positives)


def top_k_precision(labels: np.ndarray, predicted: np.ndarray, k: int = 20) -> float:
    """Share of the ``k`` highest-ranked rows that did report within the horizon.

    ``top_k_recall`` was being gated at 0.5, which no model could ever reach:
    with 642 positives in a fold, twenty rows can recover at most 3% of them,
    so the gate failed on arithmetic rather than on performance. Precision is
    the question that was meant - of the countries we would have warned about,
    how many were right - and it is attainable.
    """
    if len(predicted) == 0:
        return float("nan")
    size = min(k, len(predicted))
    chosen = np.argsort(predicted)[::-1][:size]
    return float(np.sum(labels[chosen] == 1) / size)
