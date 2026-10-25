r"""Per-pathogen parameter profiles.

A profile supplies the parameters the models cannot derive from the data:
:math:`\\alpha` (probability of boarding while infectious, relative to a
random traveller), :math:`R` and :math:`k`, and the infectious period used to
turn a cumulative case count into a prevalence estimate.

**These are documented assumptions, not measurements.** Every numeric value
carries a ``basis`` string naming where it comes from, and every profile
declares a ``confidence`` level. A value whose basis is
``ParameterBasis.PROJECT_ASSUMPTION`` has no literature citation behind it and
is surfaced in the UI as an assumption the user can change — it is not
presented as a published estimate.

The ranges are deliberately wide. They drive the low/central/high *scenario*
band, which is not a confidence interval: it is the model re-run at the ends of
its assumed inputs (AGENTS.md section 10.2).

Where a pathogen's establishment is not governed by :math:`R` in a way this
model can represent — vector-borne transmission being the clear case — the
profile sets ``establishment_estimable = False`` and the API answers "not
estimable" rather than publishing a number the model cannot support.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from endemica.core.errors import ModelInputError


class ParameterBasis(StrEnum):
    """Where a parameter value comes from.

    Shown in the UI next to the value, so a reader can tell a cited estimate
    from an engineering assumption.
    """

    LITERATURE = "literature"
    """Taken from a named publication, cited in the profile's ``references``."""

    DERIVED_FROM_LITERATURE = "derived_from_literature"
    """Computed from cited quantities by a documented step."""

    PROJECT_ASSUMPTION = "project_assumption"
    """Endemica's own working assumption. No citation exists. Treat as a dial."""


class Confidence(StrEnum):
    """How well-characterised a profile's parameters are."""

    MODERATE = "moderate"
    """Several independent published estimates agree on the order of magnitude."""

    LOW = "low"
    """Few estimates, wide disagreement, or heavy dependence on context."""

    INDICATIVE_ONLY = "indicative_only"
    """Values are placeholders for exploring the model, not for interpretation."""


@dataclass(frozen=True, slots=True)
class ParameterRange:
    """A low/central/high range for one model parameter.

    Attributes:
        low: Lower end of the scenario range.
        central: Default value used for the central estimate.
        high: Upper end of the scenario range.
        basis: Where these numbers come from.
        note: Short explanation shown in the UI.
    """

    low: float
    central: float
    high: float
    basis: ParameterBasis
    note: str = ""

    def __post_init__(self) -> None:
        """Validate ordering, since a misordered range would invert the band."""
        if not self.low <= self.central <= self.high:
            msg = (
                f"parameter range must satisfy low <= central <= high, got "
                f"({self.low}, {self.central}, {self.high})"
            )
            raise ModelInputError(msg)


@dataclass(frozen=True, slots=True)
class PathogenProfile:
    """Model parameters and provenance for one pathogen or pathogen class.

    Attributes:
        key: Stable identifier used in the API.
        label: Human-readable name.
        description: One sentence on what this profile represents.
        alpha: Probability of boarding a flight while infectious, relative to
            a randomly chosen traveller.
        reproduction_number: R in a destination with no specific information.
        dispersion_k: Negative-binomial dispersion k.
        infectious_period_days: Mean duration of infectiousness, used to
            convert incidence into a point prevalence.
        incubation_period_days: Mean latent period. Used only by the scenario
            markers, never by the importation model.
        establishment_estimable: False when R and k cannot represent this
            pathogen's establishment (vector-borne transmission).
        establishment_note: Why establishment is or is not estimable.
        confidence: Overall confidence in the profile's values.
        references: Citations supporting the literature-based parameters.
        aliases: Lowercase substrings matched against a report's disease label.
    """

    key: str
    label: str
    description: str
    alpha: ParameterRange
    reproduction_number: ParameterRange
    dispersion_k: ParameterRange
    infectious_period_days: float
    incubation_period_days: float
    establishment_estimable: bool
    establishment_note: str
    confidence: Confidence
    references: tuple[str, ...]
    aliases: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Profile definitions
#
# Each profile below states, per parameter, whether the value is cited or is
# Endemica's assumption. The research briefing note gives qualitative guidance
# ("high for early COVID-19 and Zika, very low for Ebola") rather than numbers
# for alpha, so every alpha here is a PROJECT_ASSUMPTION calibrated to that
# ordering. R and k for COVID-19 are the one case with widely replicated
# published values.
# ---------------------------------------------------------------------------

_PROFILES: Final[tuple[PathogenProfile, ...]] = (
    PathogenProfile(
        key="respiratory_default",
        label="Respiratory pathogen (default)",
        description=(
            "Generic directly-transmitted respiratory pathogen with substantial "
            "pre-symptomatic transmission, parameterised on early COVID-19."
        ),
        alpha=ParameterRange(
            low=0.2,
            central=0.5,
            high=0.8,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note=(
                "The research note's illustrative chart uses alpha = 0.5 "
                "('infected people board at half the rate of everyone else'). "
                "The range spans heavy self-isolation to none."
            ),
        ),
        reproduction_number=ParameterRange(
            low=1.2,
            central=2.0,
            high=3.0,
            basis=ParameterBasis.LITERATURE,
            note="Spans commonly reported basic reproduction numbers for early COVID-19.",
        ),
        dispersion_k=ParameterRange(
            low=0.1,
            central=0.3,
            high=0.5,
            basis=ParameterBasis.LITERATURE,
            note=(
                "Low k reflects the superspreading-dominated transmission "
                "documented for SARS-CoV-2; the research note cites k near 0.1."
            ),
        ),
        infectious_period_days=7.0,
        incubation_period_days=5.0,
        establishment_estimable=True,
        establishment_note="Branching process on R and k applies to direct human transmission.",
        confidence=Confidence.MODERATE,
        references=(
            "Lloyd-Smith JO, Schreiber SJ, Kopp PE, Getz WM. Superspreading and the effect "
            "of individual variation on disease emergence. Nature 2005;438:355-359.",
            "Briefing note: How disease-spread probabilities get their data, 14 Oct 2026.",
        ),
        aliases=(
            "respiratory syndrome",
            "pneumonia",
            "diphtheria",
            "pertussis",
        ),
    ),
    PathogenProfile(
        key="covid_19",
        label="COVID-19",
        description="SARS-CoV-2, parameterised on early-pandemic community transmission.",
        alpha=ParameterRange(
            low=0.2,
            central=0.5,
            high=0.8,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note="Same boarding range as the generic respiratory profile. Not measured.",
        ),
        reproduction_number=ParameterRange(
            low=1.2,
            central=2.5,
            high=3.5,
            basis=ParameterBasis.LITERATURE,
            note="Early-pandemic SARS-CoV-2 reproduction numbers, before widespread immunity.",
        ),
        dispersion_k=ParameterRange(
            low=0.05,
            central=0.1,
            high=0.5,
            basis=ParameterBasis.LITERATURE,
            note="Superspreading dispersion for SARS-CoV-2; the research note cites k near 0.1.",
        ),
        infectious_period_days=7.0,
        incubation_period_days=5.0,
        establishment_estimable=True,
        establishment_note="Branching process on R and k applies to direct human transmission.",
        confidence=Confidence.MODERATE,
        references=(
            "Endo A et al. Overdispersion in COVID-19 transmission. Wellcome Open Res 2020.",
            "Lloyd-Smith JO et al. Nature 2005;438:355-359.",
        ),
        aliases=(
            "covid-19",
            "covid",
            "sars-cov-2",
            "coronavirus disease",
            "pneumonia of undetermined etiology",
        ),
    ),
    PathogenProfile(
        key="seasonal_influenza",
        label="Seasonal influenza",
        description="Community influenza. Avian influenza is a separate profile.",
        alpha=ParameterRange(
            low=0.3,
            central=0.5,
            high=0.8,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note="Many infections are mild enough to travel. Not a published boarding rate.",
        ),
        reproduction_number=ParameterRange(
            low=1.2,
            central=1.3,
            high=1.8,
            basis=ParameterBasis.LITERATURE,
            note="Seasonal influenza reproduction numbers in temperate epidemics.",
        ),
        dispersion_k=ParameterRange(
            low=0.5,
            central=1.0,
            high=2.0,
            basis=ParameterBasis.LITERATURE,
            note="Less clustered than SARS-CoV-2. A larger k means fewer superspreading events.",
        ),
        infectious_period_days=5.0,
        incubation_period_days=2.0,
        establishment_estimable=True,
        establishment_note="Branching process on R and k applies to direct human transmission.",
        confidence=Confidence.MODERATE,
        references=(
            "Biggerstaff M et al. Reproduction number for seasonal influenza. BMC Infect Dis 2014.",
        ),
        aliases=("seasonal influenza", "influenza"),
    ),
    PathogenProfile(
        key="avian_influenza",
        label="Avian influenza (H5N1 and related)",
        description="Zoonotic avian influenza with limited sustained human-to-human spread.",
        alpha=ParameterRange(
            low=0.01,
            central=0.05,
            high=0.15,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note="Recognised human cases are usually too ill to fly. Not a measured rate.",
        ),
        reproduction_number=ParameterRange(
            low=0.1,
            central=0.5,
            high=0.9,
            basis=ParameterBasis.LITERATURE,
            note="WHO assessments keep human H5N1 community R below 1, so establishment is zero.",
        ),
        dispersion_k=ParameterRange(
            low=0.1,
            central=0.5,
            high=1.0,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note="Unused while R stays below 1. Present so the profile has a complete range.",
        ),
        infectious_period_days=7.0,
        incubation_period_days=3.0,
        establishment_estimable=True,
        establishment_note=(
            "The whole R range is below 1, so this model gives establishment probability zero. "
            "That is community transmission only."
        ),
        confidence=Confidence.LOW,
        references=("WHO avian influenza risk assessments.",),
        aliases=(
            "influenza a h5n1",
            "influenza a(h5n1)",
            "avian influenza",
            "h5n1",
        ),
    ),
    PathogenProfile(
        key="measles",
        label="Measles",
        description="Highly transmissible rash illness. Most infectious people are visibly sick.",
        alpha=ParameterRange(
            low=0.05,
            central=0.15,
            high=0.4,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note="The rash makes boarding less likely than for a mild respiratory virus.",
        ),
        reproduction_number=ParameterRange(
            low=12.0,
            central=15.0,
            high=18.0,
            basis=ParameterBasis.LITERATURE,
            note="Classic measles basic reproduction numbers in a fully susceptible population.",
        ),
        dispersion_k=ParameterRange(
            low=0.5,
            central=1.0,
            high=2.0,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note="Measles is less clustered than SARS-CoV-2. The range is an assumption.",
        ),
        infectious_period_days=8.0,
        incubation_period_days=10.0,
        establishment_estimable=True,
        establishment_note=(
            "R applies to a susceptible population. High vaccination coverage, which this "
            "model does not represent, would lower it."
        ),
        confidence=Confidence.MODERATE,
        references=(
            "Guerra FM et al. The basic reproduction number of measles. Lancet Infect Dis 2017.",
        ),
        aliases=("measles",),
    ),
    PathogenProfile(
        key="mpox",
        label="Mpox",
        description="Mpox, including the 2022 multi-country clade. Calibration holdout.",
        alpha=ParameterRange(
            low=0.2,
            central=0.4,
            high=0.7,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note="Many 2022 infections were mild enough to travel. Not a published boarding rate.",
        ),
        reproduction_number=ParameterRange(
            low=0.8,
            central=1.4,
            high=2.2,
            basis=ParameterBasis.LITERATURE,
            note="Early 2022 estimates sat just above 1 in the most affected networks, then fell.",
        ),
        dispersion_k=ParameterRange(
            low=0.1,
            central=0.3,
            high=0.8,
            basis=ParameterBasis.LITERATURE,
            note="Transmission was concentrated in specific contact networks.",
        ),
        infectious_period_days=14.0,
        incubation_period_days=8.0,
        establishment_estimable=True,
        establishment_note="Branching process on R and k. Networks beyond k are not modelled.",
        confidence=Confidence.LOW,
        references=("WHO multi-country mpox outbreak external situation reports, 2022.",),
        aliases=("mpox", "monkeypox"),
    ),
    PathogenProfile(
        key="low_mobility_severe",
        label="Severe filovirus-like (Ebola, Marburg)",
        description=(
            "Severe disease whose infectious period is incapacitating, so very few "
            "infectious people board international flights."
        ),
        alpha=ParameterRange(
            low=0.005,
            central=0.02,
            high=0.05,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note=(
                "The research note describes boarding while infectious as 'very low' "
                "for Ebola: people are usually too sick to fly during the highly "
                "infectious period, and exit screening was strict. No published "
                "numeric estimate of alpha is used here."
            ),
        ),
        reproduction_number=ParameterRange(
            low=1.2,
            central=1.5,
            high=2.0,
            basis=ParameterBasis.LITERATURE,
            note="Community reproduction numbers reported during West Africa 2014-2016.",
        ),
        dispersion_k=ParameterRange(
            low=0.1,
            central=0.2,
            high=0.4,
            basis=ParameterBasis.LITERATURE,
            note="Filovirus transmission is strongly clustered around care and burial events.",
        ),
        infectious_period_days=9.0,
        incubation_period_days=9.0,
        establishment_estimable=True,
        establishment_note=(
            "Establishment is estimable, but note the negative-control expectation from "
            "the research note: a very low alpha should keep international establishment "
            "low even where local R exceeds 1."
        ),
        confidence=Confidence.LOW,
        references=(
            "WHO Ebola situation reports, West Africa 2014-2016 and DRC 2018-2020.",
            "Briefing note: How disease-spread probabilities get their data, 14 Oct 2026.",
        ),
        aliases=("ebola", "marburg", "filovirus", "haemorrhagic fever", "hemorrhagic fever"),
    ),
    PathogenProfile(
        key="hospital_amplified",
        label="Hospital-amplified (MERS-like)",
        description=(
            "Pathogen with limited community transmission whose outbreaks are "
            "amplified in healthcare settings after a rare introduction."
        ),
        alpha=ParameterRange(
            low=0.05,
            central=0.15,
            high=0.3,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note=(
                "The research note describes boarding while infectious as 'medium to low' "
                "outside hospitals for MERS. Not a published estimate."
            ),
        ),
        reproduction_number=ParameterRange(
            low=0.3,
            central=0.6,
            high=0.9,
            basis=ParameterBasis.LITERATURE,
            note=(
                "Community R below 1 in WHO assessments. Because the range stays below 1, "
                "the branching process correctly returns zero establishment probability: "
                "the hospital amplification that drives real MERS clusters is a different "
                "process from the community transmission this model represents."
            ),
        ),
        dispersion_k=ParameterRange(
            low=0.05,
            central=0.1,
            high=0.3,
            basis=ParameterBasis.LITERATURE,
            note="Extremely clustered: a few nosocomial events dominate.",
        ),
        infectious_period_days=7.0,
        incubation_period_days=6.0,
        establishment_estimable=True,
        establishment_note=(
            "Community establishment only. Nosocomial amplification is NOT modelled, so a "
            "zero here does not mean a hospital cluster is impossible."
        ),
        confidence=Confidence.LOW,
        references=(
            "WHO Middle East respiratory syndrome coronavirus risk assessments.",
            "Briefing note: How disease-spread probabilities get their data, 14 Oct 2026.",
        ),
        aliases=(
            "mers",
            "middle east respiratory",
        ),
    ),
    PathogenProfile(
        key="vector_borne",
        label="Vector-borne (Zika, dengue, chikungunya)",
        description=(
            "Mild or asymptomatic infection travels readily, but whether it establishes "
            "is decided by the local vector population and climate."
        ),
        alpha=ParameterRange(
            low=0.6,
            central=0.8,
            high=1.0,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note=(
                "The research note describes boarding while infectious as 'high' for Zika: "
                "many infections were mild or asymptomatic, so infected travellers kept "
                "moving. Not a published estimate."
            ),
        ),
        # These are never used: establishment_estimable is False. They are
        # present only so the dataclass is uniform, and are deliberately set to
        # the subcritical value so any accidental use yields zero rather than a
        # misleading positive probability.
        reproduction_number=ParameterRange(
            low=0.0,
            central=0.0,
            high=0.0,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note="Not used: establishment for this class is reported as not estimable.",
        ),
        dispersion_k=ParameterRange(
            low=0.1,
            central=0.1,
            high=0.1,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note="Not used: establishment for this class is reported as not estimable.",
        ),
        infectious_period_days=7.0,
        incubation_period_days=6.0,
        establishment_estimable=False,
        establishment_note=(
            "Establishment depends on local vector presence, density and climate "
            "suitability. Endemica holds no vector-suitability dataset, so it reports "
            "establishment as not estimable rather than substituting a human-to-human R. "
            "Importation risk is still estimable and is reported."
        ),
        confidence=Confidence.INDICATIVE_ONLY,
        references=(
            "PAHO Zika epidemiological alerts and updates.",
            "Briefing note: How disease-spread probabilities get their data, 14 Oct 2026.",
        ),
        aliases=("zika", "dengue", "chikungunya", "yellow fever", "west nile"),
    ),
    PathogenProfile(
        key="enteric_waterborne",
        label="Enteric / waterborne (cholera-like)",
        description=(
            "Faecal-oral transmission whose establishment depends on water and "
            "sanitation infrastructure rather than on contact rates alone."
        ),
        alpha=ParameterRange(
            low=0.1,
            central=0.3,
            high=0.6,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note=(
                "Many infections are mild, but severe cases do not travel. "
                "Not a published estimate."
            ),
        ),
        reproduction_number=ParameterRange(
            low=0.0,
            central=0.0,
            high=0.0,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note="Not used: establishment for this class is reported as not estimable.",
        ),
        dispersion_k=ParameterRange(
            low=0.1,
            central=0.1,
            high=0.1,
            basis=ParameterBasis.PROJECT_ASSUMPTION,
            note="Not used: establishment for this class is reported as not estimable.",
        ),
        infectious_period_days=7.0,
        incubation_period_days=2.0,
        establishment_estimable=False,
        establishment_note=(
            "Establishment is governed by water and sanitation conditions, which Endemica "
            "does not model. Reported as not estimable."
        ),
        confidence=Confidence.INDICATIVE_ONLY,
        references=(
            "Briefing note: How disease-spread probabilities get their data, 14 Oct 2026.",
        ),
        aliases=(
            "cholera",
            "typhoid",
            "hepatitis a",
            "acute watery diarrhoea",
            "poliomyelitis",
            "polio",
        ),
    ),
)

PROFILES: Final[MappingProxyType[str, PathogenProfile]] = MappingProxyType(
    {p.key: p for p in _PROFILES}
)
"""Read-only registry of pathogen profiles, keyed by :attr:`PathogenProfile.key`."""

DEFAULT_PROFILE_KEY: Final = "respiratory_default"

# Longer aliases are matched first so that, for example, "middle east
# respiratory" wins over the generic "respiratory syndrome".
_ALIAS_INDEX: Final[tuple[tuple[str, str], ...]] = tuple(
    sorted(
        ((alias, profile.key) for profile in _PROFILES for alias in profile.aliases),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
)

_NON_WORD = re.compile(r"[^a-z0-9]+")


def _normalise(label: str) -> str:
    """Lowercase and collapse punctuation so alias matching is robust.

    WHO titles vary between "Avian influenza - Egypt", "Avian influenza -
    Egypt" with an en dash, and "Avian influenza (H5N1)".
    """
    return _NON_WORD.sub(" ", label.casefold()).strip()


def get_profile(key: str) -> PathogenProfile:
    """Return the profile registered under ``key``.

    Raises:
        ModelInputError: If no profile has that key. The caller must not fall
            back to a default silently, because the choice of profile changes
            every published number.
    """
    try:
        return PROFILES[key]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        msg = f"unknown pathogen profile '{key}'; known profiles: {known}"
        raise ModelInputError(msg) from None


def match_profile_key(disease_label: str | None) -> str | None:
    """Map a source's free-text disease label to a profile key.

    Matching is by longest alias substring on a punctuation-normalised label.

    Args:
        disease_label: The disease exactly as the source words it.

    Returns:
        The matching profile key, or ``None`` when nothing matches. ``None``
        is deliberate: an unmatched pathogen gets no parameters, and the API
        reports its establishment risk as not estimable rather than applying
        respiratory defaults to, say, a fungal infection.

    Example:
        >>> match_profile_key("Ebola disease caused by Bundibugyo virus")
        'low_mobility_severe'
        >>> match_profile_key("Middle East respiratory syndrome coronavirus")
        'hospital_amplified'
        >>> match_profile_key("Something entirely new") is None
        True
    """
    if not disease_label:
        return None
    normalised = _normalise(disease_label)
    for alias, key in _ALIAS_INDEX:
        if _normalise(alias) in normalised:
            return key
    return None
