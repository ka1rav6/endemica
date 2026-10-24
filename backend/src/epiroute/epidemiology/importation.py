r"""Importation risk: will an infected traveller arrive?

**Question answered.** What is the probability that at least one infected
traveller arrives at a destination within a time horizon of :math:`T` days?

**Model.** Arrivals of infected travellers are treated as a Poisson process
with a constant rate. For destination :math:`n`, summing over origins
:math:`m`:

.. math::

    \lambda_n = \sum_m \frac{I_m}{N_m} \, F_{mn} \, \alpha_m \, (1 - \sigma_{mn})

.. math::

    P(\text{at least one arrival within } T) = 1 - e^{-\lambda_n T}

**Variables and units.**

================  ==========================================================
Symbol            Meaning and unit
================  ==========================================================
:math:`I_m/N_m`   Estimated prevalence of currently-infectious people at
                  origin *m*. Dimensionless fraction in [0, 1]. Produced by
                  :mod:`epiroute.epidemiology.prevalence`.
:math:`F_{mn}`    Passenger flow from *m* to *n*, **passengers per day**.
                  Observed where a statistical agency publishes it, otherwise
                  estimated by the gravity model and labelled as such.
:math:`\alpha_m`  Probability that an infectious person boards a flight,
                  relative to a randomly chosen traveller. Dimensionless in
                  [0, 1]. From the pathogen profile.
:math:`\sigma_{mn}` Effectiveness of screening and border measures on the
                  route, dimensionless in [0, 0.9]. 0 means no confirmed
                  measure, which is the default.
:math:`\lambda_n` Expected infected arrivals per day at *n*.
:math:`T`         Horizon in days.
================  ==========================================================

**Assumptions, and when they fail.**

1. *Constant rate over the horizon.* Prevalence is held at its current
   estimate and schedules are held at this period's values. For a horizon
   comparable to the epidemic doubling time this understates risk; the
   scenario module exists to explore that explicitly rather than hiding it
   inside the central estimate.
2. *Independence between travellers.* Treating arrivals as Poisson assumes
   infected travellers arrive independently. Family groups and tour parties
   violate this; the effect is to make the true distribution of arrivals
   more clustered than Poisson, so :math:`P(\ge 1)` from this model is
   biased slightly high for a given mean.
3. *Origin prevalence applies to departing travellers.* The term
   :math:`(I/N)\alpha` assumes the infectious prevalence among people
   boarding a flight equals the general population prevalence scaled by
   :math:`\alpha`. Outbreaks concentrated far from an international airport
   break this, which is exactly the Ebola case the research note flags.
4. *Direct flows only.* :math:`F_{mn}` as used here is the flow attributed to
   the origin-destination pair. Where the flow table includes hub
   itineraries that is captured; where it does not, transit passengers are
   missing and risk is understated. The value's ``source`` field says which.

**Missing data.** A missing prevalence or a missing flow contributes nothing
to the sum *and is reported*: :func:`importation_rate` returns the list of
origins it could not use, so the caller can answer "not estimable" rather
than silently returning a smaller number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from epiroute.core.errors import ModelInputError

# Upper bound on screening effectiveness. The research note describes sigma as
# running "from 0 to about 0.9": no border measure is perfect, and allowing
# sigma = 1 would let a scenario drive importation risk to exactly zero, which
# would be a stronger claim than any evidence supports.
MAX_SIGMA = 0.9

# Above this exponent, 1 - exp(-x) is 1.0 in float64. Used to report
# saturation honestly instead of printing "100.0%" as if it were precise.
_SATURATION_EXPONENT = 37.0


@dataclass(frozen=True, slots=True)
class OriginContribution:
    """One origin's contribution to a destination's arrival rate.

    Attributes:
        origin_iso3: ISO-3166-1 alpha-3 code of the origin country.
        prevalence: Estimated infectious prevalence I/N, dimensionless.
        passengers_per_day: Passenger flow F from origin to destination.
        alpha: Relative probability of boarding while infectious.
        sigma: Screening effectiveness on this route, in [0, MAX_SIGMA].
        rate_per_day: The product, in expected infected arrivals per day.
    """

    origin_iso3: str
    prevalence: float
    passengers_per_day: float
    alpha: float
    sigma: float
    rate_per_day: float


@dataclass(frozen=True, slots=True)
class ImportationRate:
    """The assembled arrival rate for one destination.

    Attributes:
        rate_per_day: lambda_n, expected infected arrivals per day.
        contributions: Per-origin breakdown, descending by rate.
        excluded_origins: Origins that had an outbreak signal but could not be
            used, as ``(iso3, reason)`` pairs. Never silently dropped.
    """

    rate_per_day: float
    contributions: tuple[OriginContribution, ...] = ()
    excluded_origins: tuple[tuple[str, str], ...] = field(default=())

    @property
    def usable_origin_count(self) -> int:
        """Number of origins that contributed a non-zero rate."""
        return sum(1 for c in self.contributions if c.rate_per_day > 0)


def _validate_unit_interval(name: str, value: float, *, upper: float = 1.0) -> float:
    """Validate that ``value`` is finite and within ``[0, upper]``."""
    if not math.isfinite(value):
        msg = f"{name} must be finite, got {value!r}"
        raise ModelInputError(msg)
    if not 0.0 <= value <= upper:
        msg = f"{name} must lie in [0, {upper}], got {value!r}"
        raise ModelInputError(msg)
    return value


def arrival_rate_from_origin(
    prevalence: float,
    passengers_per_day: float,
    alpha: float,
    sigma: float = 0.0,
) -> float:
    r"""Return one origin's expected infected arrivals per day.

    Computes :math:`(I/N) \cdot F \cdot \alpha \cdot (1 - \sigma)`.

    Args:
        prevalence: Infectious prevalence I/N at the origin, in [0, 1].
        passengers_per_day: Passenger flow F, non-negative.
        alpha: Relative boarding probability while infectious, in [0, 1].
        sigma: Screening effectiveness, in [0, :data:`MAX_SIGMA`].

    Returns:
        Expected infected arrivals per day from this origin.

    Raises:
        ModelInputError: If any input is non-finite, negative, or outside its
            documented range.

    Example:
        The research note's illustrative case: 10 cases per 100,000 at the
        origin, 50 passengers a day on one direct route, alpha = 0.5, no
        screening.

        >>> round(arrival_rate_from_origin(1e-4, 50.0, 0.5), 6)
        0.0025
    """
    _validate_unit_interval("prevalence", prevalence)
    _validate_unit_interval("alpha", alpha)
    _validate_unit_interval("sigma", sigma, upper=MAX_SIGMA)
    if not math.isfinite(passengers_per_day):
        msg = f"passengers_per_day must be finite, got {passengers_per_day!r}"
        raise ModelInputError(msg)
    if passengers_per_day < 0:
        msg = f"passengers_per_day must be non-negative, got {passengers_per_day!r}"
        raise ModelInputError(msg)

    return prevalence * passengers_per_day * alpha * (1.0 - sigma)


def importation_rate(contributions: list[OriginContribution]) -> ImportationRate:
    """Sum per-origin rates into a destination's arrival rate.

    Args:
        contributions: Per-origin contributions, already validated by
            :func:`arrival_rate_from_origin`.

    Returns:
        An :class:`ImportationRate` with the total and a breakdown sorted by
        descending contribution, so the UI can show the dominant routes.
    """
    ordered = tuple(sorted(contributions, key=lambda c: c.rate_per_day, reverse=True))
    return ImportationRate(
        rate_per_day=math.fsum(c.rate_per_day for c in ordered),
        contributions=ordered,
    )


def probability_at_least_one_arrival(rate_per_day: float, horizon_days: float) -> float:
    r"""Return :math:`P(\text{at least one infected arrival within } T)`.

    Computes :math:`1 - e^{-\lambda T}` under a constant-rate Poisson
    assumption.

    Args:
        rate_per_day: Expected infected arrivals per day, non-negative.
        horizon_days: Horizon T in days, non-negative.

    Returns:
        A probability in [0, 1]. Exactly 0 when either argument is 0.

    Raises:
        ModelInputError: If either argument is negative or non-finite.

    Example:
        >>> round(probability_at_least_one_arrival(0.0025, 14.0), 4)
        0.0344
        >>> probability_at_least_one_arrival(0.0, 14.0)
        0.0
        >>> probability_at_least_one_arrival(5.0, 0.0)
        0.0
    """
    for name, value in (("rate_per_day", rate_per_day), ("horizon_days", horizon_days)):
        if not math.isfinite(value):
            msg = f"{name} must be finite, got {value!r}"
            raise ModelInputError(msg)
        if value < 0:
            msg = f"{name} must be non-negative, got {value!r}"
            raise ModelInputError(msg)

    exponent = rate_per_day * horizon_days
    if exponent == 0.0:
        return 0.0
    # expm1 keeps precision for small exponents, where the naive
    # 1 - exp(-x) form loses most of its significant digits.
    return -math.expm1(-exponent)


def is_saturated(rate_per_day: float, horizon_days: float) -> bool:
    """Whether the probability is indistinguishable from 1 in float64.

    The UI uses this to render "> 99.99%" rather than an exact-looking
    "100.0%", which would overstate the precision of the inputs.
    """
    return rate_per_day * horizon_days > _SATURATION_EXPONENT


def days_to_probability_threshold(
    rate_per_day: float, threshold: float, *, max_days: float = 365.0
) -> float | None:
    r"""Return the first day on which cumulative arrival probability reaches ``threshold``.

    Inverting :math:`1 - e^{-\lambda t} = p` gives
    :math:`t = -\ln(1-p)/\lambda`. The result is rounded **up** to a whole
    day, because the marker is presented as a day number.

    Args:
        rate_per_day: Expected infected arrivals per day. Must be positive for
            a finite answer.
        threshold: Target probability, in (0, 1).
        max_days: Horizon beyond which the answer is reported as ``None``
            rather than an implausibly distant date.

    Returns:
        The day number, or ``None`` when the rate is zero or the threshold is
        not reached within ``max_days``.

    Raises:
        ModelInputError: If ``threshold`` is outside (0, 1) or ``rate_per_day``
            is negative or non-finite.
    """
    if not math.isfinite(threshold) or not 0.0 < threshold < 1.0:
        msg = f"threshold must lie strictly in (0, 1), got {threshold!r}"
        raise ModelInputError(msg)
    if not math.isfinite(rate_per_day) or rate_per_day < 0:
        msg = f"rate_per_day must be finite and non-negative, got {rate_per_day!r}"
        raise ModelInputError(msg)
    if rate_per_day == 0.0:
        return None

    days = -math.log1p(-threshold) / rate_per_day
    rounded = math.ceil(days)
    return None if rounded > max_days else float(rounded)
