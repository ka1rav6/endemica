"""A small monotone boosted model. It is recorded only when every held-out gate passes."""

from __future__ import annotations

import numpy as np
import pandas as pd

from epiroute.calibration.gates import all_passed, evaluate_gates
from epiroute.calibration.metrics import brier


def compare_to_hazard(panel: pd.DataFrame) -> dict[str, object] | None:
    """Fit a boosted classifier if scikit-learn is installed. Otherwise skip."""
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier
    except ImportError:
        return None

    features = ["lambda", "inbound_passengers", "log_population"]
    folds: list[dict[str, object]] = []
    for held_out in sorted(panel["outbreak"].unique()):
        train = panel[panel["outbreak"] != held_out]
        test = panel[panel["outbreak"] == held_out]
        if train["label"].nunique() < 2 or test.empty:
            continue
        model = HistGradientBoostingClassifier(
            max_depth=2,
            max_iter=50,
            learning_rate=0.1,
            monotonic_cst=[1, 1, 0],
            random_state=0,
        )
        model.fit(train[features], train["label"].astype(int))
        predicted = model.predict_proba(test[features])[:, 1]
        labels = test["label"].to_numpy(dtype=float)
        lam = np.clip(test["lambda"].to_numpy(dtype=float), 0, None)
        uncalibrated = 1.0 - np.exp(-lam * 28.0)
        inbound = test["inbound_passengers"].to_numpy(dtype=float)
        simple = np.clip(1.0 - np.exp(-inbound / 1.0e5), 0, 1)
        gates = evaluate_gates(
            labels=labels,
            predicted=predicted,
            uncalibrated=uncalibrated,
            best_simple=simple,
            arrival_day=test["arrival_day"].to_numpy(dtype=float),
            monotone=True,
        )
        folds.append(
            {
                "held_out": str(held_out),
                "brier": brier(labels, predicted),
                "passed": all_passed(gates),
            }
        )
    if not folds:
        return {"beats_hazard": False, "reason": "no fold had both classes"}
    beats = all(bool(fold["passed"]) for fold in folds)
    reason = (
        "passed the held-out gates, but the served number stays the hazard model"
        if beats
        else "did not pass every held-out gate, so it is not served"
    )
    return {"beats_hazard": beats, "reason": reason, "folds": folds}
