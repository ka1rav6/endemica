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

*2. Recent-window fallback* — used when only one report exists **and** that
report states when the outbreak began. The cumulative count is multiplied by
the fraction of it that would still be infectious if cases had accumulated
evenly:

.. math::

    I \approx C \times \min\!\left(1, \frac{D}{A}\right) \times u

where :math:`A` is the number of days from the stated start to the report
date, floored at :math:`D`. If the report never states a start date, :math:`A`
is :data:`ASSUMED_OUTBREAK_AGE_DAYS` (90). That assumption is written into the
estimate. Treating every historical case as still infectious is not used.

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
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum

from endemica.core.errors import ModelInputError

# Default scenario range for the under-reporting multiplier u.
DEFAULT_UNDERREPORTING = (2.0, 4.0, 10.0)

# A report older than this is treated as not describing the present. 60 days
# is roughly the interval after which WHO has usually published a follow-up or
# the event has been closed; it is a project assumption, exposed as a setting.
DEFAULT_MAX_REPORT_AGE_DAYS = 60.0

# Used only when a report gives a cumulative total and does not say when the
# outbreak began. 90 days is the same window Endemica treats as an active
# outbreak. It is an assumption, and the estimate says so.
ASSUMED_OUTBREAK_AGE_DAYS = 90.0

# Two reports closer than this are a revision of the same total, not a rate.
# Differencing them divides a small count change by a fraction of a day.
MIN_INCIDENCE_GAP_DAYS = 1.0

# A report older than the default window can still be the only grounded series
# we have. Callers may opt into this longer ceiling rather than returning nothing.
STALE_REPORT_MAX_AGE_DAYS = 1825.0

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

    DEATH_DIFFERENCE = "death_difference"
    """Fallback: the change in deaths, converted by the series' own fatality ratio."""


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


@dataclass(frozen=True, slots=True)
class ReportedCount:
    """One grounded cumulative case count at a publication time.

    Attributes:
        published_at: When the report carrying this count was published.
        cases_confirmed: Cumulative confirmed cases. Only a count that survived
            grounding belongs here.
        outbreak_started_on: The day the source says the outbreak was declared
            or began. ``None`` when the text does not say.
        deaths: Cumulative deaths from the same report, when the source gives
            them. Used only when the case total is flat and the death total is
            not, which is how some sources report a long-running outbreak.
    """

    published_at: datetime
    cases_confirmed: int
    outbreak_started_on: date | None = None
    deaths: int | None = None


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
    if age_days < 0:
        return PrevalenceUnavailable(
            reason="report_after_as_of",
            detail=(
                "The later report was published after the time this estimate describes, "
                "so it is excluded."
            ),
        )
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
    if elapsed_days < MIN_INCIDENCE_GAP_DAYS:
        return PrevalenceUnavailable(
            reason="no_elapsed_time",
            detail=(
                "The two reports are less than a day apart, so the change between them "
                "is a revision rather than a daily incidence."
            ),
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
    outbreak's age :math:`A`. When the start date is unknown, :math:`A` is
    :data:`ASSUMED_OUTBREAK_AGE_DAYS` and the estimate says so.

    Args:
        cumulative_cases: Cumulative reported cases C, non-negative.
        report_date: Publication time of the report.
        population: Origin population N, positive.
        infectious_period_days: Mean infectious period D, positive.
        outbreak_age_days: Outbreak age A in days, from the stated start to the
            report date. ``None`` means the start was not stated, and
            :data:`ASSUMED_OUTBREAK_AGE_DAYS` is used.
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
    if age_days < 0:
        return PrevalenceUnavailable(
            reason="report_after_as_of",
            detail=(
                "The report was published after the time this estimate describes, "
                "so it is excluded."
            ),
        )
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

    assumed_age = False
    if outbreak_age_days is None:
        outbreak_age_days = ASSUMED_OUTBREAK_AGE_DAYS
        assumed_age = True
    if not math.isfinite(outbreak_age_days) or outbreak_age_days < 0:
        msg = f"outbreak_age_days must be finite and non-negative, got {outbreak_age_days!r}"
        raise ModelInputError(msg)

    # Floor the age at the infectious period: an outbreak younger than one
    # infectious period cannot have had cases recover, so the fraction is 1.
    effective_age = max(outbreak_age_days, infectious_period_days)
    active_fraction = min(1.0, infectious_period_days / effective_age)
    if assumed_age:
        age_caveat = (
            f"The report does not say when the outbreak began, so its age is assumed to be "
            f"{ASSUMED_OUTBREAK_AGE_DAYS:.0f} days, the active-outbreak window. "
            f"{active_fraction:.0%} of reported cases are treated as currently infectious."
        )
    else:
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


def prevalence_from_series(
    points: Sequence[ReportedCount],
    *,
    population: int,
    infectious_period_days: float,
    underreporting: tuple[float, float, float] = DEFAULT_UNDERREPORTING,
    as_of: datetime,
    max_report_age_days: float = DEFAULT_MAX_REPORT_AGE_DAYS,
) -> PrevalenceOutcome:
    """Estimate current prevalence from a time-ordered series of cumulative counts.

    Uses incidence differencing on the latest pair of reports separated in
    time. That result stands, including a refusal: a flat or revised-down
    series is evidence about current transmission, and the single-report
    formula must not replace it by treating the old cumulative total as still
    infectious. The single-report formula runs for one count. A stated start
    date supplies the outbreak age; otherwise the age is
    :data:`ASSUMED_OUTBREAK_AGE_DAYS`.

    Args:
        points: Grounded cumulative counts. Order does not matter.
        population: Origin population N, positive.
        infectious_period_days: Mean infectious period D, positive.
        underreporting: (low, central, high) multipliers, each >= 1.
        as_of: The time the estimate is being made.
        max_report_age_days: Reports older than this are not used.

    Returns:
        A prevalence estimate, or an explicit refusal.
    """
    if not points:
        return PrevalenceUnavailable(
            reason="no_reported_cases",
            detail="no grounded case count is available for this origin",
        )

    usable = [point for point in points if point.published_at <= as_of]
    if not usable:
        return PrevalenceUnavailable(
            reason="report_after_as_of",
            detail=(
                "Every report for this origin was published after the time this estimate describes."
            ),
        )

    ordered = sorted(usable, key=lambda point: point.published_at)
    later = ordered[-1]
    min_gap_seconds = MIN_INCIDENCE_GAP_DAYS * 86400.0
    earlier = next(
        (
            candidate
            for candidate in reversed(ordered[:-1])
            if (later.published_at - candidate.published_at).total_seconds() >= min_gap_seconds
        ),
        None,
    )
    if earlier is not None:
        outcome = estimate_from_incidence(
            earlier.cases_confirmed,
            earlier.published_at,
            later.cases_confirmed,
            later.published_at,
            population=population,
            infectious_period_days=infectious_period_days,
            underreporting=underreporting,
            as_of=as_of,
            max_report_age_days=max_report_age_days,
        )
        if isinstance(outcome, PrevalenceUnavailable) and outcome.reason == "no_new_cases":
            return _incidence_from_deaths(
                earlier,
                later,
                population=population,
                infectious_period_days=infectious_period_days,
                underreporting=underreporting,
                as_of=as_of,
                max_report_age_days=max_report_age_days,
                refusal=outcome,
            )
        return outcome

    age = _age_from_start(later.published_at, later.outbreak_started_on)
    return estimate_from_single_report(
        later.cases_confirmed,
        later.published_at,
        population=population,
        infectious_period_days=infectious_period_days,
        outbreak_age_days=age,
        underreporting=underreporting,
        as_of=as_of,
        max_report_age_days=max_report_age_days,
    )


def _incidence_from_deaths(
    earlier: ReportedCount,
    later: ReportedCount,
    *,
    population: int,
    infectious_period_days: float,
    underreporting: tuple[float, float, float],
    as_of: datetime,
    max_report_age_days: float,
    refusal: PrevalenceUnavailable,
) -> PrevalenceOutcome:
    """Recover incidence from the death toll when the case total did not move.

    Some sources keep a running death count current while restating the
    cumulative case figure only occasionally -- WHO's MERS bulletins do this,
    and Saudi Arabia's October 2026 report raised deaths from 946 to 965 while
    leaving the case total at the figure published seventeen months earlier.
    Read literally that is "no new cases", which is the one thing the deaths
    rule out.

    The conversion uses the case fatality ratio of this same series,
    ``deaths / cases`` at the later report, so no external constant enters and
    a source that is internally consistent stays internally consistent. The
    result is an estimate built on a ratio rather than a count, so it is
    returned with that stated in its caveats; where the ratio cannot be formed
    the original refusal stands.
    """
    if earlier.deaths is None or later.deaths is None:
        return refusal
    new_deaths = later.deaths - earlier.deaths
    if new_deaths <= 0:
        return refusal
    if later.cases_confirmed <= 0 or later.deaths <= 0:
        return refusal
    fatality_ratio = later.deaths / later.cases_confirmed
    if not 0.0 < fatality_ratio <= 1.0:
        return refusal
    implied_cases = new_deaths / fatality_ratio
    outcome = estimate_from_incidence(
        earlier.cases_confirmed,
        earlier.published_at,
        earlier.cases_confirmed + round(implied_cases),
        later.published_at,
        population=population,
        infectious_period_days=infectious_period_days,
        underreporting=underreporting,
        as_of=as_of,
        max_report_age_days=max_report_age_days,
    )
    if not isinstance(outcome, PrevalenceEstimate):
        return outcome
    return replace(
        outcome,
        method=PrevalenceMethod.DEATH_DIFFERENCE,
        caveats=(
            f"The case total did not move between {earlier.published_at.date()} and "
            f"{later.published_at.date()}, but deaths rose from {earlier.deaths} to "
            f"{later.deaths}. Incidence was recovered from those {new_deaths} deaths "
            f"using this series' own case fatality ratio of {fatality_ratio:.1%}, "
            f"implying about {round(implied_cases)} cases.",
            "A ratio applied to a death count is weaker evidence than a case count, "
            "and deaths lag infection, so this estimate is both less certain and "
            "later than a case-based one.",
            *outcome.caveats[1:],
        ),
    )


def _age_from_start(published_at: datetime, started_on: date | None) -> float | None:
    """Days from a stated outbreak start to the report date, or None."""
    if started_on is None:
        return None
    age = (published_at.date() - started_on).days
    if age < 0:
        return None
    return float(age)
