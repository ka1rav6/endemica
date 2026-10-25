"""The backtest must not see reports published after the forecast date."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from endemica.calibration.leakage import (
    LeakageError,
    assert_inputs_not_after_forecast,
    assert_outbreaks_disjoint,
    label_shift_destroyed_signal,
)


@dataclass
class _Row:
    forecast_at: datetime
    latest_input_at: datetime
    outbreak: str


def test_a_future_report_is_rejected() -> None:
    row = _Row(
        forecast_at=datetime(2020, 3, 1, tzinfo=UTC),
        latest_input_at=datetime(2020, 3, 8, tzinfo=UTC),
        outbreak="covid_2020",
    )
    with pytest.raises(LeakageError, match="covid_2020"):
        assert_inputs_not_after_forecast([row])


def test_an_input_on_the_forecast_date_is_allowed() -> None:
    moment = datetime(2020, 3, 1, tzinfo=UTC)
    assert_inputs_not_after_forecast(
        [_Row(forecast_at=moment, latest_input_at=moment, outbreak="covid_2020")]
    )


def test_overlapping_outbreaks_are_rejected() -> None:
    with pytest.raises(LeakageError, match="mpox_2022"):
        assert_outbreaks_disjoint(["covid_2020", "mpox_2022"], ["mpox_2022"])


def test_a_shifted_label_must_lose_its_ranking_power() -> None:
    assert label_shift_destroyed_signal(0.55)
    assert not label_shift_destroyed_signal(0.8)
