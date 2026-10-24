from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

_YEAR_PREFIX = re.compile(r"^\s*(19|20)\d{2}\s*[-–—:]\s*")
_UPDATE_SUFFIX = re.compile(
    r"[\s,;:–—-]+(update|updates?\s*\d+|situation\s+report).*$", re.IGNORECASE
)
_SEPARATORS = ("–", "—", " - ", " -", "- ", " – ", ":")
_IN_COUNTRY = re.compile(
    r"\s+(?:in|of|from|reported\s+in)\s+(?:the\s+)?[A-ZÀ-Þ].*$",
)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class DiseaseDefinition:
    key: str
    name: str
    family: str
    patterns: tuple[str, ...]


DEFINITIONS: Final[tuple[DiseaseDefinition, ...]] = (
    DiseaseDefinition(
        "covid19",
        "COVID-19",
        "Respiratory virus",
        (r"covid.?19", r"sars.?cov.?2", r"novel coronavirus", r"2019.?ncov"),
    ),
    DiseaseDefinition(
        "sars",
        "SARS",
        "Respiratory virus",
        (r"severe acute respiratory syndrome(?!.*coronavirus 2)", r"\bsars\b(?!.?cov.?2)"),
    ),
    DiseaseDefinition(
        "mers",
        "MERS-CoV",
        "Respiratory virus",
        (r"middle east respiratory", r"mers.?cov", r"\bmers\b"),
    ),
    DiseaseDefinition(
        "influenza_h5n1",
        "Avian influenza A(H5N1)",
        "Influenza",
        (r"h5n1", r"avian influenza(?!.*h7n9)(?!.*h9n2)(?!.*h5n6)(?!.*h10)(?!.*h3n8)"),
    ),
    DiseaseDefinition(
        "influenza_h7n9",
        "Avian influenza A(H7N9)",
        "Influenza",
        (r"h7n9",),
    ),
    DiseaseDefinition(
        "influenza_h5n6",
        "Avian influenza A(H5N6)",
        "Influenza",
        (r"h5n6",),
    ),
    DiseaseDefinition(
        "influenza_h9n2",
        "Avian influenza A(H9N2)",
        "Influenza",
        (r"h9n2",),
    ),
    DiseaseDefinition(
        "influenza_h1n1",
        "Influenza A(H1N1)",
        "Influenza",
        (r"h1n1", r"pandemic \(h1n1\)", r"swine influenza"),
    ),
    DiseaseDefinition(
        "influenza_other",
        "Other zoonotic influenza",
        "Influenza",
        (
            r"h10n\d",
            r"h3n8",
            r"h5n5",
            r"h7n\d",
            r"h1n2",
            r"variant influenza",
            r"influenza a\s?\(?h",
            r"reassortant",
        ),
    ),
    DiseaseDefinition(
        "influenza_seasonal",
        "Seasonal influenza",
        "Influenza",
        (r"h3n2", r"\binfluenza\b"),
    ),
    DiseaseDefinition(
        "ebola",
        "Ebola virus disease",
        "Viral haemorrhagic fever",
        (r"\bebola\b", r"sudan virus disease", r"sudan ebolavirus", r"bundibugyo"),
    ),
    DiseaseDefinition(
        "marburg",
        "Marburg virus disease",
        "Viral haemorrhagic fever",
        (r"marburg",),
    ),
    DiseaseDefinition(
        "lassa",
        "Lassa fever",
        "Viral haemorrhagic fever",
        (r"lassa",),
    ),
    DiseaseDefinition(
        "cchf",
        "Crimean-Congo haemorrhagic fever",
        "Viral haemorrhagic fever",
        (r"crimean.?congo", r"\bcchf\b"),
    ),
    DiseaseDefinition(
        "rvf",
        "Rift Valley fever",
        "Viral haemorrhagic fever",
        (r"rift valley",),
    ),
    DiseaseDefinition(
        "vhf_unspecified",
        "Unspecified haemorrhagic fever",
        "Viral haemorrhagic fever",
        (r"haemorrhagic fever syndrome", r"viral haemorrhagic fever", r"hemorrhagic fever"),
    ),
    DiseaseDefinition(
        "yellow_fever",
        "Yellow fever",
        "Vector-borne",
        (r"yellow fever",),
    ),
    DiseaseDefinition(
        "dengue",
        "Dengue",
        "Vector-borne",
        (r"\bdengue\b",),
    ),
    DiseaseDefinition(
        "zika",
        "Zika virus disease",
        "Vector-borne",
        (r"\bzika\b",),
    ),
    DiseaseDefinition(
        "chikungunya",
        "Chikungunya",
        "Vector-borne",
        (r"chikungunya",),
    ),
    DiseaseDefinition(
        "malaria",
        "Malaria",
        "Vector-borne",
        (r"\bmalaria\b",),
    ),
    DiseaseDefinition(
        "west_nile",
        "West Nile virus",
        "Vector-borne",
        (r"west nile",),
    ),
    DiseaseDefinition(
        "japanese_encephalitis",
        "Japanese encephalitis",
        "Vector-borne",
        (r"japanese encephalitis",),
    ),
    DiseaseDefinition(
        "oropouche",
        "Oropouche virus disease",
        "Vector-borne",
        (r"oropouche",),
    ),
    DiseaseDefinition(
        "cholera",
        "Cholera",
        "Waterborne / enteric",
        (r"\bcholera\b", r"acute watery diarrhoea", r"acute watery diarrhoeal"),
    ),
    DiseaseDefinition(
        "typhoid",
        "Typhoid fever",
        "Waterborne / enteric",
        (r"typhoid", r"salmonella typhi"),
    ),
    DiseaseDefinition(
        "hepatitis",
        "Hepatitis",
        "Waterborne / enteric",
        (r"hepatitis",),
    ),
    DiseaseDefinition(
        "shigella",
        "Shigellosis",
        "Waterborne / enteric",
        (r"shigell", r"dysentery"),
    ),
    DiseaseDefinition(
        "foodborne",
        "Food-borne illness",
        "Waterborne / enteric",
        (r"food.?borne", r"listeriosis", r"\be\.? ?coli\b", r"botulism", r"intoxication"),
    ),
    DiseaseDefinition(
        "polio",
        "Poliomyelitis",
        "Vaccine-preventable",
        (r"\bpolio", r"poliovirus"),
    ),
    DiseaseDefinition(
        "measles",
        "Measles",
        "Vaccine-preventable",
        (r"\bmeasles\b",),
    ),
    DiseaseDefinition(
        "diphtheria",
        "Diphtheria",
        "Vaccine-preventable",
        (r"diphtheria",),
    ),
    DiseaseDefinition(
        "pertussis",
        "Pertussis",
        "Vaccine-preventable",
        (r"pertussis", r"whooping cough"),
    ),
    DiseaseDefinition(
        "rubella",
        "Rubella",
        "Vaccine-preventable",
        (r"rubella",),
    ),
    DiseaseDefinition(
        "meningococcal",
        "Meningococcal disease",
        "Bacterial",
        (r"meningococc", r"meningitis"),
    ),
    DiseaseDefinition(
        "plague",
        "Plague",
        "Bacterial",
        (r"\bplague\b", r"yersinia pestis"),
    ),
    DiseaseDefinition(
        "anthrax",
        "Anthrax",
        "Bacterial",
        (r"anthrax",),
    ),
    DiseaseDefinition(
        "leptospirosis",
        "Leptospirosis",
        "Bacterial",
        (r"leptospir",),
    ),
    DiseaseDefinition(
        "legionella",
        "Legionellosis",
        "Bacterial",
        (r"legionell",),
    ),
    DiseaseDefinition(
        "tuberculosis",
        "Tuberculosis",
        "Bacterial",
        (r"tuberculosis", r"\bxdr.?tb\b", r"\bmdr.?tb\b"),
    ),
    DiseaseDefinition(
        "mpox",
        "Mpox",
        "Other viral",
        (r"\bmpox\b", r"monkeypox"),
    ),
    DiseaseDefinition(
        "nipah",
        "Nipah virus infection",
        "Other viral",
        (r"\bnipah\b",),
    ),
    DiseaseDefinition(
        "hantavirus",
        "Hantavirus infection",
        "Other viral",
        (r"hantavirus", r"hantaan"),
    ),
    DiseaseDefinition(
        "rabies",
        "Rabies",
        "Other viral",
        (r"\brabies\b",),
    ),
    DiseaseDefinition(
        "encephalitis",
        "Acute encephalitis syndrome",
        "Other viral",
        (r"encephalitis", r"acute neurological syndrome"),
    ),
    DiseaseDefinition(
        "hfmd",
        "Hand, foot and mouth disease",
        "Other viral",
        (r"hand,? foot and mouth", r"enterovirus"),
    ),
    DiseaseDefinition(
        "chemical",
        "Chemical or environmental event",
        "Non-infectious event",
        (r"\blead poisoning\b", r"chemical", r"radiat", r"methanol", r"contamination"),
    ),
    DiseaseDefinition(
        "disaster",
        "Natural disaster health response",
        "Non-infectious event",
        (r"hurricane", r"earthquake", r"\bflood", r"tsunami", r"cyclone", r"volcan"),
    ),
    DiseaseDefinition(
        "antimicrobial_resistance",
        "Antimicrobial resistance",
        "Other",
        (r"resistan",),
    ),
    DiseaseDefinition(
        "respiratory_undetermined",
        "Undiagnosed respiratory illness",
        "Other",
        (
            r"pneumonia of (?:undetermined|unknown)",
            r"respiratory illness of unknown",
            r"acute respiratory syndrome",
            r"respiratory illnesses",
            r"\bpneumonia\b",
        ),
    ),
    DiseaseDefinition(
        "diarrhoeal",
        "Acute diarrhoeal disease",
        "Waterborne / enteric",
        (r"diarrhoeal", r"diarrheal", r"gastroenteritis"),
    ),
    DiseaseDefinition(
        "neuro_syndrome",
        "Neurological syndrome",
        "Other",
        (r"guillain.?barr", r"microcephaly", r"neurological syndrome", r"\bparalysis\b"),
    ),
    DiseaseDefinition(
        "zoonotic_bacterial",
        "Other zoonotic bacterial infection",
        "Bacterial",
        (
            r"tularemia",
            r"tularaemia",
            r"psittacosis",
            r"streptococcus",
            r"brucell",
            r"glanders",
            r"melioidosis",
        ),
    ),
    DiseaseDefinition(
        "arenavirus",
        "Arenavirus infection",
        "Viral haemorrhagic fever",
        (r"arenavir", r"lujo"),
    ),
    DiseaseDefinition(
        "febrile_illness",
        "Acute febrile illness",
        "Other",
        (r"febrile illness", r"fever of unknown"),
    ),
    DiseaseDefinition(
        "undiagnosed",
        "Undiagnosed illness",
        "Other",
        (r"undiagnosed", r"unknown (?:disease|illness|aetiology|etiology)", r"unexplained"),
    ),
)

_COMPILED: Final[tuple[tuple[DiseaseDefinition, tuple[re.Pattern[str], ...]], ...]] = tuple(
    (definition, tuple(re.compile(p, re.IGNORECASE) for p in definition.patterns))
    for definition in DEFINITIONS
)

BY_KEY: Final[MappingProxyType[str, DiseaseDefinition]] = MappingProxyType(
    {definition.key: definition for definition in DEFINITIONS}
)

OTHER_KEY: Final = "other"
OTHER_NAME: Final = "Other or unclassified event"
OTHER_FAMILY: Final = "Other"


def clean_title(title: str) -> str:
    text = _WHITESPACE.sub(" ", title or "").strip()
    text = _YEAR_PREFIX.sub("", text)
    return _UPDATE_SUFFIX.sub("", text).strip(" -–—,;:")


def extract_label(title: str) -> str | None:
    """The disease as the source words it, with year and country stripped."""
    text = clean_title(title)
    if not text:
        return None
    for separator in _SEPARATORS:
        if separator in text:
            head = text.split(separator, 1)[0].strip(" -–—,;:")
            if len(head) >= 3:
                text = head
                break
    text = _IN_COUNTRY.sub("", text).strip(" -–—,;:")
    return text or None


def classify(*candidates: str | None) -> DiseaseDefinition | None:
    """First canonical disease whose pattern appears in any candidate string."""
    haystack = " || ".join(c for c in candidates if c)
    if not haystack:
        return None
    for definition, patterns in _COMPILED:
        if any(pattern.search(haystack) for pattern in patterns):
            return definition
    return None


def resolve(title: str, *, label: str | None = None) -> tuple[str, str, str, str | None]:
    """Return ``(key, name, family, source_label)`` for one report title."""
    source_label = label or extract_label(title)
    definition = classify(source_label, clean_title(title))
    if definition is None:
        return OTHER_KEY, OTHER_NAME, OTHER_FAMILY, source_label
    return definition.key, definition.name, definition.family, source_label
