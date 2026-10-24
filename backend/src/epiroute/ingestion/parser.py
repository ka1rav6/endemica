from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from epiroute.datasets.iso import find_countries, find_countries_with_positions, resolve
from epiroute.tinyfish.schemas import ExtractedLocation, ExtractedReport

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
_NUMBER = re.compile(r"\b(\d{1,3}(?:[,    ]\d{3})+|\d+)\b")
_NUMBER_TOKEN = r"\d{1,3}(?:[,    ]\d{3})+|\d+"

# A field may be written "42 confirmed cases" or "confirmed cases have reached 42".
# Both are accepted. The second form is how WHO states a national cumulative total.
_FIELD_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "cases_confirmed",
        (
            re.compile(
                rf"(?P<n>{_NUMBER_TOKEN})\s+"
                r"(?:(?:new|additional|cumulative|total|more)\s+)*"
                r"(?:laboratory[- ]confirmed|lab[- ]confirmed|confirmed)\s+"
                r"(?:human\s+)?cases?",
                re.IGNORECASE,
            ),
            re.compile(
                rf"(?:cumulative|total)\s+confirmed\s+cases\s+have\s+reached\s+(?P<n>{_NUMBER_TOKEN})",
                re.IGNORECASE,
            ),
        ),
    ),
    (
        "cases_probable",
        (
            re.compile(
                rf"(?P<n>{_NUMBER_TOKEN})\s+"
                r"(?:(?:new|additional|cumulative|total)\s+)*probable\s+cases?",
                re.IGNORECASE,
            ),
        ),
    ),
    (
        "cases_suspected",
        (
            re.compile(
                rf"(?P<n>{_NUMBER_TOKEN})\s+"
                r"(?:(?:new|additional|cumulative|total)\s+)*suspect(?:ed)?\s+cases?",
                re.IGNORECASE,
            ),
        ),
    ),
    (
        "deaths",
        (
            re.compile(
                rf"(?P<n>{_NUMBER_TOKEN})\s+"
                r"(?:(?:new|additional|cumulative|total|associated|related)\s+)*"
                r"(?:confirmed\s+)?deaths?",
                re.IGNORECASE,
            ),
        ),
    ),
)

# Skip a sentence that is about something other than cases and deaths.
# "recover" is intentionally not here: a cumulative-total sentence often ends
# with a recovery count, and dropping the whole sentence would drop the total.
_EXCLUDE_SENTENCE = re.compile(
    r"\b(vaccinat|coverage|dose|discharge|contact(?:s)? (?:were|have|traced)|"
    r"sample|test(?:s|ed|ing)|bed|staff|training|funding|per cent of (?:the )?target)\b",
    re.IGNORECASE,
)

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

# Only dates tied to the outbreak's beginning. A death date or a travel date
# must not become the age used in the prevalence formula.
_OUTBREAK_START = re.compile(
    r"\b(?:declaration of the outbreak|outbreak was declared|outbreak began|outbreak started)"
    r"[^.]{0,180}?\bon\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    re.IGNORECASE,
)

_COUNTRY_HINT = re.compile(
    r"\b(?:in|from|of|across|affecting)\s+(?P<name>(?:[A-Z][\w'’-]*\s*){1,4})"
)


COUNTRY_PROXIMITY_WINDOW = 30

_SUBSET_MARKER = re.compile(
    r"\b(includ\w*|of which|among (?:them|which)|respectively|as well as|plus)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ParsedSentence:
    sentence: str
    values: dict[str, int]
    positions: dict[str, int]


def _to_int(text: str) -> int | None:
    digits = re.sub(r"[,    ]", "", text)
    try:
        return int(digits)
    except ValueError:
        return None


def split_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT.split(cleaned) if s.strip()]


def parse_sentence(sentence: str) -> ParsedSentence | None:
    if _EXCLUDE_SENTENCE.search(sentence):
        return None
    values: dict[str, int] = {}
    positions: dict[str, int] = {}
    for field_name, patterns in _FIELD_PATTERNS:
        match = next((found for pattern in patterns if (found := pattern.search(sentence))), None)
        if match is None:
            continue
        value = _to_int(match.group("n"))
        if value is not None:
            values[field_name] = value
            positions[field_name] = match.start("n")
    if not values:
        return None
    return ParsedSentence(sentence=sentence, values=values, positions=positions)


def find_country_in_sentence(
    sentence: str, fallback_iso3: str | None, *, number_position: int | None = None
) -> str | None:
    candidates = find_countries_with_positions(sentence)
    if not candidates:
        return fallback_iso3

    codes = {iso3 for iso3, _, _ in candidates}
    if fallback_iso3 in codes:
        return fallback_iso3
    if number_position is None:
        return candidates[0][0] if len(candidates) == 1 else fallback_iso3

    nearest, distance = None, None
    for iso3, start, end in candidates:
        gap = (
            0
            if start <= number_position <= end
            else min(abs(start - number_position), abs(end - number_position))
        )
        if distance is None or gap < distance:
            nearest, distance = iso3, gap

    if nearest is None or distance is None or distance > COUNTRY_PROXIMITY_WINDOW:
        return fallback_iso3

    marker = _SUBSET_MARKER.search(sentence, number_position)
    if marker is not None and marker.start() < number_position + distance:
        return fallback_iso3
    return nearest


def parse_report(
    text: str, *, title: str | None = None, disease_label: str | None = None
) -> ExtractedReport:
    fallback_iso3 = _country_from_title(title) if title else None
    locations: list[ExtractedLocation] = []

    for sentence in split_sentences(text):
        parsed = parse_sentence(sentence)
        if parsed is None:
            continue
        anchor = min(parsed.positions.values()) if parsed.positions else None
        iso3 = find_country_in_sentence(sentence, fallback_iso3, number_position=anchor)
        if iso3 is None:
            continue
        locations.append(
            ExtractedLocation(
                country=iso3,
                cases_confirmed=parsed.values.get("cases_confirmed"),
                cases_probable=parsed.values.get("cases_probable"),
                cases_suspected=parsed.values.get("cases_suspected"),
                deaths=parsed.values.get("deaths"),
                evidence=parsed.sentence,
            )
        )

    return ExtractedReport(disease=disease_label, locations=locations)


def _country_from_title(title: str) -> str | None:
    found = find_countries(title)
    if found:
        return found[0]
    for separator in ("\u2013", "\u2014", " - "):
        if separator in title:
            return resolve(title.rsplit(separator, 1)[1].strip())
    return None


def countries_in_title(title: str | None) -> list[str]:
    return find_countries(title) if title else []


def find_outbreak_start(text: str) -> date | None:
    """Return the outbreak start date when the text explicitly states one.

    Matches wording such as "declaration of the outbreak on 15 May 2026".
    Other dates in the bulletin (symptom onset, death, travel) are ignored.
    If several declaration dates appear, the earliest is used.

    Returns:
        The start date, or ``None`` when the text does not state one.
    """
    if not text:
        return None
    found: list[date] = []
    for day, month, year in _OUTBREAK_START.findall(text):
        month_number = _MONTHS.get(month.casefold())
        if month_number is None:
            continue
        try:
            found.append(date(int(year), month_number, int(day)))
        except ValueError:
            continue
    return min(found) if found else None
