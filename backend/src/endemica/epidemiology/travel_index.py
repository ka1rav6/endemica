"""Composite travel-risk index.

One 0–10 number for "how risky does this destination look under the current
scenario?" It is a weighted mean of the inputs that exist. A missing input is
left out, not filled with zero. If none of the inputs exist, the index is not
estimable.

This is not a calibrated forecast, not a diagnosis, and not official travel
advice. The next-country hazard model is deliberately not an input: that model
is unvalidated unless its card says otherwise, and this index does not take a
forecast probability at all.

Inputs, each scored from 0 to 10
--------------------------------
Local presence ("is it already there?"):

* no grounded report → 0
* reported, but every report is older than 90 days, or the date is unknown → 4
* reported within 90 days → 7
* reported within 90 days and the confirmed-case figure is at least 100 → 9

The case figure is the one already attached to local presence: the highest
grounded confirmed count among the reports that answer "is it already here?"
A report exactly 90 days old still counts as recent. Older than 90 days does not.

Importation: the central probability of at least one infectious arrival within
the horizon, scored on orders of magnitude. Over a two-week horizon these
probabilities span roughly ``1e-6`` to ``1e-1`` across destinations, so a
linear ``10 ×`` map puts almost every country at 0.0 and the index stops
telling them apart. ``log10(p)`` is mapped onto 0-10 instead:

* ``p`` at or below ``1e-6`` → 0
* ``p`` at or above ``0.1`` → 10
* otherwise linear in ``log10(p)`` between those two

Omitted when the probability is not estimable. A computed zero stays in as 0.

Establishment: the central probability that spread takes off within the
horizon, on the same log scale, and only when that probability is estimable.
A computed zero (for example R at or below 1) stays in. "Not estimable" is
omitted.

Connectivity: the gravity/passenger term, scored from the modelled infectious
arrival rate (infected arrivals per day), which already includes passenger
volume. ``log10(rate)`` is mapped onto 0–10:

* no rate → omitted (a top-origin share without a rate is not turned into one)
* rate ≤ 0 → 0
* rate at or below ``1e-6`` per day → 0
* rate ≥ 1 per day → 10
* otherwise linear in ``log10(rate)`` between ``1e-6`` and 1

When the aggregate rate is missing but origin-level rates were still returned,
those origin rates are summed and used. They are not used when an aggregate
rate is present, because the listed origins can be a truncated top-N.

Weights when all four exist: presence 0.40, importation 0.30, establishment
0.15, connectivity 0.15. The weights of the inputs that exist are scaled so
they sum to 1. The displayed index is that mean, rounded to one decimal
(half up). Component scores are rounded the same way for display; the mean is
taken before that rounding.

Bands follow the rounded index: 0–2.9 Low, 3–5.9 Moderate, 6–7.9 High,
8–10 Very high.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

PRESENCE_RECENT_DAYS = 90
LARGE_CONFIRMED_CASES = 100

PRESENCE_ABSENT = 0.0
PRESENCE_STALE = 4.0
PRESENCE_RECENT = 7.0
PRESENCE_RECENT_LARGE = 9.0

# One modelled infectious arrival every million days sits at 0. One per day
# saturates the connectivity term. The scale is linear in log10(rate). The
# floor is well below the rates real destinations produce, because anything
# higher flattens most of the world onto 0 and hides the differences.
CONNECTIVITY_RATE_FLOOR = 1e-6
CONNECTIVITY_RATE_CAP = 1.0

# Probabilities are scored the same way, for the same reason.
PROBABILITY_FLOOR = 1e-6
PROBABILITY_CAP = 0.1

BandLabel = Literal["Low", "Moderate", "High", "Very high"]
ComponentKey = Literal["presence", "importation", "establishment", "connectivity"]

WEIGHTS: dict[ComponentKey, float] = {
    "presence": 0.40,
    "importation": 0.30,
    "establishment": 0.15,
    "connectivity": 0.15,
}

COMPONENT_ORDER: tuple[ComponentKey, ...] = (
    "presence",
    "importation",
    "establishment",
    "connectivity",
)

NOTE = (
    "This is a composite scenario index, not a forecast and not a reason to "
    "ignore official travel advice."
)


@dataclass(frozen=True, slots=True)
class TravelIndexInputs:
    """Plain values the index needs. Missing probabilities and rates stay None."""

    presence_status: str = "not_estimable"
    last_reported_at: datetime | None = None
    cases_confirmed: float | None = None
    as_of: datetime | None = None
    importation_probability: float | None = None
    establishment_probability: float | None = None
    arrival_rate_per_day: float | None = None
    origin_rates: tuple[float, ...] = ()
    top_origin_share: float | None = None


@dataclass(frozen=True, slots=True)
class TravelComponentScore:
    key: ComponentKey
    score: float | None
    weight: float
    available: bool


@dataclass(frozen=True, slots=True)
class TravelIndexResult:
    score: float | None
    band: BandLabel | None
    components: tuple[TravelComponentScore, ...]
    note: str


def round_tenths(value: float) -> float:
    """Round half up to one decimal. Avoid binary ``round``, which ties to even."""
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def band_for(score: float) -> BandLabel:
    """Band of an already-rounded 0–10 index."""
    if score < 3:
        return "Low"
    if score < 6:
        return "Moderate"
    if score < 8:
        return "High"
    return "Very high"


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _finite(value: float | None) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value


def score_presence(
    status: str,
    last_reported_at: datetime | None,
    cases_confirmed: float | None,
    as_of: datetime | None,
) -> float | None:
    """Score local presence. ``not_estimable`` is missing; no report is a real 0."""
    if status == "not_estimable":
        return None
    if status == "not_reported":
        return PRESENCE_ABSENT
    if status != "reported":
        return None
    if last_reported_at is None or as_of is None:
        return PRESENCE_STALE
    age = _aware(as_of) - _aware(last_reported_at)
    if age > timedelta(days=PRESENCE_RECENT_DAYS):
        return PRESENCE_STALE
    cases = _finite(cases_confirmed)
    if cases is not None and cases >= LARGE_CONFIRMED_CASES:
        return PRESENCE_RECENT_LARGE
    return PRESENCE_RECENT


def _log_scale(value: float, floor: float, cap: float) -> float:
    """Map ``value`` onto 0-10, linear in log10 between ``floor`` and ``cap``."""
    if value <= floor:
        return 0.0
    if value >= cap:
        return 10.0
    log_floor = math.log10(floor)
    log_cap = math.log10(cap)
    return 10.0 * (math.log10(value) - log_floor) / (log_cap - log_floor)


def score_probability(probability: float | None) -> float | None:
    """Map a central probability onto 0-10 by orders of magnitude.

    Missing stays missing. A computed zero is a real 0, not a missing value.
    """
    value = _finite(probability)
    if value is None:
        return None
    if value <= 0:
        return 0.0
    return _log_scale(value, PROBABILITY_FLOOR, PROBABILITY_CAP)


def resolve_arrival_rate(
    total_rate: float | None,
    origin_rates: tuple[float, ...],
    top_origin_share: float | None,
) -> float | None:
    """The rate connectivity can score, or None when there is nothing to take log10 of.

    A top-origin share without a rate is not converted into a rate. The share is
    part of the contract so callers can pass the origin breakdown they have.
    """
    total = _finite(total_rate)
    if total is not None:
        return total
    finite_origins = [rate for rate in origin_rates if _finite(rate) is not None]
    if finite_origins:
        return float(sum(finite_origins))
    # A share is a fraction of a rate, not a rate. Without arrivals per day
    # there is nothing to put through log10, so the term stays missing.
    if top_origin_share is not None:
        return None
    return None


def score_connectivity(rate: float) -> float:
    """Map ``log10(arrival rate per day)`` onto 0–10. ``rate`` must be a real number."""
    if rate <= 0:
        return 0.0
    return _log_scale(rate, CONNECTIVITY_RATE_FLOOR, CONNECTIVITY_RATE_CAP)


def compute_travel_index(inputs: TravelIndexInputs) -> TravelIndexResult:
    """Weighted mean of the travel-risk inputs that exist.

    The next-country model is not an argument. Do not fold an unvalidated
    forecast into this score at the call site.
    """
    rate = resolve_arrival_rate(
        inputs.arrival_rate_per_day,
        inputs.origin_rates,
        inputs.top_origin_share,
    )
    raw: dict[ComponentKey, float | None] = {
        "presence": score_presence(
            inputs.presence_status,
            inputs.last_reported_at,
            inputs.cases_confirmed,
            inputs.as_of,
        ),
        "importation": score_probability(inputs.importation_probability),
        "establishment": score_probability(inputs.establishment_probability),
        "connectivity": None if rate is None else score_connectivity(rate),
    }
    present: dict[ComponentKey, float] = {
        key: value for key, value in raw.items() if value is not None
    }
    total_weight = sum(WEIGHTS[key] for key in present)
    score: float | None = None
    band: BandLabel | None = None
    if present and total_weight > 0:
        mean = sum(value * WEIGHTS[key] for key, value in present.items()) / total_weight
        score = round_tenths(min(10.0, max(0.0, mean)))
        band = band_for(score)

    components: list[TravelComponentScore] = []
    for key in COMPONENT_ORDER:
        value = raw[key]
        available = value is not None
        weight = 0.0 if not available else min(1.0, WEIGHTS[key] / total_weight)
        components.append(
            TravelComponentScore(
                key=key,
                score=None if value is None else round_tenths(value),
                weight=weight,
                available=available,
            )
        )
    return TravelIndexResult(
        score=score,
        band=band,
        components=tuple(components),
        note=NOTE,
    )
