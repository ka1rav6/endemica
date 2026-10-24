"""Fit the hazard on one outbreak and score it on the other."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from epiroute.calibration.gates import all_passed, evaluate_gates
from epiroute.calibration.hazard import HazardCoefficients, fit_b0_by_outbreak, probability
from epiroute.calibration.labels import labels_dir
from epiroute.calibration.metrics import brier
from epiroute.core.config import Settings, get_settings


def _matrix(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    log_lambda = np.log(np.clip(frame["lambda"].to_numpy(dtype=float), 1e-12, None))
    log_population = frame["log_population"].to_numpy(dtype=float)
    labels = frame["label"].to_numpy(dtype=float)
    outbreaks = frame["outbreak"].to_numpy(dtype=str)
    return outbreaks, log_lambda, log_population, labels


def train(settings: Settings | None = None) -> Path:
    """Leave one outbreak out. The card is written either way; passing is separate."""
    settings = settings or get_settings()
    panel = pd.read_parquet(labels_dir(settings) / "panel.parquet")
    panel["forecast_at"] = pd.to_datetime(panel["forecast_at"])
    outbreaks = sorted(panel["outbreak"].unique())
    folds: list[dict[str, object]] = []
    intercepts: dict[str, float] = {}
    slope = 1.0
    population_slope = 0.0

    for held_out in outbreaks:
        train_frame = panel[panel["outbreak"] != held_out]
        test_frame = panel[panel["outbreak"] == held_out]
        if train_frame.empty or test_frame.empty or train_frame["label"].sum() == 0:
            folds.append({"held_out": held_out, "skipped": True})
            continue
        train_outbreaks, train_lambda, train_population, train_labels = _matrix(train_frame)
        fitted_intercepts, slope, population_slope = fit_b0_by_outbreak(
            train_outbreaks,
            train_lambda,
            train_population,
            train_labels,
            horizon_days=28.0,
        )
        intercepts.update(fitted_intercepts)
        _test_outbreaks, test_lambda, test_population, test_labels = _matrix(test_frame)
        b0 = float(np.median(list(fitted_intercepts.values())))
        _guard_fold(train_frame, test_frame, held_out)
        coefficients = HazardCoefficients(b0, slope, population_slope)
        predicted = probability(coefficients, test_lambda, test_population, 28.0)
        uncalibrated = 1.0 - np.exp(-np.exp(test_lambda) * 28.0)
        simple = 1.0 - np.exp(-test_frame["inbound_passengers"].to_numpy(dtype=float) / 1.0e5)
        simple = np.clip(simple, 0.0, 1.0)
        arrival = test_frame["arrival_day"].to_numpy(dtype=float)
        gates = evaluate_gates(
            labels=test_labels,
            predicted=predicted,
            uncalibrated=uncalibrated,
            best_simple=simple,
            arrival_day=arrival,
            monotone=slope >= 0,
        )
        folds.append(
            {
                "held_out": held_out,
                "skipped": False,
                "brier": brier(test_labels, predicted),
                "serve_b0": b0,
                "serve_b1": slope,
                "serve_g": population_slope,
                "gates": [asdict(gate) for gate in gates],
                "passed": all_passed(gates),
            }
        )

    scored = [fold for fold in folds if not fold.get("skipped")]
    # all([]) is True in Python. A card with only skipped folds has not been tested.
    passed = (
        len(scored) >= 2
        and all(bool(fold.get("passed")) for fold in scored)
        and bool(intercepts)
    )
    card = {
        "passed": passed,
        "status": "calibrated" if passed else "not_validated",
        "b1": slope,
        "g": population_slope,
        "b0_by_outbreak": intercepts,
        "folds": folds,
        "claim": (
            "Held-out chance that a country reports its first case within 28 days, "
            "for the outbreaks in this card. Not a forecast for a new pathogen."
        ),
    }
    boosted = _maybe_boosted(panel)
    if boosted is not None:
        card["boosted"] = boosted
        # The app serves the hazard. A boosted model is recorded, not substituted,
        # because a single fit on every outbreak would see the held-out one.
        card["boosted_shipped"] = False
    card["panel_sha256"] = _sha256(labels_dir(settings) / "panel.parquet")
    target = settings.processed_data_dir / "model_card.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(card, indent=2, default=str), encoding="utf-8")
    return target


def _guard_fold(train_frame: pd.DataFrame, test_frame: pd.DataFrame, held_out: str) -> None:
    """Run the leakage guards on one split. They raise if a row sees the future."""
    from epiroute.calibration.leakage import (
        assert_inputs_not_after_forecast,
        assert_outbreaks_disjoint,
    )

    class _Row:
        def __init__(self, forecast_at: object, latest_input_at: object, outbreak: str) -> None:
            self.forecast_at = forecast_at
            self.latest_input_at = latest_input_at
            self.outbreak = outbreak

    rows = [
        _Row(row.forecast_at, row.latest_input_at, str(row.outbreak))
        for row in test_frame.itertuples(index=False)
    ]
    assert_inputs_not_after_forecast(rows)
    assert_outbreaks_disjoint(list(train_frame["outbreak"].unique()), [held_out])


def _maybe_boosted(panel: pd.DataFrame) -> dict[str, object] | None:
    try:
        from epiroute.calibration.boosted import compare_to_hazard
    except ImportError:
        return None
    return compare_to_hazard(panel)


def _sha256(path: Path) -> str | None:
    import hashlib

    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_card(settings: Settings | None = None) -> dict[str, object] | None:
    settings = settings or get_settings()
    path = settings.processed_data_dir / "model_card.json"
    if not path.exists():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def calibration_status(settings: Settings | None = None) -> str:
    card = load_card(settings)
    if card is None or card.get("status") != "calibrated":
        return "not_validated"
    settings = settings or get_settings()
    if card.get("panel_sha256") != _sha256(labels_dir(settings) / "panel.parquet"):
        return "not_validated"
    return "calibrated"
