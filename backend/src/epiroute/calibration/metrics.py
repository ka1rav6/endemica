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
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope), float(intercept)


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
