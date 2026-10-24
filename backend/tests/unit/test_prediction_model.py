"""The prediction model: one feature definition, an honest fit, and guards on both."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from epiroute.calibration.evaluate import (
    forward_chaining,
    leave_one_outbreak_out,
    permutation_auc,
    uncalibrated,
)
from epiroute.calibration.features import (
    FEATURE_NAMES,
    HORIZON_DAYS,
    FeatureRow,
    design_from_panel,
    design_matrix,
    monotone_columns,
)
from epiroute.calibration.gates import GateResult, status_from_gates
from epiroute.calibration.hazard import cloglog_probability, fit_cloglog
from epiroute.calibration.metrics import calibration_line, top_k_precision


def panel(rows: int = 400, seed: int = 0) -> pd.DataFrame:
    generator = np.random.default_rng(seed)
    inbound = generator.lognormal(mean=6.0, sigma=2.0, size=rows)
    frame = pd.DataFrame(
        {
            "outbreak": np.where(np.arange(rows) % 2 == 0, "one", "two"),
            "week_index": (np.arange(rows) % 16) + 1,
            "lambda": inbound * 1e-7,
            "inbound_passengers": inbound,
            "log_population": generator.normal(7.0, 1.0, size=rows),
            "affected_count": generator.integers(1, 60, size=rows),
            "arrival_day": generator.integers(1, 60, size=rows).astype(float),
        }
    )
    design = design_from_panel(frame)
    truth = np.array([-7.0, 0.0, 0.5, -0.2])
    probability = cloglog_probability(design, truth, HORIZON_DAYS)
    frame["label"] = (generator.random(rows) < probability).astype(int)
    return frame


def test_serving_and_training_build_the_same_row() -> None:
    # The bug this guards against put the two callers on different flow
    # tables, so a fitted coefficient did not apply to the number served.
    frame = pd.DataFrame(
        {
            "lambda": [2.5e-6],
            "inbound_passengers": [1200.0],
            "affected_count": [7],
        }
    )
    served = design_matrix(
        [
            FeatureRow(
                arrival_rate_per_day=2.5e-6,
                inbound_passengers_per_day=1200.0,
                affected_country_count=7,
            )
        ]
    )
    np.testing.assert_allclose(design_from_panel(frame), served)


def test_the_design_has_an_intercept_and_one_column_per_named_feature() -> None:
    frame = panel(20)
    assert design_from_panel(frame).shape == (20, 1 + len(FEATURE_NAMES))


def test_a_panel_without_the_inbound_column_is_refused_rather_than_guessed() -> None:
    frame = panel(20).drop(columns=["inbound_passengers"])
    with pytest.raises(KeyError, match="rebuild"):
        design_from_panel(frame)


def test_a_zero_rate_row_is_a_question_the_model_declines() -> None:
    row = FeatureRow(
        arrival_rate_per_day=0.0, inbound_passengers_per_day=0.0, affected_country_count=5
    )
    assert not row.has_evidence
    assert FeatureRow(0.0, 1.0, 5).has_evidence


def test_the_travel_coefficients_cannot_come_out_negative() -> None:
    frame = panel(600, seed=3)
    # Labels inverted, so an unconstrained fit would want a negative slope.
    frame["label"] = 1 - frame["label"]
    beta = fit_cloglog(
        design_from_panel(frame),
        frame["label"].to_numpy(dtype=float),
        horizon_days=HORIZON_DAYS,
        monotone_columns=monotone_columns(),
    )
    for column in monotone_columns():
        assert beta[column] >= 0.0


def test_the_fit_recovers_a_slope_it_was_given() -> None:
    generator = np.random.default_rng(11)
    rows = 4000
    feature = generator.normal(size=rows)
    design = np.column_stack([np.ones(rows), feature])
    truth = np.array([-7.0, 0.9])
    labels = (generator.random(rows) < cloglog_probability(design, truth, HORIZON_DAYS)).astype(
        float
    )
    beta = fit_cloglog(design, labels, horizon_days=HORIZON_DAYS, monotone_columns=(1,))
    assert beta[1] == pytest.approx(0.9, abs=0.2)


def test_the_fit_is_the_same_on_a_second_run() -> None:
    frame = panel(300, seed=5)
    design = design_from_panel(frame)
    labels = frame["label"].to_numpy(dtype=float)
    first = fit_cloglog(design, labels, horizon_days=HORIZON_DAYS)
    second = fit_cloglog(design, labels, horizon_days=HORIZON_DAYS)
    np.testing.assert_array_equal(first, second)


def test_shuffling_the_training_labels_destroys_the_held_out_ranking() -> None:
    from epiroute.calibration.evaluate import CANDIDATES

    served = next(candidate for candidate in CANDIDATES if candidate.name == "hazard")
    score = permutation_auc(served, panel(600, seed=7))
    assert 0.35 <= score <= 0.65


def test_no_outbreak_appears_on_both_sides_of_a_held_out_split() -> None:
    frame = panel(200)
    for name, train, test in leave_one_outbreak_out(frame):
        assert name not in set(train["outbreak"])
        assert set(test["outbreak"]) == {name}


def test_a_forward_fold_never_trains_on_a_week_it_is_scored_on() -> None:
    folds = forward_chaining(panel(600, seed=9))
    assert folds
    for _name, train, test in folds:
        assert train["week_index"].max() < test["week_index"].min()


def test_the_uncalibrated_baseline_is_the_formula_the_app_falls_back_to() -> None:
    frame = pd.DataFrame({"lambda": [0.0, 0.01]})
    np.testing.assert_allclose(uncalibrated(frame, 28.0), [0.0, 1.0 - np.exp(-0.28)], rtol=1e-12)


def test_a_constant_forecast_has_no_calibration_line_rather_than_an_error() -> None:
    labels = np.array([0.0, 1.0, 0.0, 1.0])
    slope, intercept = calibration_line(labels, np.full(4, 0.4))
    assert not np.isfinite(slope)
    assert not np.isfinite(intercept)


def test_top_k_precision_is_attainable_where_recall_was_not() -> None:
    labels = np.concatenate([np.ones(300), np.zeros(300)])
    predicted = np.concatenate([np.linspace(0.9, 0.6, 300), np.linspace(0.4, 0.1, 300)])
    assert top_k_precision(labels, predicted, 20) == 1.0


def _gate(name: str, passed: bool) -> GateResult:
    return GateResult(name, passed, 1.0, "")


def test_a_validated_ordering_with_an_unvalidated_level_is_its_own_status() -> None:
    ranking = [
        _gate("brier_skill_vs_uncalibrated", True),
        _gate("roc_auc", True),
        _gate("monotone_in_lambda", True),
        _gate("calibration_slope", True),
        _gate("calibration_intercept", False),
    ]
    assert status_from_gates([ranking, ranking]) == "ranking_validated"


def test_both_sets_passing_is_calibrated_and_a_failing_ordering_is_neither() -> None:
    passing = [
        _gate("brier_skill_vs_uncalibrated", True),
        _gate("roc_auc", True),
        _gate("monotone_in_lambda", True),
        _gate("calibration_slope", True),
        _gate("calibration_intercept", True),
    ]
    assert status_from_gates([passing, passing]) == "calibrated"
    failing = [*passing[:1], _gate("roc_auc", False), *passing[2:]]
    assert status_from_gates([passing, failing]) == "not_validated"


def test_one_fold_is_not_enough_to_validate_anything() -> None:
    passing = [
        _gate("brier_skill_vs_uncalibrated", True),
        _gate("roc_auc", True),
        _gate("monotone_in_lambda", True),
        _gate("calibration_slope", True),
        _gate("calibration_intercept", True),
    ]
    assert status_from_gates([passing]) == "not_validated"
