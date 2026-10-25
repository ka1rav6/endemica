"""Fit the served model, score it on outbreaks it has not seen, and write both down.

Two artefacts come out of one run and they have different jobs. The card in
``data/processed/model_card.json`` is what the API reads: the coefficients it
serves, the band around them, and the strongest claim the evidence supports.
``MODEL_EVALUATION.md`` in the repository root is what a person reads, and it
is rewritten from scratch every time, so a number in it is never older than the
coefficients beside it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from endemica.calibration import report as report_module
from endemica.calibration.evaluate import (
    CANDIDATES,
    baseline_predictions,
    evaluate_baselines,
    evaluate_candidate,
    leave_one_outbreak_out,
)
from endemica.calibration.features import (
    FEATURE_NAMES,
    HORIZON_DAYS,
    design_from_panel,
    monotone_columns,
)
from endemica.calibration.gates import GateResult, evaluate_gates, status_from_gates
from endemica.calibration.hazard import cloglog_probability, fit_cloglog
from endemica.calibration.labels import labels_dir
from endemica.core.config import Settings, get_settings

MODEL_VERSION = "hazard-cloglog-2"
SERVED_MODEL = "hazard"


def _panel(settings: Settings) -> pd.DataFrame:
    panel = pd.read_parquet(labels_dir(settings) / "panel.parquet")
    panel["forecast_at"] = pd.to_datetime(panel["forecast_at"])
    panel["latest_input_at"] = pd.to_datetime(panel["latest_input_at"])
    return panel


def train(settings: Settings | None = None) -> Path:
    """Write the card and the report. The card is written whether or not it passed."""
    settings = settings or get_settings()
    panel = _panel(settings)

    fold_coefficients: dict[str, list[float]] = {}
    gates: dict[str, list[GateResult]] = {}
    for name, train_frame, test_frame in leave_one_outbreak_out(panel):
        _guard_fold(train_frame, test_frame, name)
        beta = fit_cloglog(
            design_from_panel(train_frame),
            train_frame["label"].to_numpy(dtype=float),
            horizon_days=HORIZON_DAYS,
            monotone_columns=monotone_columns(),
        )
        predicted = cloglog_probability(design_from_panel(test_frame), beta, HORIZON_DAYS)
        baselines = baseline_predictions(train_frame, test_frame)
        fold_coefficients[name] = [float(value) for value in beta]
        gates[name] = evaluate_gates(
            labels=test_frame["label"].to_numpy(dtype=float),
            predicted=predicted,
            uncalibrated=baselines["uncalibrated_poisson"],
            best_simple=baselines["inbound_passengers_only"],
            arrival_day=test_frame["arrival_day"].to_numpy(dtype=float),
            monotone=all(value >= 0 for value in beta[1:3]),
        )

    status = status_from_gates(list(gates.values()))

    # The served coefficients are fitted on the whole panel. The folds above are
    # the evidence that a model fitted this way generalises; the fit that is
    # served should then use every row of evidence there is. Serving one fold's
    # coefficients, which is what the previous version did, meant the app could
    # only answer for the outbreak that fold held out.
    served = fit_cloglog(
        design_from_panel(panel),
        panel["label"].to_numpy(dtype=float),
        horizon_days=HORIZON_DAYS,
        monotone_columns=monotone_columns(),
    )

    evaluations = [evaluate_candidate(candidate, panel) for candidate in CANDIDATES]
    served_evaluation = next(
        evaluation for evaluation in evaluations if evaluation.model == SERVED_MODEL
    )
    ablations = [evaluation for evaluation in evaluations if evaluation.model != SERVED_MODEL]

    panel_sha = _sha256(labels_dir(settings) / "panel.parquet")
    provenance = _provenance(settings, panel)
    coefficients = dict(
        zip(("intercept", *FEATURE_NAMES), (float(value) for value in served), strict=True)
    )

    card: dict[str, object] = {
        "model_version": MODEL_VERSION,
        "status": status,
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "horizon_days": HORIZON_DAYS,
        "feature_names": list(FEATURE_NAMES),
        "coefficients": coefficients,
        "served_beta": [float(value) for value in served],
        # The band is the two folds' coefficient vectors. A destination's low
        # and high are what this model would have said about it had it never
        # seen COVID-19, and had it never seen mpox. That is a statement about
        # which outbreaks the fit happens to rest on, which is the dominant
        # uncertainty here, and it is not a confidence interval.
        "band_beta": dict(sorted(fold_coefficients.items())),
        "gates": {name: [asdict(result) for result in results] for name, results in gates.items()},
        "panel_sha256": panel_sha,
        "panel_provenance": provenance,
        "claim": _claim(status),
        "report": report_module.REPORT_NAME,
    }
    challenger = _challenger(panel)
    if challenger is not None:
        card["challenger"] = challenger

    target = settings.processed_data_dir / "model_card.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(card, indent=2, default=str), encoding="utf-8")

    report_module.write(
        report_module.ReportInput(
            served=served_evaluation,
            ablations=ablations,
            baselines=evaluate_baselines(panel),
            challenger=challenger,
            gravity=_gravity(settings),
            panel_provenance=provenance,
            panel_sha256=panel_sha,
            status=status,
            gates={name: [asdict(result) for result in results] for name, results in gates.items()},
            coefficients=coefficients,
            horizon_days=HORIZON_DAYS,
        )
    )
    return target


def _claim(status: str) -> str:
    if status == "calibrated":
        return (
            "Held-out chance that a country reports its first case within 28 days. "
            "Both the ordering and the level passed on an outbreak the fit had not seen."
        )
    if status == "ranking_validated":
        return (
            "Held-out ordering of which countries report next within 28 days. The "
            "ordering passed on both outbreaks the fit had not seen; the absolute "
            "level did not, so the number is indicative and the band is wide."
        )
    return (
        "Not validated. The app falls back to the uncalibrated arrival-rate arithmetic and says so."
    )


def _provenance(settings: Settings, panel: pd.DataFrame) -> dict[str, object]:
    path = labels_dir(settings) / "panel_provenance.json"
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    return {
        "rows": len(panel),
        "positives": int(panel["label"].sum()),
        "zero_rate_share": float((panel["lambda"] <= 0).mean()),
    }


def _gravity(settings: Settings) -> dict[str, object] | None:
    path = settings.processed_data_dir / "gravity_fit.json"
    if not path.exists():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def _guard_fold(train_frame: pd.DataFrame, test_frame: pd.DataFrame, held_out: str) -> None:
    """Run the leakage guards on one split. They raise if a row sees the future."""
    from endemica.calibration.leakage import (
        assert_inputs_not_after_forecast,
        assert_outbreaks_disjoint,
    )

    class _Row:
        def __init__(self, forecast_at: datetime, latest_input_at: datetime, outbreak: str) -> None:
            self.forecast_at = forecast_at
            self.latest_input_at = latest_input_at
            self.outbreak = outbreak

    rows: list[_Row] = [
        _Row(
            cast("datetime", row.forecast_at),
            cast("datetime", row.latest_input_at),
            str(row.outbreak),
        )
        for row in test_frame.itertuples(index=False)
    ]
    assert_inputs_not_after_forecast(rows)
    assert_outbreaks_disjoint(list(train_frame["outbreak"].unique()), [held_out])


def _challenger(panel: pd.DataFrame) -> dict[str, object] | None:
    try:
        from endemica.calibration.boosted import compare_to_hazard
    except ImportError:
        return None
    return compare_to_hazard(panel)


def _sha256(path: Path) -> str | None:
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
    """The card's status, but only while the card still matches the panel on disk."""
    card = load_card(settings)
    if card is None:
        return "not_validated"
    status = card.get("status")
    if status not in ("calibrated", "ranking_validated"):
        return "not_validated"
    settings = settings or get_settings()
    if card.get("panel_sha256") != _sha256(labels_dir(settings) / "panel.parquet"):
        return "not_validated"
    return str(status)


def served_coefficients(card: dict[str, object]) -> np.ndarray | None:
    """The coefficient vector the card says to serve, or ``None`` if it is unusable."""
    beta = card.get("served_beta")
    if not isinstance(beta, list) or len(beta) != 1 + len(FEATURE_NAMES):
        return None
    try:
        values = np.array([float(value) for value in beta], dtype=float)
    except (TypeError, ValueError):
        return None
    if not np.all(np.isfinite(values)):
        return None
    # The two travel terms are constrained non-negative when fitted. A card
    # that says otherwise was not written by this code and is not served.
    return values if values[1] >= 0 and values[2] >= 0 else None


def band_coefficients(card: dict[str, object]) -> list[np.ndarray]:
    """One coefficient vector per held-out refit, for the low and high bounds."""
    band = card.get("band_beta")
    if not isinstance(band, dict):
        return []
    out: list[np.ndarray] = []
    for values in band.values():
        if not isinstance(values, list) or len(values) != 1 + len(FEATURE_NAMES):
            continue
        try:
            vector = np.array([float(value) for value in values], dtype=float)
        except (TypeError, ValueError):
            continue
        if np.all(np.isfinite(vector)):
            out.append(vector)
    return out
