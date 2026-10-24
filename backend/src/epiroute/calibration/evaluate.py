"""Scoring the prediction model against splits it cannot see and baselines it must beat.

Three questions, each with its own split, because a single number cannot answer
them:

Can it generalise to a pathogen it has never seen?
    Leave one outbreak out. Two folds, which is as many as two outbreaks allow.
    This is the split that matters for serving, since every disease the app
    shows other than COVID-19 and mpox is in exactly that position.

Can it generalise forward in time inside an outbreak?
    Forward chaining: fit on the first ``k`` weeks, score the two weeks after
    them, for several ``k``. Ten folds rather than two, so the spread of the
    scores is a measurable thing rather than a guess. This is also the only
    split that answers the question the app actually asks - what happens next
    week - and the one a stale model degrades on first.

Is it learning anything, or reading a leak?
    Refit on permuted labels and score on the untouched test fold. A model with
    no leak scores about 0.5 there. Anything well above that means a feature is
    carrying the answer, which is the failure mode that makes a backtest look
    excellent and a live forecast look random.

Every fitted model is also set against four baselines it has to beat. The
honest comparison is not "is the model good" but "is it better than the
arithmetic it replaces", and the arithmetic here - one minus the exponential of
the arrival rate - is already a defensible forecast.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from epiroute.calibration.features import (
    FEATURE_NAMES,
    HORIZON_DAYS,
    MONOTONE_FEATURES,
    design_from_panel,
)
from epiroute.calibration.hazard import cloglog_probability, fit_cloglog
from epiroute.calibration.metrics import (
    brier,
    brier_skill,
    calibration_line,
    roc_auc,
    spearman,
    top_k_precision,
    top_k_recall,
)

# Two test weeks per fold. One week gives too few positives for a stable AUC
# and four lets the fold straddle a change in the epidemic's phase.
FORWARD_TEST_WEEKS = 2
FORWARD_MIN_TRAIN_WEEKS = 4

# A permuted-label refit should score no better than a coin. The ceiling is
# above 0.5 to allow for the sampling noise of a few hundred rows, not to let a
# leak through.
PERMUTATION_AUC_CEILING = 0.60
PERMUTATION_ROUNDS = 5


@dataclass(frozen=True, slots=True)
class Scores:
    rows: int
    positives: int
    brier: float
    roc_auc: float
    calibration_slope: float
    calibration_intercept: float
    top_20_recall: float
    top_20_precision: float
    arrival_order_spearman: float
    mean_predicted: float
    observed_rate: float


@dataclass(frozen=True, slots=True)
class Fold:
    split: str
    name: str
    test: Scores
    train: Scores | None = None
    skill_vs_uncalibrated: float = float("nan")
    skill_vs_best_simple: float = float("nan")

    @property
    def overfit_gap(self) -> float:
        """Test Brier minus train Brier. A model that memorised its fold shows here."""
        if self.train is None:
            return float("nan")
        return self.test.brier - self.train.brier


@dataclass(frozen=True, slots=True)
class ModelEvaluation:
    model: str
    description: str
    parameters: int
    folds: list[Fold] = field(default_factory=list)
    permutation_auc: float = float("nan")
    coefficients: dict[str, float] = field(default_factory=dict)

    def mean(self, metric: Callable[[Fold], float]) -> float:
        values = [metric(fold) for fold in self.folds]
        finite = [value for value in values if np.isfinite(value)]
        return float(np.mean(finite)) if finite else float("nan")


def score(
    labels: np.ndarray, predicted: np.ndarray, arrival_day: np.ndarray | None = None
) -> Scores:
    slope, intercept = calibration_line(labels, predicted)
    rank = float("nan")
    if arrival_day is not None:
        known = np.isfinite(arrival_day) & (labels == 1)
        if int(known.sum()) >= 3:
            rank = spearman(-predicted[known], arrival_day[known])
    return Scores(
        rows=len(labels),
        positives=int(labels.sum()),
        brier=brier(labels, predicted),
        roc_auc=roc_auc(labels, predicted),
        calibration_slope=slope,
        calibration_intercept=intercept,
        top_20_recall=top_k_recall(labels, predicted, 20),
        top_20_precision=top_k_precision(labels, predicted, 20),
        arrival_order_spearman=rank,
        mean_predicted=float(np.mean(predicted)),
        observed_rate=float(np.mean(labels)),
    )


# ---------------------------------------------------------------------------
# Baselines
#
# Each is a forecast somebody could reasonably make without fitting anything.
# A model that cannot beat all four is not earning its place in the app.
# ---------------------------------------------------------------------------


def uncalibrated(frame: pd.DataFrame, horizon_days: float = HORIZON_DAYS) -> np.ndarray:
    """The arithmetic the app falls back to: a Poisson first arrival at rate lambda."""
    rate = np.clip(frame["lambda"].to_numpy(dtype=float), 0.0, None)
    return 1.0 - np.exp(-rate * horizon_days)


def inbound_only(frame: pd.DataFrame) -> np.ndarray:
    """Passenger volume alone, with no case data. The strongest model-free ranking."""
    inbound = frame["inbound_passengers"].to_numpy(dtype=float)
    return np.clip(1.0 - np.exp(-inbound / 1.0e5), 0.0, 1.0)


def population_only(frame: pd.DataFrame) -> np.ndarray:
    """Country size alone. Here to show how much of the signal is just size."""
    size = frame["log_population"].to_numpy(dtype=float)
    span = float(np.ptp(size)) or 1.0
    return (size - float(size.min())) / span


def base_rate(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """The training fold's event rate for every row. Perfectly calibrated, no ranking."""
    return np.full(len(test), float(train["label"].mean()))


BASELINES: dict[str, str] = {
    "uncalibrated_poisson": (
        "1 - exp(-lambda * 28), the formula the app serves when nothing is fitted"
    ),
    "inbound_passengers_only": "passenger volume from affected origins, ignoring case counts",
    "population_only": "destination population, ignoring travel and cases",
    "train_base_rate": "the training fold's event rate, the same number for every country",
}


def baseline_predictions(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        "uncalibrated_poisson": uncalibrated(test),
        "inbound_passengers_only": inbound_only(test),
        "population_only": population_only(test),
        "train_base_rate": base_rate(train, test),
    }


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------


def leave_one_outbreak_out(panel: pd.DataFrame) -> list[tuple[str, pd.DataFrame, pd.DataFrame]]:
    splits: list[tuple[str, pd.DataFrame, pd.DataFrame]] = []
    for held_out in sorted(panel["outbreak"].unique()):
        train = panel[panel["outbreak"] != held_out]
        test = panel[panel["outbreak"] == held_out]
        if train.empty or test.empty or train["label"].sum() == 0:
            continue
        splits.append((str(held_out), train, test))
    return splits


def forward_chaining(panel: pd.DataFrame) -> list[tuple[str, pd.DataFrame, pd.DataFrame]]:
    """Fit on weeks up to ``k``, score the next two, within one outbreak at a time."""
    splits: list[tuple[str, pd.DataFrame, pd.DataFrame]] = []
    for outbreak in sorted(panel["outbreak"].unique()):
        subset = panel[panel["outbreak"] == outbreak]
        weeks = sorted(int(week) for week in subset["week_index"].unique())
        for cutoff in weeks:
            if cutoff < FORWARD_MIN_TRAIN_WEEKS:
                continue
            train = subset[subset["week_index"] <= cutoff]
            test = subset[
                (subset["week_index"] > cutoff)
                & (subset["week_index"] <= cutoff + FORWARD_TEST_WEEKS)
            ]
            if test.empty or train["label"].sum() == 0 or test["label"].sum() == 0:
                continue
            splits.append((f"{outbreak} after week {cutoff}", train, test))
    return splits


# ---------------------------------------------------------------------------
# The fitted models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    description: str
    design: Callable[[pd.DataFrame], np.ndarray]
    monotone: Callable[[], tuple[int, ...]]
    feature_names: tuple[str, ...]


def _column(frame: pd.DataFrame, name: str) -> np.ndarray:
    """One named feature column, for the ablation designs.

    ``log_population`` is not in the served matrix, so an ablation that wants
    it has to read it off the panel directly.
    """
    if name == "log_population":
        return frame["log_population"].to_numpy(dtype=float)
    column: np.ndarray = design_from_panel(frame)[:, FEATURE_NAMES.index(name) + 1]
    return column


def _subset(names: tuple[str, ...]) -> Callable[[pd.DataFrame], np.ndarray]:
    def build(frame: pd.DataFrame) -> np.ndarray:
        return np.column_stack(
            [np.ones(len(frame), dtype=float), *(_column(frame, name) for name in names)]
        )

    return build


def _candidate(name: str, description: str, features: tuple[str, ...]) -> Candidate:
    monotone = tuple(
        index + 1 for index, feature in enumerate(features) if feature in MONOTONE_FEATURES
    )
    return Candidate(
        name=name,
        description=description,
        design=_subset(features),
        monotone=lambda monotone=monotone: monotone,  # type: ignore[misc]
        feature_names=features,
    )


# The served model first, then one ablation per claim it makes. An ablation
# that scores as well as the full model is a feature that should come out, and
# one that scores far worse on one split and far better on another is a feature
# that is pathogen-specific - which is the finding that decided how the model
# is served.
CANDIDATES: tuple[Candidate, ...] = (
    _candidate(
        "hazard",
        "Complementary log-log survival model on all four features. This is the "
        "model the app serves.",
        FEATURE_NAMES,
    ),
    _candidate(
        "hazard_with_population",
        "The served model plus destination population. It forecasts better "
        "inside an outbreak it has already seen and worse on a held-out "
        "pathogen, because how much of a population is exposed depends on how "
        "the pathogen spreads. That is why population is not served.",
        ("log_lambda", "log_inbound", "log_population", "log_affected"),
    ),
    _candidate(
        "hazard_travel_only",
        "Arrival rate and passenger volume only: the mechanism with no context "
        "about the destination or the epidemic's phase.",
        ("log_lambda", "log_inbound"),
    ),
    _candidate(
        "hazard_lambda_only",
        "The arrival rate as the only feature. What the app's stated mechanism "
        "achieves on its own.",
        ("log_lambda",),
    ),
    _candidate(
        "hazard_inbound_only",
        "Passenger volume as the only feature, with no case counts anywhere in "
        "it. If this matches the arrival-rate model, the prevalence estimate is "
        "not contributing.",
        ("log_inbound",),
    ),
)


def evaluate_candidate(
    candidate: Candidate,
    panel: pd.DataFrame,
    *,
    horizon_days: float = HORIZON_DAYS,
) -> ModelEvaluation:
    folds: list[Fold] = []
    for split_name, splits in (
        ("leave_one_outbreak_out", leave_one_outbreak_out(panel)),
        ("forward_chaining", forward_chaining(panel)),
    ):
        for name, train, test in splits:
            beta = fit_cloglog(
                candidate.design(train),
                train["label"].to_numpy(dtype=float),
                horizon_days=horizon_days,
                monotone_columns=candidate.monotone(),
            )
            predicted = cloglog_probability(candidate.design(test), beta, horizon_days)
            on_train = cloglog_probability(candidate.design(train), beta, horizon_days)
            labels = test["label"].to_numpy(dtype=float)
            baselines = baseline_predictions(train, test)
            folds.append(
                Fold(
                    split=split_name,
                    name=name,
                    test=score(labels, predicted, test["arrival_day"].to_numpy(dtype=float)),
                    train=score(train["label"].to_numpy(dtype=float), on_train),
                    skill_vs_uncalibrated=brier_skill(
                        labels, predicted, baselines["uncalibrated_poisson"]
                    ),
                    skill_vs_best_simple=brier_skill(
                        labels, predicted, baselines["inbound_passengers_only"]
                    ),
                )
            )

    final = fit_cloglog(
        candidate.design(panel),
        panel["label"].to_numpy(dtype=float),
        horizon_days=horizon_days,
        monotone_columns=candidate.monotone(),
    )
    return ModelEvaluation(
        model=candidate.name,
        description=candidate.description,
        parameters=1 + len(candidate.feature_names),
        folds=folds,
        permutation_auc=permutation_auc(candidate, panel, horizon_days=horizon_days),
        coefficients=dict(
            zip(
                ("intercept", *candidate.feature_names),
                (float(value) for value in final),
                strict=True,
            )
        ),
    )


def permutation_auc(
    candidate: Candidate, panel: pd.DataFrame, *, horizon_days: float = HORIZON_DAYS
) -> float:
    """Mean held-out AUC after shuffling the training labels. About 0.5 means no leak.

    The test fold's labels are left alone: a model fitted on noise must be
    unable to rank the real outcomes. Shuffling both sides would instead test
    whether the metric is symmetric, which is not in question.

    The monotone constraint is dropped for this fit, and only for this fit. A
    constrained fit on noise can only return a zero slope or a positive one,
    and a positive slope ranks in the right direction, so the constraint on its
    own lifts the permuted score above 0.5 and hides what the test is for.
    """
    splits = leave_one_outbreak_out(panel)
    if not splits:
        return float("nan")
    scores: list[float] = []
    for round_index in range(PERMUTATION_ROUNDS):
        # Seeded per round so the number is the same on every machine.
        generator = np.random.default_rng(round_index)
        for _name, train, test in splits:
            shuffled = generator.permutation(train["label"].to_numpy(dtype=float))
            beta = fit_cloglog(
                candidate.design(train),
                shuffled,
                horizon_days=horizon_days,
            )
            predicted = cloglog_probability(candidate.design(test), beta, horizon_days)
            value = roc_auc(test["label"].to_numpy(dtype=float), predicted)
            if np.isfinite(value):
                scores.append(value)
    return float(np.mean(scores)) if scores else float("nan")


def evaluate_baselines(panel: pd.DataFrame) -> list[ModelEvaluation]:
    """Score each baseline on the same splits, so the table compares like with like."""
    out: list[ModelEvaluation] = []
    for key, description in BASELINES.items():
        folds: list[Fold] = []
        for split_name, splits in (
            ("leave_one_outbreak_out", leave_one_outbreak_out(panel)),
            ("forward_chaining", forward_chaining(panel)),
        ):
            for name, train, test in splits:
                predicted = baseline_predictions(train, test)[key]
                labels = test["label"].to_numpy(dtype=float)
                folds.append(
                    Fold(
                        split=split_name,
                        name=name,
                        test=score(labels, predicted, test["arrival_day"].to_numpy(dtype=float)),
                    )
                )
        out.append(
            ModelEvaluation(
                model=key,
                description=description,
                parameters=0 if key != "train_base_rate" else 1,
                folds=folds,
            )
        )
    return out
