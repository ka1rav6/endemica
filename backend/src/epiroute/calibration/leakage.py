"""Guards that stop a backtest from seeing the future.

A row is one destination in one forecast week. ``latest_input_at`` is the newest
timestamp of any case count, flow table, or label feature on that row.
``forecast_at`` is the moment the prediction is supposed to have been made.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol


class LeakageError(Exception):
    """A training or evaluation row used information from after its forecast date."""


class ForecastRow(Protocol):
    forecast_at: datetime
    latest_input_at: datetime
    outbreak: str


def assert_inputs_not_after_forecast(rows: Sequence[ForecastRow]) -> None:
    """Raise when any row's inputs are newer than the forecast it claims to make."""
    for row in rows:
        if row.latest_input_at > row.forecast_at:
            msg = (
                f"{row.outbreak} at {row.forecast_at.isoformat()} uses an input from "
                f"{row.latest_input_at.isoformat()}"
            )
            raise LeakageError(msg)


def assert_outbreaks_disjoint(train: Sequence[str], test: Sequence[str]) -> None:
    """Leave-one-outbreak-out is void if an outbreak sits in both sides."""
    overlap = set(train) & set(test)
    if overlap:
        msg = f"outbreaks appear in both train and test: {sorted(overlap)}"
        raise LeakageError(msg)


def label_shift_destroyed_signal(shifted_auc: float, *, ceiling: float = 0.6) -> bool:
    """A model that still ranks well after labels move 8 weeks is using a leak.

    The check passes when the shifted score falls below ``ceiling``.
    """
    return shifted_auc < ceiling
