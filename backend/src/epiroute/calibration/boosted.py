"""A monotone gradient-boosted challenger, scored on the same folds as the served model.

It is here to answer one question honestly: would a flexible learner do better
than a four-parameter survival model on this panel? The comparison is only
worth anything if nothing about it is tilted, so the challenger gets the same
feature definition, the same two splits, the same gate thresholds and the same
status rule as the model it is challenging.

It is recorded rather than served even when it wins, and the reason is not
caution. A tree ensemble predicts a constant outside the range of arrival rates
it was fitted on, and a new pathogen is exactly the case that sits outside that
range - that is what the held-out folds are standing in for. Serving it would
also mean storing a fitted scikit-learn estimator in ``data/`` and loading it
back at request time, which couples the running API to a library version and
adds a deserialisation step to the request path for a model whose advantage, if
it has one, is a few hundredths of a Brier score. What it would take to change
that decision is written at the end of the result it returns, so the choice can
be revisited with numbers rather than reargued.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from epiroute.calibration.evaluate import (
    baseline_predictions,
    forward_chaining,
    leave_one_outbreak_out,
)
from epiroute.calibration.features import HORIZON_DAYS, design_from_panel, monotone_columns
from epiroute.calibration.gates import evaluate_gates, status_from_gates
from epiroute.calibration.hazard import cloglog_probability, fit_cloglog
from epiroute.calibration.metrics import brier, roc_auc

# Depth two and fifty rounds. The panel has 976 positives across two outbreaks,
# so a deeper or longer ensemble has room to fit one outbreak's idiosyncrasies
# and nothing to stop it. The monotone constraints are the same ones the
# survival model carries: a higher arrival rate or more arriving passengers may
# not lower the predicted chance.
MAX_DEPTH = 2
MAX_ITER = 50
LEARNING_RATE = 0.1
RANDOM_STATE = 0


def _fit_predict(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray | None:
    from sklearn.ensemble import HistGradientBoostingClassifier

    if train["label"].nunique() < 2 or test.empty:
        return None
    model = HistGradientBoostingClassifier(
        max_depth=MAX_DEPTH,
        max_iter=MAX_ITER,
        learning_rate=LEARNING_RATE,
        # One entry per served feature, in the order design_from_panel builds
        # them, with the intercept column dropped.
        monotonic_cst=[1, 1, 0],
        random_state=RANDOM_STATE,
    )
    model.fit(design_from_panel(train)[:, 1:], train["label"].astype(int))
    predicted: np.ndarray = model.predict_proba(design_from_panel(test)[:, 1:])[:, 1]
    return predicted


def compare_to_hazard(panel: pd.DataFrame) -> dict[str, object] | None:
    """Score the challenger beside the served model. ``None`` when scikit-learn is absent."""
    try:
        import sklearn  # noqa: F401
    except ImportError:
        return None

    folds: list[dict[str, Any]] = []
    gates: list[list[Any]] = []
    for split, splits in (
        ("leave_one_outbreak_out", leave_one_outbreak_out(panel)),
        ("forward_chaining", forward_chaining(panel)),
    ):
        for name, train, test in splits:
            predicted = _fit_predict(train, test)
            if predicted is None:
                continue
            labels = test["label"].to_numpy(dtype=float)
            served = cloglog_probability(
                design_from_panel(test),
                fit_cloglog(
                    design_from_panel(train),
                    train["label"].to_numpy(dtype=float),
                    horizon_days=HORIZON_DAYS,
                    monotone_columns=monotone_columns(),
                ),
                HORIZON_DAYS,
            )
            baselines = baseline_predictions(train, test)
            result = evaluate_gates(
                labels=labels,
                predicted=predicted,
                uncalibrated=baselines["uncalibrated_poisson"],
                best_simple=baselines["inbound_passengers_only"],
                arrival_day=test["arrival_day"].to_numpy(dtype=float),
                monotone=True,
            )
            if split == "leave_one_outbreak_out":
                gates.append(result)
            folds.append(
                {
                    "split": split,
                    "fold": name,
                    "challenger_brier": brier(labels, predicted),
                    "challenger_auc": roc_auc(labels, predicted),
                    "served_brier": brier(labels, served),
                    "served_auc": roc_auc(labels, served),
                }
            )

    if not folds:
        return {"status": "not_validated", "reason": "no fold had both classes"}

    held_out = [fold for fold in folds if fold["split"] == "leave_one_outbreak_out"]
    wins_brier = all(
        float(fold["challenger_brier"]) < float(fold["served_brier"]) for fold in held_out
    )
    wins_auc = all(
        float(fold["challenger_auc"]) > float(fold["served_auc"])
        for fold in held_out
        if np.isfinite(fold["challenger_auc"]) and np.isfinite(fold["served_auc"])
    )
    status = status_from_gates(gates)
    beats = bool(held_out) and wins_brier and wins_auc
    return {
        "status": status,
        "beats_served_on_every_held_out_fold": beats,
        "served": False,
        "folds": folds,
        "reason": (
            "It wins on every held-out fold. It is still not served, for the reasons "
            "in this module's docstring: a tree ensemble predicts a constant outside "
            "the arrival rates it saw, which is the case a new pathogen puts it in."
            if beats
            else "It does not beat the served model on every held-out fold."
        ),
        "what_would_change_this": (
            "A third and fourth training outbreak, so a held-out fold is a test of "
            "generalisation rather than a test of transfer between two pathogens; and "
            "a way to serve the fitted estimator that does not put library-version "
            "coupling and a deserialisation step on the request path."
        ),
    }
