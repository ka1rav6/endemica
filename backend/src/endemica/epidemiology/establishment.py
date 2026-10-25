r"""Local establishment risk: given an introduction, will transmission sustain?

**Question answered.** Given that one infected person arrives, what is the
probability that sustained local transmission develops rather than the chain
dying out?

**Model.** Each introduction starts a branching process. The number of
secondary cases per infectious individual is negative-binomially distributed
with mean :math:`R` and dispersion :math:`k` — the parameterisation
Lloyd-Smith et al. (Nature 2005) introduced to capture superspreading. Its
probability generating function is

.. math::

    g(s) = \left(1 + \frac{R}{k}(1 - s)\right)^{-k}

The extinction probability :math:`q` is the smallest root in :math:`[0, 1]` of
the fixed-point equation :math:`q = g(q)`, that is

.. math::

    q = \left(1 + \frac{R(1-q)}{k}\right)^{-k}

and the probability that a single introduction establishes is :math:`1 - q`.

**Subcritical case.** For :math:`R \le 1` extinction is certain, so
:math:`q = 1` and the establishment probability is exactly 0. This is returned
as a value, not an error: "cannot sustain transmission" is a result.

**Over a time horizon.** Introductions arrive as a Poisson process with rate
:math:`\lambda` and each independently establishes with probability
:math:`1-q`. By Poisson thinning the establishing introductions are themselves
Poisson with rate :math:`\lambda(1-q)`, so

.. math::

    P(\text{establishment within } T) = 1 - e^{-\lambda T (1 - q)}

**Variables and units.**

===============  ===========================================================
Symbol           Meaning and unit
===============  ===========================================================
:math:`R`        Reproduction number in the destination: mean secondary cases
                 per case, dimensionless, non-negative.
:math:`k`        Negative-binomial dispersion, dimensionless, positive.
                 Small *k* means most transmission comes from few people, so
                 most chains die out. COVID-19 estimates near 0.1.
:math:`q`        Probability a single introduction's chain goes extinct.
:math:`\lambda`  Infected arrivals per day, from the importation model.
:math:`T`        Horizon in days.
===============  ===========================================================

**Numerical method.** Bisection on :math:`f(q) = g(q) - q` over
:math:`[0, 1)`.

Why not fixed-point iteration, the obvious choice? Because :math:`g` is
increasing and convex, iterating from :math:`q_0 = 0` does converge to the
smallest root, but its convergence rate is :math:`g'(q^\*)`, which approaches
1 as :math:`R \to 1^+`. Just above criticality it needs far more than any
sane iteration cap, and truncating it there would report a *wrong*
establishment probability for exactly the marginal cases that matter most.

Bisection is correct here because :math:`f` is strictly decreasing on
:math:`[0, q^\*]`: on that interval :math:`g'(q) \le g'(q^\*) < 1`, so
:math:`f' = g' - 1 < 0`. Since :math:`f(0) = g(0) > 0` for
:math:`R > 1` and :math:`f` is positive only on :math:`[0, q^\*)`, bracketing
on the sign of :math:`f` converges to the smallest root in a fixed number of
steps regardless of how close :math:`R` is to 1.

The implementation is verified against three independent results: the closed
form :math:`q = 1/R` at :math:`k = 1` (geometric offspring), the Poisson limit
:math:`q = e^{-R(1-q)}` as :math:`k \to \infty`, and an
independently-written bisection in the test suite.

*Precision note.* For :math:`R` extremely close to 1 the quantity
:math:`1 - q` is itself near zero, and bisection resolves it to about
:math:`10^{-16}` absolute. The relative precision of a very small
establishment probability is therefore limited, which is reported through
``iterations`` rather than hidden.

**Assumptions, and when they fail.**

1. *Homogeneous, unlimited susceptibles.* The branching process ignores
   depletion of susceptibles, which is correct only for the first few
   generations. It answers "does this chain take off", not "how large does the
   epidemic become".
2. *R and k are properties of the destination.* Both are taken from the
   pathogen profile and are not adjusted for local contact patterns, season,
   immunity or healthcare capacity.
3. *Vector-borne pathogens are not covered by R alone.* Whether a Zika-like
   introduction establishes is decided by local mosquito presence and climate.
   The profile for such pathogens therefore declares establishment
   ``not estimable`` rather than supplying an R, so no number is published
   that the model cannot support.
4. *Each introduction is independent.* Co-travelling cases that seed the same
   household are not independent chains.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from endemica.core.errors import ModelInputError

# Bisection settings. 200 halvings is far more than the ~60 needed to reduce
# the bracket to adjacent doubles, so the cap is a safety net, not the exit
# condition.
_MAX_ITERATIONS = 200

# The upper bracket cannot be exactly 1.0, because f(1) = 0 is the trivial root
# and including it would let bisection converge there.
_UPPER_BRACKET = 1.0 - 1e-16

# Above this value of k the negative binomial is numerically indistinguishable
# from Poisson, and (1 + R(1-q)/k)^(-k) starts losing precision. Switching to
# the Poisson generating function is both faster and more accurate.
_POISSON_LIMIT_K = 1e6


@dataclass(frozen=True, slots=True)
class EstablishmentResult:
    """Outcome of solving the branching-process equation.

    Attributes:
        extinction_probability: q, the probability one introduction dies out.
        establishment_probability: 1 - q, per single introduction.
        iterations: Bisection steps used. 0 for the closed-form subcritical
            case.
        subcritical: True when R <= 1, where extinction is certain.
    """

    extinction_probability: float
    establishment_probability: float
    iterations: int
    subcritical: bool


def _validate_parameters(reproduction_number: float, dispersion_k: float) -> None:
    """Validate R and k against their documented domains."""
    if not math.isfinite(reproduction_number):
        msg = f"reproduction_number must be finite, got {reproduction_number!r}"
        raise ModelInputError(msg)
    if reproduction_number < 0:
        msg = f"reproduction_number must be non-negative, got {reproduction_number!r}"
        raise ModelInputError(msg)
    if not math.isfinite(dispersion_k):
        msg = f"dispersion_k must be finite, got {dispersion_k!r}"
        raise ModelInputError(msg)
    if dispersion_k <= 0:
        # k = 0 is not a limiting case of the negative binomial that this
        # equation can represent; it has no finite mean-variance form here.
        msg = f"dispersion_k must be strictly positive, got {dispersion_k!r}"
        raise ModelInputError(msg)


def _offspring_pgf(s: float, reproduction_number: float, dispersion_k: float) -> float:
    r"""Evaluate the offspring probability generating function g(s).

    Uses the Poisson form for very large k, where the negative-binomial
    expression ``(1 + R(1-s)/k) ** -k`` would lose precision.
    """
    if dispersion_k >= _POISSON_LIMIT_K:
        return math.exp(-reproduction_number * (1.0 - s))
    return float((1.0 + reproduction_number * (1.0 - s) / dispersion_k) ** (-dispersion_k))


def solve_establishment(
    reproduction_number: float,
    dispersion_k: float,
) -> EstablishmentResult:
    r"""Solve :math:`q = g(q)` for the extinction probability.

    Args:
        reproduction_number: R, the mean number of secondary cases.
            Non-negative.
        dispersion_k: k, the negative-binomial dispersion. Strictly positive.
            Smaller values mean more overdispersed transmission.

    Returns:
        An :class:`EstablishmentResult`. For ``R <= 1`` the extinction
        probability is exactly 1 and the establishment probability exactly 0.

    Raises:
        ModelInputError: If R is negative or non-finite, or if k is
            non-positive or non-finite.

    Example:
        COVID-like overdispersion. Most introductions die out even though R is
        well above 1:

        >>> result = solve_establishment(2.5, 0.1)
        >>> round(result.establishment_probability, 4)
        0.1393

        The same R with Poisson-like transmission is far more dangerous per
        introduction, which is the whole point of tracking k:

        >>> round(solve_establishment(2.5, 1e9).establishment_probability, 3)
        0.893

        Subcritical transmission cannot establish:

        >>> solve_establishment(0.9, 0.5).establishment_probability
        0.0
    """
    _validate_parameters(reproduction_number, dispersion_k)

    # R <= 1: the only root of q = g(q) in [0, 1] is q = 1. Returning the
    # closed-form answer avoids iterating towards 1 from below, which
    # converges slowly and would report a spurious non-zero establishment
    # probability if it were truncated.
    if reproduction_number <= 1.0:
        return EstablishmentResult(
            extinction_probability=1.0,
            establishment_probability=0.0,
            iterations=0,
            subcritical=True,
        )

    # Bisection on f(q) = g(q) - q. f is strictly decreasing on [0, q*] and
    # positive only there, so bracketing on sign(f) converges to the smallest
    # root -- the epidemiologically meaningful one -- in a bounded number of
    # steps even when R is barely above 1.
    def f(q: float) -> float:
        return _offspring_pgf(q, reproduction_number, dispersion_k) - q

    low, high = 0.0, _UPPER_BRACKET
    steps = 0
    for _ in range(_MAX_ITERATIONS):
        mid = 0.5 * (low + high)
        # Converged when the bracket is two adjacent doubles: the midpoint then
        # equals one endpoint and no further halving is representable. This is
        # a scale-free stopping rule, which a fixed absolute tolerance is not
        # when q sits near 1.
        if mid in (low, high):
            break
        if f(mid) > 0.0:
            low = mid
        else:
            high = mid
        steps += 1
    q = 0.5 * (low + high)

    # Clamp against float drift: the mathematical result is in [0, 1] and a
    # value like 1.0000000000000002 would fail the API's probability bound.
    q = min(max(q, 0.0), 1.0)
    return EstablishmentResult(
        extinction_probability=q,
        establishment_probability=1.0 - q,
        iterations=steps,
        subcritical=False,
    )


def probability_of_establishment_within(
    arrival_rate_per_day: float,
    horizon_days: float,
    reproduction_number: float,
    dispersion_k: float,
) -> float:
    r"""Return P(sustained local transmission begins within ``horizon_days``).

    Combines the importation rate with the per-introduction establishment
    probability by Poisson thinning:
    :math:`1 - e^{-\lambda T (1-q)}`.

    Args:
        arrival_rate_per_day: lambda, infected arrivals per day, non-negative.
        horizon_days: T in days, non-negative.
        reproduction_number: R in the destination.
        dispersion_k: k in the destination.

    Returns:
        A probability in [0, 1]. Exactly 0 when no arrivals are expected, when
        the horizon is zero, or when R <= 1.

    Raises:
        ModelInputError: If any input is outside its documented domain.

    Example:
        >>> round(probability_of_establishment_within(0.5, 14.0, 2.5, 0.1), 4)
        0.6229
        >>> probability_of_establishment_within(0.5, 14.0, 0.8, 0.1)
        0.0
    """
    for name, value in (
        ("arrival_rate_per_day", arrival_rate_per_day),
        ("horizon_days", horizon_days),
    ):
        if not math.isfinite(value):
            msg = f"{name} must be finite, got {value!r}"
            raise ModelInputError(msg)
        if value < 0:
            msg = f"{name} must be non-negative, got {value!r}"
            raise ModelInputError(msg)

    result = solve_establishment(reproduction_number, dispersion_k)
    if result.establishment_probability == 0.0:
        return 0.0

    exponent = arrival_rate_per_day * horizon_days * result.establishment_probability
    if exponent == 0.0:
        return 0.0
    return -math.expm1(-exponent)


def days_to_establishment_threshold(
    arrival_rate_per_day: float,
    threshold: float,
    reproduction_number: float,
    dispersion_k: float,
    *,
    max_days: float = 365.0,
) -> float | None:
    r"""First day on which establishment probability reaches ``threshold``.

    Inverts :math:`1 - e^{-\lambda t (1-q)} = p`.

    Args:
        arrival_rate_per_day: lambda, infected arrivals per day.
        threshold: Target probability, strictly in (0, 1).
        reproduction_number: R in the destination.
        dispersion_k: k in the destination.
        max_days: Beyond this, report ``None`` rather than a distant date.

    Returns:
        The day number, or ``None`` when the threshold is unreachable because
        the rate is zero, R <= 1, or the horizon exceeds ``max_days``.

    Raises:
        ModelInputError: If an input is outside its documented domain.
    """
    if not math.isfinite(threshold) or not 0.0 < threshold < 1.0:
        msg = f"threshold must lie strictly in (0, 1), got {threshold!r}"
        raise ModelInputError(msg)
    if not math.isfinite(arrival_rate_per_day) or arrival_rate_per_day < 0:
        msg = f"arrival_rate_per_day must be finite and non-negative, got {arrival_rate_per_day!r}"
        raise ModelInputError(msg)

    result = solve_establishment(reproduction_number, dispersion_k)
    effective_rate = arrival_rate_per_day * result.establishment_probability
    if effective_rate <= 0.0:
        return None

    days = -math.log1p(-threshold) / effective_rate
    rounded = math.ceil(days)
    return None if rounded > max_days else float(rounded)
