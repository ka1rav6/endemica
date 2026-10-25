"""The one definition of the hazard model's inputs.

Training and serving both build their design matrix here. They used not to:
the panel summed Eurostat's observed flows only, while the live ranking summed
every flow in the table, observed and gravity-estimated alike. Observed flows
cover 1,884 of 50,400 country pairs, so two thirds of the training rows had an
arrival rate of exactly zero while the same country at serving time had a
positive one. A coefficient fitted on a feature that is structurally zero in
training and positive in production is not a coefficient for that feature, so
the numbers the app showed were never the numbers the model was scored on.
After the panel was rebuilt through this module the share of rows with a zero
rate fell from 69% to 7%.

Keeping both callers on one function is what stops that happening again.

The columns are all knowable at the moment a forecast is made, for a pathogen
the model has never seen:

``log_lambda``
    Log of the arrival rate: prevalence at each affected origin times
    passengers per day on that origin-to-destination pair, times the fraction
    of travellers who could be infectious. This is the mechanism the app is
    built around.
``log_inbound``
    Log of one plus passengers per day arriving from affected origins, with no
    case data in it at all. It is here because the arrival rate above is
    0.96-correlated with it: across this panel the prevalence term adds almost
    nothing to travel volume, and on its own it ranks worse than volume does
    (held-out AUC 0.70 against 0.76). Carrying both lets the fit decide how
    much the prevalence estimate is worth rather than assuming it. At that
    correlation their individual coefficients should not be read apart;
    together they are the travel term.
``log_affected``
    Log of one plus the number of countries already reporting. This replaces
    what used to be an intercept fitted separately for each outbreak. An
    intercept keyed to the outbreak cannot be known for an outbreak that has
    not happened yet, which is why the fitted model could only ever score
    COVID-19 and mpox and went unused for every other disease in the app. The
    count of already-affected countries is the same quantity made observable:
    it rises as an epidemic becomes global, and the app knows it for a live
    outbreak.

Destination population is deliberately **not** here. It is the one feature
that measurably fails to transfer between pathogens: adding it lifts the
within-outbreak forecast (forward-chained AUC 0.745 to 0.803) and wrecks the
held-out one for mpox (AUC 0.768 to 0.633, Brier 0.149 to 0.209). That is not
noise, it is the mechanism - how much of a country's population is exposed
depends on how the pathogen spreads, and mpox in 2022 spread through specific
contact networks rather than in proportion to headcount. Every disease in the
app except COVID-19 and mpox is in the held-out position, so the model is built
for that case and the ablation stays in the evaluation report as the evidence.

Four parameters including the intercept, against 976 positives in the panel.
The model is not in a position to memorise them.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Column order is part of the model: a stored coefficient vector is read back
# against this tuple, so appending is safe and reordering is not.
FEATURE_NAMES: tuple[str, ...] = ("log_lambda", "log_inbound", "log_affected")

# These two may not take a negative coefficient. More infectious travellers
# arriving, or more travellers arriving, cannot lower the chance of arrival,
# whatever a finite sample suggests, and a sign flip is the first thing a model
# with two outbreaks does when it overfits. The constraint is a prior with a
# mechanism behind it, not a tuning knob. The affected count is left free in
# both directions, because a wider epidemic means both more origins to leave
# and fewer destinations left to reach.
MONOTONE_FEATURES: tuple[str, ...] = ("log_lambda", "log_inbound")

# The horizon the model is fitted for. Serving a different one is serving a
# different model, so the card records it and the API will not reuse it.
HORIZON_DAYS = 28.0

# A rate of zero is a real observation - no flight data linked that pair - and
# the log of it is not. The floor sits far below the smallest non-zero rate in
# the panel, so those rows group at the bottom of the ranking rather than being
# dropped. Serving treats such a destination as having no answer rather than a
# low one; see ``has_evidence``.
LAMBDA_FLOOR = 1e-12


@dataclass(frozen=True, slots=True)
class FeatureRow:
    """One destination's inputs at one moment, in the units the model expects."""

    arrival_rate_per_day: float
    inbound_passengers_per_day: float
    affected_country_count: int

    @property
    def has_evidence(self) -> bool:
        """Whether anything connects this destination to the outbreak.

        No inbound passengers from any affected country means the model has
        been given nothing to work from. The fitted curve will still return a
        number there, and that number is the intercept rather than a finding,
        so serving reports it as unavailable instead. Seven per cent of the
        panel's rows are in this position.
        """
        return self.inbound_passengers_per_day > 0.0


def _columns(rate: np.ndarray, inbound: np.ndarray, affected: np.ndarray) -> np.ndarray:
    return np.column_stack(
        [
            np.ones(len(rate), dtype=float),
            np.log(np.clip(rate, LAMBDA_FLOOR, None)),
            np.log1p(np.clip(inbound, 0.0, None)),
            np.log1p(np.clip(affected, 0.0, None)),
        ]
    )


def design_matrix(rows: list[FeatureRow]) -> np.ndarray:
    """``(n, 1 + len(FEATURE_NAMES))`` with the intercept in column zero."""
    if not rows:
        return np.empty((0, 1 + len(FEATURE_NAMES)), dtype=float)
    return _columns(
        np.array([row.arrival_rate_per_day for row in rows], dtype=float),
        np.array([row.inbound_passengers_per_day for row in rows], dtype=float),
        np.array([row.affected_country_count for row in rows], dtype=float),
    )


def design_from_panel(frame: pd.DataFrame) -> np.ndarray:
    """The same matrix, read off a stored panel."""
    needed = {"lambda", "inbound_passengers", "affected_count"}
    missing = needed - set(frame.columns)
    if missing:
        msg = f"panel is missing {sorted(missing)}; rebuild it with train-model --rebuild-panel"
        raise KeyError(msg)
    return _columns(
        frame["lambda"].to_numpy(dtype=float),
        frame["inbound_passengers"].to_numpy(dtype=float),
        frame["affected_count"].to_numpy(dtype=float),
    )


def monotone_columns() -> tuple[int, ...]:
    """Indexes into the design matrix that may not take a negative coefficient."""
    return tuple(FEATURE_NAMES.index(name) + 1 for name in MONOTONE_FEATURES)
