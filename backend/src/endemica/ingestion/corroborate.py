"""Compare two sources' case counts without mixing them into one incidence series.

Agreement is the larger of 5 cases or 10 percent. A wider gap widens the
scenario band. A gap above 50 percent is held for a person to review.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

AGREEMENT_CASES = 5
AGREEMENT_FRACTION = 0.10
CONFLICT_FRACTION = 0.50
MAX_DATE_GAP_DAYS = 7


@dataclass(frozen=True, slots=True)
class CountPoint:
    source_name: str
    pathogen_key: str
    country_iso3: str
    metric: str
    value: float
    as_of: datetime


@dataclass(frozen=True, slots=True)
class Corroboration:
    verdict: str
    relative_difference: float | None
    date_gap_days: float | None
    low_value: float | None
    high_value: float | None
    central_source: str | None


def _gap(left: CountPoint, right: CountPoint) -> float:
    return abs((left.as_of - right.as_of).total_seconds()) / 86400.0


def corroborate(primary: CountPoint, other: CountPoint) -> Corroboration:
    """Compare one WHO count with one count from a different source.

    The two points must name the same pathogen, country and metric. Incidence
    is never computed from the pair: this only accepts or challenges a level.
    """
    if primary.source_name == other.source_name:
        return Corroboration("same_source", None, None, None, None, None)
    if (
        primary.pathogen_key != other.pathogen_key
        or primary.country_iso3 != other.country_iso3
        or primary.metric != other.metric
    ):
        return Corroboration("not_comparable", None, None, None, None, None)

    gap_days = _gap(primary, other)
    if gap_days > MAX_DATE_GAP_DAYS:
        return Corroboration("unmatched", None, gap_days, None, None, None)

    larger = max(primary.value, other.value, 1.0)
    difference = abs(primary.value - other.value) / larger
    allowance = max(AGREEMENT_CASES / larger, AGREEMENT_FRACTION)
    if gap_days > 3:
        allowance = max(allowance, 0.20)
    low = min(primary.value, other.value)
    high = max(primary.value, other.value)
    if difference <= allowance:
        verdict = "corroborated"
    elif difference <= CONFLICT_FRACTION:
        verdict = "conflict"
    else:
        verdict = "gross_conflict"
    return Corroboration(verdict, difference, gap_days, low, high, primary.source_name)
