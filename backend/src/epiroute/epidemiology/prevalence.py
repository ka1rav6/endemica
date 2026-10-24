r"""Origin prevalence: turning reported case counts into :math:`I/N`.

**Question answered.** What fraction of an origin country's population is
currently infectious?

This is the single weakest link in the importation model, and the module is
written to make that visible rather than to hide it.

**The problem.** The importation model needs :math:`I/N`, the prevalence of
*currently infectious* people. WHO Disease Outbreak News publishes
**cumulative** case counts as of a report date. Cumulative counts and point
prevalence are different quantities, and no amount of arithmetic converts one
into the other without an assumption.

**Two estimators, in order of preference.**

*1. Incidence differencing* — used when two or more reports describe the same
pathogen and country at different dates. The difference in cumulative counts
over the elapsed time gives an incidence rate, and multiplying by the
infectious period gives a prevalence:

.. math::

    \text{incidence} = \frac{C_2 - C_1}{t_2 - t_1},
    \qquad I \approx \text{incidence} \times D \times u

where :math:`D` is the mean infectious period in days and :math:`u` the
under-reporting multiplier. This is the preferred path because it uses only
the *change* in reporting, which is far less sensitive to how complete the
cumulative total is.

*2. Recent-window fallback* — used when only one report exists. The stated
cumulative count is multiplied by the fraction of it assumed still infectious:

.. math::

    I \approx C \times \min\!\left(1, \frac{D}{A}\right) \times u

where :math:`A` is the outbreak's apparent age in days (report date minus the
earliest reporting date, floored at :math:`D`). The term
:math:`\min(1, D/A)` is a crude assumption that cases accumulated uniformly
over the outbreak's life; it is labelled as such and the resulting estimate
carries a warning.

**Staleness.** A report older than ``max_report_age_days`` yields
:class:`PrevalenceUnavailable`, not a decayed number. An outbreak that stopped
being reported on may have ended, and guessing is worse than saying so.

**Under-reporting band.** :math:`u` is a scenario parameter with no measured
value for a live outbreak. The default range 2x-10x spans the multipliers
commonly discussed for acute outbreak surveillance; it is an assumption the
user can change, and it is what makes the low/high band wide.

**Variables and units.**

===============  ===========================================================
Symbol           Meaning and unit
===============  ===========================================================
:math:`C`        Cumulative reported cases, persons.
:math:`N`        Population of the origin, persons.
:math:`D`        Mean infectious period, days (pathogen profile).
:math:`A`        Apparent outbreak age, days.
:math:`u`        Under-reporting multiplier, dimensionless, >= 1.
:math:`I/N`      Estimated infectious prevalence, dimensionless in [0, 1].
===============  ===========================================================
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from epiroute.core.errors import ModelInputError

# Default scenario range for the under-reporting multiplier u.
DEFAULT_UNDERREPORTING = (2.0, 4.0, 10.0)

# A report older than this is treated as not describing the present. 60 days
# is roughly the interval after which WHO has usually published a follow-up or
# the event has been closed; it is a project assumption, exposed as a setting.
DEFAULT_MAX_REPORT_AGE_DAYS = 60.0

# Hard ceiling on the estimated prevalence. An estimate above this is almost
# certainly a data error (a count mis-parsed by orders of magnitude, or a
# population mismatched to the wrong country), so it is clamped and flagged
# rather than allowed to drive the whole model.
MAX_PLAUSIBLE_PREVALENCE = 0.25


class PrevalenceMethod(StrEnum):
    """Which estimator produced a prevalence value."""

    INCIDENCE_DIFFERENCE = "incidence_difference"
    """Preferred: from the change in cumulative counts between two reports."""

    RECENT_WINDOW = "recent_window"
    """Fallback: a single cumulative count apportioned over the outbreak's age."""


@dataclass(frozen=True, slots=True)
class PrevalenceEstimate:
    """An estimated infectious prevalence with its band and provenance.

    Attributes:
        low: Prevalence at the low end of the under-reporting range.
        central: Prevalence at the central under-reporting multiplier.
        high: Prevalence at the high end.
        method: Which estimator was used.
        infectious_cases_central: Estimated infectious persons at the central
            multiplier, useful for display.
        reported_cases: The cumulative count the estimate started from.
        population: Denominator used.
        underreporting_range: The (low, central, high) multipliers applied.
        reference_date: The report date the estimate describes.
        caveats: Human-readable limitations specific to this estimate.
        clamped: True when the estimate hit :data:`MAX_PLAUSIBLE_PREVALENCE`.
    """

    low: float
    central: float
    high: float
    method: PrevalenceMethod
    infectious_cases_central: float
    reported_cases: int
    population: int
    underreporting_range: tuple[float, float, float]
    reference_date: datetime
    caveats: tuple[str, ...] = ()
    clamped: bool = False


@dataclass(frozen=True, slots=True)
class PrevalenceUnavailable:
    """Why a prevalence could not be estimated.

    Returned instead of a number so the caller can report "not estimable" with
    a reason, which is the behaviour AGENTS.md section 9.4 requires.

    Attributes:
        reason: Machine-readable reason code.
        detail: Human-readable explanation.
    """

    reason: str
    detail: str


PrevalenceOutcome = PrevalenceEstimate | PrevalenceUnavailable


def _validate_underreporting(band: tuple[float, float, float]) -> None:
    """Validate the under-reporting multiplier range."""
    low, central, high = band
    for name, value in (("low", low), ("central", central), ("high", high)):
        if not math.isfinite(value):
            msg = f"under-reporting {name} must be finite, got {value!r}"
            raise ModelInputError(msg)
        if value < 1.0:
            # u < 1 would mean more cases occurred than were reported in
            # reverse -- i.e. over-reporting -- which this model does not
            # represent.
            msg = f"under-reporting {name} must be at least 1.0, got {value!r}"
            raise ModelInputError(msg)
    if not low <= central <= high:
        msg = f"under-reporting range must be ordered, got {band!r}"
        raise ModelInputError(msg)


def _finalise(
    infectious_low: float,
    infectious_central: float,
    infectious_high: float,
    *,
    population: int,
    method: PrevalenceMethod,
    reported_cases: int,
    underreporting: tuple[float, float, float],
    reference_date: datetime,
    caveats: tuple[str, ...],
) -> PrevalenceEstimate:
    """Convert infectious-person counts into a clamped prevalence band."""
    raw = tuple(
        count / population for count in (infectious_low, infectious_central, infectious_high)
    )
    clamped = any(value > MAX_PLAUSIBLE_PREVALENCE for value in raw)
    low, central, high = (min(value, MAX_PLAUSIBLE_PREVALENCE) for value in raw)
    if clamped:
        caveats = (
            *caveats,
            f"Estimated prevalence exceeded the plausibility ceiling of "
            f"{MAX_PLAUSIBLE_PREVALENCE:.0%} and was clamped. Check the reported "
            f"case count and the population denominator.",
        )
    return PrevalenceEstimate(
        low=low,
        central=central,
        high=high,
        method=method,
        infectious_cases_central=infectious_central,
        reported_cases=reported_cases,
        population=population,
        underreporting_range=underreporting,
        reference_date=reference_date,
        caveats=caveats,
        clamped=clamped,
    )


def estimate_from_incidence(
    earlier_cumulative: int,
    earlier_date: datetime,
    later_cumulative: int,
    later_date: datetime,
    *,
    population: int,
    infectious_period_days: float,
    underreporting: tuple[float, float, float] = DEFAULT_UNDERREPORTING,
    as_of: datetime,
    max_report_age_days: float = DEFAULT_MAX_REPORT_AGE_DAYS,
) -> PrevalenceOutcome:
    r"""Estimate prevalence from the change in cumulative counts (preferred).

    Args:
        earlier_cumulative: Cumulative cases in the earlier report.
        earlier_date: Publication time of the earlier report.
        later_cumulative: Cumulative cases in the later report.
        later_date: Publication time of the later report.
        population: Origin population N, positive.
        infectious_period_days: Mean infectious period D, positive.
        underreporting: (low, central, high) multipliers, each >= 1.
        as_of: The time the estimate is being made, for staleness checks.
        max_report_age_days: Reports older than this are not used.

    Returns:
        A :class:`PrevalenceEstimate`, or :class:`PrevalenceUnavailable` when
        the inputs cannot support one (stale report, non-increasing counts,
        zero elapsed time).

    Raises:
        ModelInputError: If population, the infectious period or the
            under-reporting range is outside its documented domain.

    Example:
        An outbreak reporting 100 then 240 cumulative cases 14 days apart, in a
        population of 10 million, with a 7-day infectious period and u = 4:

        >>> from datetime import UTC, datetime
        >>> d1 = datetime(2026, 10, 1, tzinfo=UTC)
        >>> d2 = datetime(2026, 10, 15, tzinfo=UTC)
        >>> est = estimate_from_incidence(
        ...     100, d1, 240, d2,
        ...     population=10_000_000, infectious_period_days=7.0,
        ...     underreporting=(2.0, 4.0, 10.0),
        ...     as_of=datetime(2026, 10, 20, tzinfo=UTC),
        ... )
        >>> est.method.value
        'incidence_difference'
        >>> est.infectious_cases_central   # 10 cases/day * 7 days * 4
        280.0
        >>> round(est.central * 1e5, 2)    # per 100,000
        2.8
    """
    _validate_underreporting(underreporting)
    if population <= 0:
        msg = f"population must be positive, got {population!r}"
        raise ModelInputError(msg)
    if not math.isfinite(infectious_period_days) or infectious_period_days <= 0:
        msg = f"infectious_period_days must be positive and finite, got {infectious_period_days!r}"
        raise ModelInputError(msg)

    age_days = (as_of - later_date).total_seconds() / 86400.0
    if age_days > max_report_age_days:
        return PrevalenceUnavailable(
            reason="report_too_old",
            detail=(
                f"The most recent report for this origin is {age_days:.0f} days old "
                f"(limit {max_report_age_days:.0f}). The outbreak may have ended, so no "
                f"current prevalence is estimated."
            ),
        )

    elapsed_days = (later_date - earlier_date).total_seconds() / 86400.0
    if elapsed_days <= 0:
        return PrevalenceUnavailable(
            reason="no_elapsed_time",
            detail="The two reports share a publication time, so no incidence can be derived.",
        )

    new_cases = later_cumulative - earlier_cumulative
    if new_cases < 0:
        # Cumulative counts are routinely revised downwards after case
        # reclassification. That is a real event, but it carries no usable
        # incidence signal.
        return PrevalenceUnavailable(
            reason="counts_revised_downwards",
            detail=(
                f"Cumulative cases fell from {earlier_cumulative} to {later_cumulative}, "
                f"which indicates a reclassification rather than new transmission."
            ),
        )
    if new_cases == 0:
        return PrevalenceUnavailable(
            reason="no_new_cases",
            detail=(
                f"No new cases were reported between {earlier_date.date()} and "
                f"{later_date.date()}, so current transmission is not evidenced."
            ),
        )

    incidence_per_day = new_cases / elapsed_days
    base_infectious = incidence_per_day * infectious_period_days

    caveats = (
        f"Prevalence derived from {new_cases} new reported cases over "
        f"{elapsed_days:.0f} days, multiplied by a {infectious_period_days:.0f}-day "
        f"assumed infectious period.",
        "Reported cases are not infections. The under-reporting multiplier is a "
        "scenario assumption, not a measured correction.",
    )
    return _finalise(
        base_infectious * underreporting[0],
        base_infectious * underreporting[1],
        base_infectious * underreporting[2],
        population=population,
        method=PrevalenceMethod.INCIDENCE_DIFFERENCE,
        reported_cases=later_cumulative,
        underreporting=underreporting,
        reference_date=later_date,
        caveats=caveats,
    )


def estimate_from_single_report(
    cumulative_cases: int,
    report_date: datetime,
    *,
    population: int,
    infectious_period_days: float,
    outbreak_age_days: float | None = None,
    underreporting: tuple[float, float, float] = DEFAULT_UNDERREPORTING,
    as_of: datetime,
    max_report_age_days: float = DEFAULT_MAX_REPORT_AGE_DAYS,
) -> PrevalenceOutcome:
    r"""Estimate prevalence from one cumulative count (fallback).

    Applies :math:`I = C \times \min(1, D/A) \times u`. The
    :math:`\min(1, D/A)` factor assumes cases accumulated uniformly over the
    outbreak's apparent age :math:`A`; when the age is unknown it defaults to
    the infectious period, which makes the factor 1 and treats every reported
    case as currently infectious. That is the most pessimistic reading and is
    flagged as such.

    Args:
        cumulative_cases: Cumulative reported cases C, non-negative.
        report_date: Publication time of the report.
        population: Origin population N, positive.
        infectious_period_days: Mean infectious period D, positive.
        outbreak_age_days: Apparent outbreak age A in days. ``None`` means
            unknown.
        underreporting: (low, central, high) multipliers, each >= 1.
        as_of: The time the estimate is being made.
        max_report_age_days: Reports older than this are not used.

    Returns:
        A :class:`PrevalenceEstimate`, or :class:`PrevalenceUnavailable`.

    Raises:
        ModelInputError: If an input is outside its documented domain.

    Example:
        >>> from datetime import UTC, datetime
        >>> est = estimate_from_single_report(
        ...     1000, datetime(2026, 10, 20, tzinfo=UTC),
        ...     population=10_000_000, infectious_period_days=7.0,
        ...     outbreak_age_days=70.0, underreporting=(2.0, 4.0, 10.0),
        ...     as_of=datetime(2026, 10, 24, tzinfo=UTC),
        ... )
        >>> est.infectious_cases_central   # 1000 * (7/70) * 4
        400.0
    """
    _validate_underreporting(underreporting)
    if population <= 0:
        msg = f"population must be positive, got {population!r}"
        raise ModelInputError(msg)
    if cumulative_cases < 0:
        msg = f"cumulative_cases must be non-negative, got {cumulative_cases!r}"
        raise ModelInputError(msg)
    if not math.isfinite(infectious_period_days) or infectious_period_days <= 0:
        msg = f"infectious_period_days must be positive and finite, got {infectious_period_days!r}"
        raise ModelInputError(msg)

    age_days = (as_of - report_date).total_seconds() / 86400.0
    if age_days > max_report_age_days:
        return PrevalenceUnavailable(
            reason="report_too_old",
            detail=(
                f"The only report for this origin is {age_days:.0f} days old "
                f"(limit {max_report_age_days:.0f}), so no current prevalence is estimated."
            ),
        )
    if cumulative_cases == 0:
        return PrevalenceUnavailable(
            reason="no_reported_cases",
            detail="The report names this country but states no case count.",
        )

    if outbreak_age_days is None:
        active_fraction = 1.0
        age_caveat = (
            "The outbreak's start date is unknown, so every reported case is treated as "
            "currently infectious. This is the most pessimistic reading available."
        )
    else:
        # Floor the age at the infectious period: an outbreak younger than one
        # infectious period cannot have had cases recover, so the fraction is 1.
        effective_age = max(outbreak_age_days, infectious_period_days)
        active_fraction = min(1.0, infectious_period_days / effective_age)
        age_caveat = (
            f"Assumes cases accumulated uniformly over the outbreak's {effective_age:.0f}-day "
            f"apparent age, so {active_fraction:.0%} of reported cases are treated as "
            f"currently infectious."
        )

    base_infectious = cumulative_cases * active_fraction
    caveats = (
        "Only one report is available for this origin, so prevalence could not be "
        "derived from the change in counts. This estimate is weaker than the "
        "incidence-difference method.",
        age_caveat,
        "Reported cases are not infections. The under-reporting multiplier is a "
        "scenario assumption, not a measured correction.",
    )
    return _finalise(
        base_infectious * underreporting[0],
        base_infectious * underreporting[1],
        base_infectious * underreporting[2],
        population=population,
        method=PrevalenceMethod.RECENT_WINDOW,
        reported_cases=cumulative_cases,
        underreporting=underreporting,
        reference_date=report_date,
        caveats=caveats,
    )
