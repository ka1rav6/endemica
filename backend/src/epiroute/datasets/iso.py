"""Country-name to ISO 3166-1 alpha-3 normalisation.

Every dataset EpiRoute joins uses its own spelling of country names, and the
implementation plan identifies this as the largest source of join bugs. ISO-3
is the single join key, and this module is the only place a name becomes one.

:mod:`pycountry` provides the ISO register but its ``lookup`` misses many
spellings that appear in real data — "Turkey", "Russia", "DR Congo",
"Cote d'Ivoire" without the diacritic, "Cape Verde", "Swaziland", "Burma",
"Kosovo", "Palestine" and "Macau" all fail against the live library. The
:data:`ALIASES` table below closes those gaps and was built by testing the
actual strings that occur in Natural Earth, OpenFlights, the WHO Disease
Outbreak News titles and Eurostat labels.

**Resolution never guesses.** :func:`resolve` returns ``None`` for a name it
cannot map, and callers treat that as a validation failure. Fuzzy matching is
deliberately absent: silently mapping "Guinea-Bissau" to "Guinea" would place
an outbreak in the wrong country, which is worse than reporting an unmapped
name to an operator.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from types import MappingProxyType
from typing import Final

import pycountry

# Aliases that pycountry does not resolve, or resolves differently from how the
# sources spell them. Keys are normalised by `_normalise` before lookup, so
# only one casing/punctuation variant of each needs listing here.
#
# Entries mapping to None are recognised non-countries: aggregates and regions
# that appear in source files and must be *rejected* rather than mapped to
# whichever member state happens to match. Returning None for them is the
# correct answer, not a gap.
_RAW_ALIASES: Final[dict[str, str | None]] = {
    # --- Spellings pycountry rejects -------------------------------------
    "turkey": "TUR",
    "turkiye": "TUR",
    "republic of turkiye": "TUR",
    "russia": "RUS",
    "russian federation": "RUS",
    "uk": "GBR",
    "great britain": "GBR",
    "england": "GBR",
    "scotland": "GBR",
    "wales": "GBR",
    "northern ireland": "GBR",
    "united kingdom of great britain and northern ireland": "GBR",
    "us": "USA",
    "u s a": "USA",
    "united states of america": "USA",
    "cape verde": "CPV",
    "cabo verde": "CPV",
    "swaziland": "SWZ",
    "eswatini": "SWZ",
    "kingdom of eswatini": "SWZ",
    "burma": "MMR",
    "macau": "MAC",
    "macao": "MAC",
    "macau sar china": "MAC",
    "hong kong sar china": "HKG",
    "macedonia": "MKD",
    "north macedonia": "MKD",
    "former yugoslav republic of macedonia": "MKD",
    "palestine": "PSE",
    "state of palestine": "PSE",
    "palestinian territory": "PSE",
    "west bank and gaza": "PSE",
    "occupied palestinian territory": "PSE",
    # Kosovo has no assigned ISO-3166-1 code. XKX is the de facto placeholder
    # used by the World Bank and by Natural Earth, and EpiRoute adopts it so
    # Kosovo rows are not silently dropped. Documented in docs/data-sources.md.
    "kosovo": "XKX",
    "republic of kosovo": "XKX",
    # --- Congo: the classic join bug -------------------------------------
    "dr congo": "COD",
    "drc": "COD",
    "democratic republic of the congo": "COD",
    "democratic republic of congo": "COD",
    "congo kinshasa": "COD",
    "congo democratic republic of the": "COD",
    "zaire": "COD",
    "republic of the congo": "COG",
    "congo brazzaville": "COG",
    "congo republic": "COG",
    "congo": "COG",
    # --- Diacritic-free and colonial-era spellings -----------------------
    "cote d ivoire": "CIV",
    "cote divoire": "CIV",
    "ivory coast": "CIV",
    "sao tome and principe": "STP",
    "curacao": "CUW",
    "reunion": "REU",
    "aland islands": "ALA",
    "saint barthelemy": "BLM",
    # --- Short forms used by WHO and in the press ------------------------
    "south korea": "KOR",
    "republic of korea": "KOR",
    "korea republic of": "KOR",
    "north korea": "PRK",
    "democratic people s republic of korea": "PRK",
    "laos": "LAO",
    "lao pdr": "LAO",
    "syria": "SYR",
    "iran": "IRN",
    "islamic republic of iran": "IRN",
    "bolivia": "BOL",
    "venezuela": "VEN",
    "tanzania": "TZA",
    "united republic of tanzania": "TZA",
    "moldova": "MDA",
    "republic of moldova": "MDA",
    "vietnam": "VNM",
    "viet nam": "VNM",
    "brunei": "BRN",
    "brunei darussalam": "BRN",
    "cape of good hope": "ZAF",
    "czech republic": "CZE",
    "czechia": "CZE",
    "slovak republic": "SVK",
    "east timor": "TLS",
    "timor leste": "TLS",
    "micronesia": "FSM",
    "federated states of micronesia": "FSM",
    "the gambia": "GMB",
    "gambia the": "GMB",
    "the bahamas": "BHS",
    "bahamas the": "BHS",
    "netherlands antilles": "ANT",
    "saint vincent and the grenadines": "VCT",
    "saint helena": "SHN",
    "falkland islands": "FLK",
    "falkland islands malvinas": "FLK",
    "vatican": "VAT",
    "holy see": "VAT",
    "vatican city": "VAT",
    "united arab emirates": "ARE",
    "uae": "ARE",
    "saudi arabia": "SAU",
    "kingdom of saudi arabia": "SAU",
    "cyprus no mans area": "CYP",
    "northern cyprus": "CYP",
    "somaliland": "SOM",
    "western sahara": "ESH",
    "sahrawi arab democratic republic": "ESH",
    "south sudan": "SSD",
    "republic of south sudan": "SSD",
    "sudan the": "SDN",
    "bosnia and herzegovina": "BIH",
    "bosnia": "BIH",
    "serbia": "SRB",
    "republic of serbia": "SRB",
    "montenegro": "MNE",
    "antigua and barbuda": "ATG",
    "trinidad and tobago": "TTO",
    "papua new guinea": "PNG",
    "new caledonia": "NCL",
    "french polynesia": "PYF",
    "cook islands": "COK",
    "wallis and futuna": "WLF",
    "pitcairn islands": "PCN",
    "british virgin islands": "VGB",
    "us virgin islands": "VIR",
    "u s virgin islands": "VIR",
    "virgin islands u s": "VIR",
    "turks and caicos islands": "TCA",
    "saint kitts and nevis": "KNA",
    "saint pierre and miquelon": "SPM",
    "saint martin": "MAF",
    "sint maarten": "SXM",
    "bonaire sint eustatius and saba": "BES",
    "french southern territories": "ATF",
    "french southern and antarctic lands": "ATF",
    "heard island and mcdonald islands": "HMD",
    "south georgia and the south sandwich islands": "SGS",
    "south georgia and south sandwich is": "SGS",
    "british indian ocean territory": "IOT",
    "united states minor outlying islands": "UMI",
    "indian ocean territories": "AUS",
    "ashmore and cartier islands": "AUS",
    "siachen glacier": "IND",
    "coral sea islands": "AUS",
    "clipperton island": "FRA",
    "spratly islands": None,
    "paracel islands": None,
    "scarborough reef": None,
    "bajo nuevo bank": None,
    "serranilla bank": None,
    "southern patagonian ice field": None,
    "antarctica": "ATA",
    # --- Recognised aggregates: must be rejected, not mapped -------------
    "world": None,
    "global": None,
    "global situation": None,
    "europe": None,
    "africa": None,
    "asia": None,
    "americas": None,
    "oceania": None,
    "european union": None,
    "european union 27 countries from 2020": None,
    "euro area": None,
    "eu27 2020": None,
    "eu28": None,
    "multiple countries": None,
    "unknown": None,
    "other": None,
    "not specified": None,
    "extra eu27 2020": None,
    "extra euro area": None,
    "african region": None,
    "region of the americas": None,
    "south east asia region": None,
    "eastern mediterranean region": None,
    "western pacific region": None,
    "european region": None,
}

# Natural Earth uses '-99' for territories with no assigned ISO code; those
# rows are resolved by name through the alias table instead.
UNASSIGNED_ISO_PLACEHOLDERS: Final[frozenset[str]] = frozenset({"-99", "-099", "", "ZZ", "ZZZ"})

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Parenthesised qualifiers and trailing descriptors that carry no identity,
# e.g. "Bolivia (Plurinational State of)" or "Korea, Republic of".
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")


def _strip_diacritics(text: str) -> str:
    """Remove combining marks so "Côte d'Ivoire" matches "Cote d Ivoire"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _normalise_keeping_qualifiers(name: str) -> str:
    """Reduce a name to a key *without* discarding parenthesised qualifiers.

    Tried first, because a qualifier can be the only thing distinguishing two
    countries: "Congo (Kinshasa)" is COD while plain "Congo" is COG. Stripping
    the parenthetical before the alias lookup would silently place an outbreak
    in the wrong country.

    Example:
        >>> _normalise_keeping_qualifiers("Congo (Kinshasa)")
        'congo kinshasa'
        >>> _normalise_keeping_qualifiers("Côte d'Ivoire")
        'cote d ivoire'
    """
    folded = _strip_diacritics(name).casefold()
    return _NON_ALNUM.sub(" ", folded).strip()


def _normalise(name: str) -> str:
    """Reduce a country name to a comparable key, dropping qualifiers.

    Lowercases, strips diacritics, removes parenthesised qualifiers and
    collapses all punctuation to single spaces. Tried *after*
    :func:`_normalise_keeping_qualifiers`.

    Example:
        >>> _normalise("Bolivia (Plurinational State of)")
        'bolivia'
        >>> _normalise("Côte d'Ivoire")
        'cote d ivoire'
        >>> _normalise("Korea, Republic of")
        'korea republic of'
    """
    without_parens = _PARENTHETICAL.sub("", name)
    folded = _strip_diacritics(without_parens).casefold()
    return _NON_ALNUM.sub(" ", folded).strip()


ALIASES: Final[MappingProxyType[str, str | None]] = MappingProxyType(
    {_normalise_keeping_qualifiers(key): value for key, value in _RAW_ALIASES.items()}
)
"""Normalised alias table. ``None`` marks a recognised non-country."""

# Codes EpiRoute accepts that are not in ISO 3166-1. Each needs a rationale.
EXTRA_CODES: Final[MappingProxyType[str, str]] = MappingProxyType(
    {
        # No ISO-3166-1 code is assigned to Kosovo. XKX is the placeholder used
        # by the World Bank and Natural Earth; adopting it keeps Kosovo rows
        # joinable rather than dropped.
        "XKX": "Kosovo",
        # ANT (Netherlands Antilles) was withdrawn in 2010 but still appears in
        # historical aviation statistics.
        "ANT": "Netherlands Antilles (historical)",
    }
)


@functools.lru_cache(maxsize=4096)
def resolve(name: str | None) -> str | None:
    """Resolve a country name or code to ISO 3166-1 alpha-3.

    Resolution order: the alias table (which also rejects known aggregates),
    then :mod:`pycountry` on the normalised name, then pycountry on the
    original string, which catches codes and official names.

    Args:
        name: A country name, alpha-2 code, alpha-3 code, or ``None``.

    Returns:
        The upper-case alpha-3 code, or ``None`` when the name cannot be
        resolved or is a recognised aggregate rather than a country.

    Example:
        >>> resolve("Democratic Republic of the Congo")
        'COD'
        >>> resolve("Congo (Kinshasa)")
        'COD'
        >>> resolve("Congo")
        'COG'
        >>> resolve("Turkey"), resolve("Türkiye")
        ('TUR', 'TUR')
        >>> resolve("DE"), resolve("DEU")
        ('DEU', 'DEU')
        >>> resolve("Global situation") is None
        True
        >>> resolve("Atlantis") is None
        True
    """
    if not name:
        return None
    stripped = name.strip()
    if not stripped:
        return None

    # A bare alpha-3 we already accept, including the documented extras.
    upper = stripped.upper()
    if upper in EXTRA_CODES:
        return upper
    if upper in UNASSIGNED_ISO_PLACEHOLDERS:
        return None

    # Qualifier-preserving key first: see _normalise_keeping_qualifiers.
    qualified_key = _normalise_keeping_qualifiers(stripped)
    if qualified_key in ALIASES:
        return ALIASES[qualified_key]
    plain_key = _normalise(stripped)
    if plain_key in ALIASES:
        return ALIASES[plain_key]

    for candidate in (qualified_key, plain_key, stripped):
        try:
            return str(pycountry.countries.lookup(candidate).alpha_3)
        except LookupError:
            continue
    return None


def resolve_strict(name: str | None, *, context: str = "") -> str:
    """Resolve a country name, raising when it cannot be mapped.

    Used on ingestion paths where an unmapped name must stop the record from
    being persisted rather than be silently skipped.

    Args:
        name: The name to resolve.
        context: Extra text for the error message, e.g. the source URL.

    Returns:
        The alpha-3 code.

    Raises:
        DataValidationError: If the name cannot be resolved.
    """
    from epiroute.core.errors import DataValidationError

    code = resolve(name)
    if code is None:
        suffix = f" ({context})" if context else ""
        msg = f"could not resolve country name {name!r} to an ISO-3 code{suffix}"
        raise DataValidationError(msg, field="country")
    return code


@functools.lru_cache(maxsize=1024)
def country_name(iso3: str) -> str:
    """Return a display name for an alpha-3 code.

    Falls back to the code itself for an unknown value, so a display path can
    never raise on bad data.
    """
    upper = iso3.upper()
    if upper in EXTRA_CODES:
        return EXTRA_CODES[upper]
    try:
        record = pycountry.countries.get(alpha_3=upper)
    except LookupError:  # pragma: no cover - pycountry.get returns None instead
        return upper
    if record is None:
        return upper
    return str(getattr(record, "common_name", None) or record.name)


def is_known_iso3(code: str) -> bool:
    """Whether ``code`` is an alpha-3 EpiRoute recognises."""
    upper = code.upper()
    return upper in EXTRA_CODES or pycountry.countries.get(alpha_3=upper) is not None
