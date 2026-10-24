r"""The validation gate: does the source text actually support this value?

Structured extraction returns well-formed JSON. Well-formed is not correct.
This module is what stands between an extractor's output and a number EpiRoute
is willing to publish or feed into a model.

**Why four checks rather than one.** The design is driven by a real TinyFish
Agent response over WHO DON 2026-DON622, saved at
``tests/fixtures/tinyfish/agent_run_don622_completed.json``. Of its eight
extracted rows, only one survives unmodified. Each check exists because that
response failed it:

1. :func:`check_evidence_grounded` — the quoted sentence must appear in the
   retrieved text. Catches an invented quote. (Two rows cited sentences that
   differ from the source once whitespace is normalised.)
2. **Value grounding** — the number must appear somewhere in the retrieved
   text. Catches outright fabrication. (``cases_suspected = 9291`` and
   ``= 123`` appear nowhere in the document.)
3. **Evidence-local grounding** — the number must appear in *its own* quoted
   sentence. Catches a number borrowed from elsewhere in the page.
   (``deaths = 4687`` was attached to a sentence about 67 new cases.)
4. :func:`check_label_proximity` — the number must sit next to wording
   appropriate to its field. This is the check that catches the errors the
   others cannot, because the numbers are real and the quotes are real but the
   *assignment* is wrong:

   * "...2595 **recoveries**" extracted as ``cases_suspected``.
   * "976 confirmed **cases**, including 482 confirmed **deaths**" extracted
     with the two swapped.
   * "Haut-Uélé (89.9%; **1286**/1430)", a vaccination-coverage ratio,
     extracted as ``cases_confirmed``.

**Number formatting.** Sources write the same quantity as ``1234``, ``1,234``,
``1 234`` (including a non-breaking or narrow space) and ``1.234``. All are
accepted as the same value, because rejecting a correct number over a thousands
separator would discard real data.

**Outcome, not deletion.** A failing field is recorded with its verdict and
excluded from model inputs; the record and its source link are still stored, so
a rejected extraction remains auditable (AGENTS.md section 9.2).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum

# Characters used as thousands separators in the sources EpiRoute reads.
# U+00A0 no-break space, U+202F narrow no-break space, U+2009 thin space.
_SEPARATORS = ",.    '’"

_WHITESPACE = re.compile(r"\s+")

# How far from the number to look for a field-appropriate label, in characters.
# Wide enough for "7040 cumulative confirmed cases" (30) but not so wide that a
# label from an adjacent clause counts.
LABEL_WINDOW = 44

# Wording that identifies what a number counts. Ordered longest-first per field
# so that a specific phrase is preferred over a generic one.
FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "cases_confirmed": ("confirmed case", "laboratory-confirmed case", "confirmed", "case"),
    "cases_probable": ("probable case", "probable"),
    "cases_suspected": ("suspected case", "suspect case", "suspected"),
    "deaths": ("death", "died", "fatalit", "deceased", "mortalit"),
}

# Wording that, if it sits closer to the number than the field's own label,
# means the number counts something else entirely. These are the words that
# produced the real misassignments listed in the module docstring.
CONFLICTING_LABELS: dict[str, tuple[str, ...]] = {
    "cases_confirmed": (
        "death",
        "recover",
        "discharge",
        "vaccinat",
        "coverage",
        "contact",
        "sample",
        "test",
    ),
    "cases_probable": ("death", "recover", "confirmed", "suspected"),
    "cases_suspected": ("death", "recover", "discharge", "confirmed", "vaccinat", "coverage"),
    "deaths": ("case", "recover", "discharge", "vaccinat", "coverage", "contact", "sample"),
}


class Verdict(StrEnum):
    """Result of grounding one field."""

    GROUNDED = "grounded"
    """Found in the source text, in its own evidence, with appropriate wording."""

    GROUNDED_WEAK = "grounded_weak"
    """Found in the source text but not in the quoted evidence sentence."""

    LABEL_MISMATCH = "label_mismatch"
    """Found in the evidence, but the surrounding wording describes something else."""

    NOT_IN_EVIDENCE = "not_in_evidence"
    """Not present in the quoted evidence sentence."""

    NOT_IN_SOURCE = "not_in_source"
    """Not present anywhere in the retrieved source text: fabricated."""

    NO_EVIDENCE_PROVIDED = "no_evidence_provided"
    """The extractor supplied no quote to check against."""

    @property
    def is_usable(self) -> bool:
        """Whether a value with this verdict may feed a model input.

        Only fully grounded values qualify. ``GROUNDED_WEAK`` does not: the
        number exists in the document but nothing ties it to the place and
        period the row claims.
        """
        return self is Verdict.GROUNDED


@dataclass(frozen=True, slots=True)
class FieldVerdict:
    """Grounding outcome for one numeric field.

    Attributes:
        field_name: Name of the extracted field.
        value: The value that was checked.
        verdict: The outcome.
        detail: Human-readable explanation, shown in the UI for rejected values.
        matched_context: The source text around the match, for an auditor.
    """

    field_name: str
    value: int
    verdict: Verdict
    detail: str
    matched_context: str | None = None

    @property
    def is_usable(self) -> bool:
        """Whether this field may feed a model input."""
        return self.verdict.is_usable


@dataclass(frozen=True, slots=True)
class GroundingReport:
    """Grounding outcome for one extracted record.

    Attributes:
        evidence_grounded: Whether the quoted sentence is in the source text.
        evidence_detail: Explanation when it is not.
        fields: Per-field verdicts.
    """

    evidence_grounded: bool
    evidence_detail: str
    fields: tuple[FieldVerdict, ...] = field(default=())

    @property
    def usable_fields(self) -> dict[str, int]:
        """The subset of values that may feed a model input."""
        return {v.field_name: v.value for v in self.fields if v.is_usable}

    @property
    def rejected_fields(self) -> tuple[FieldVerdict, ...]:
        """Fields that failed grounding."""
        return tuple(v for v in self.fields if not v.is_usable)

    @property
    def all_grounded(self) -> bool:
        """Whether the evidence and every field passed."""
        return self.evidence_grounded and all(v.is_usable for v in self.fields)

    @property
    def any_grounded(self) -> bool:
        """Whether at least one field passed."""
        return bool(self.usable_fields)

    def to_detail(self) -> dict[str, object]:
        """Serialise for the ``grounding_detail`` JSONB column."""
        return {
            "evidence_grounded": self.evidence_grounded,
            "evidence_detail": self.evidence_detail,
            "fields": [
                {
                    "field": v.field_name,
                    "value": v.value,
                    "verdict": v.verdict.value,
                    "detail": v.detail,
                    "context": v.matched_context,
                }
                for v in self.fields
            ],
        }


def normalise_text(text: str) -> str:
    """Normalise text for substring comparison.

    Applies Unicode NFKC (so a narrow no-break space becomes a normal one and
    full-width digits become ASCII), collapses all whitespace runs to a single
    space, and lowercases. Markdown emphasis markers are removed because
    TinyFish Fetch returns markdown while the WHO API returns HTML, and the
    same sentence must compare equal from either path.

    Example:
        >>> normalise_text("Ituri  remains\\nthe **epicentre**.")
        'ituri remains the epicentre.'
    """
    folded = unicodedata.normalize("NFKC", text)
    without_emphasis = folded.replace("**", "").replace("__", "").replace("*", "")
    return _WHITESPACE.sub(" ", without_emphasis).strip().casefold()


def number_variants(value: int) -> tuple[str, ...]:
    """Return the written forms a source might use for ``value``.

    Covers the plain digits plus every thousands-separator style EpiRoute has
    seen: comma, period, and the three space characters used in European
    typography.

    Example:
        >>> number_variants(1234)
        ('1234', '1,234', '1.234', '1\\xa0234', '1\\u202f234', '1\\u2009234', '1 234')
        >>> number_variants(42)
        ('42',)
    """
    plain = str(value)
    if len(plain) <= 3:
        return (plain,)

    grouped: list[str] = []
    digits = plain
    while len(digits) > 3:
        grouped.insert(0, digits[-3:])
        digits = digits[:-3]
    grouped.insert(0, digits)

    return (plain, *(sep.join(grouped) for sep in (",", ".", " ", " ", " ", " ")))


def _is_standalone_number(haystack: str, start: int, length: int) -> bool:
    """Whether the match at ``start`` is a whole number, not part of a longer one.

    A plain digit on either side disqualifies it, as does a separator that
    itself has a digit on its far side: searching for ``234`` must not match
    inside ``1,234``, and searching for ``1`` must not match the first group of
    ``1 234``. An ordinary space before or after a number is of course fine,
    which is why the separator case needs the extra look-ahead rather than
    treating every separator as part of a number.
    """
    end = start + length
    before = haystack[start - 1] if start > 0 else ""
    before_before = haystack[start - 2] if start > 1 else ""
    after = haystack[end] if end < len(haystack) else ""
    after_after = haystack[end + 1] if end + 1 < len(haystack) else ""

    if before.isdigit() or after.isdigit():
        return False
    if before in _SEPARATORS and before_before.isdigit():
        return False
    return not (after in _SEPARATORS and after_after.isdigit())


def _find_number(haystack: str, value: int) -> int:
    """Return the index of ``value`` in ``haystack``, or -1.

    Matches must sit on number boundaries, so searching for 76 does not match
    inside 9704. This matters: WHO narratives are dense with numbers and a bare
    substring match would ground almost anything.
    """
    for variant in number_variants(value):
        normalised = normalise_text(variant)
        start = 0
        while (index := haystack.find(normalised, start)) != -1:
            if _is_standalone_number(haystack, index, len(normalised)):
                return index
            start = index + 1
    return -1


def check_evidence_grounded(evidence: str | None, source_text: str) -> tuple[bool, str]:
    """Check that the quoted evidence appears in the retrieved source text.

    Args:
        evidence: The sentence the extractor claims a value came from.
        source_text: The retrieved document text.

    Returns:
        ``(grounded, detail)``. A missing or very short quote is not grounded:
        a two-word fragment would match almost any document.

    Example:
        >>> check_evidence_grounded("Tshopo has recorded 76 cases and 27 deaths.",
        ...                         "Elsewhere, Tshopo has recorded 76 cases and 27 deaths.")
        (True, 'evidence found verbatim in the source text')

        A quote truncated at a natural break, with a full stop appended, is
        still grounded: every word appears in order in the source.

        >>> check_evidence_grounded("Tshopo has recorded 76 cases.",
        ...                         "Elsewhere, Tshopo has recorded 76 cases and 27 deaths.")[0]
        True

        A quote with invented wording is not:

        >>> check_evidence_grounded("Tshopo has recorded 76 fatal cases overall.",
        ...                         "Elsewhere, Tshopo has recorded 76 cases and 27 deaths.")[0]
        False
        >>> grounded, detail = check_evidence_grounded("Invented sentence here.", "Real text.")
        >>> grounded
        False
    """
    if not evidence or not evidence.strip():
        return False, "no evidence quote was supplied"

    normalised_evidence = normalise_text(evidence)
    # Below this length a quote carries too little information to ground
    # anything. Chosen so that a short real sentence like "Tshopo has recorded
    # 76 cases." (29 chars) still qualifies.
    if len(normalised_evidence) < 20:
        return False, f"evidence quote is too short to verify ({len(normalised_evidence)} chars)"

    normalised_source = normalise_text(source_text)
    if normalised_source.find(normalised_evidence) != -1:
        return True, "evidence found verbatim in the source text"

    # Extractors routinely truncate a sentence at a natural break and append a
    # full stop: the saved Agent response quotes "Nord Kivu follows with 2146
    # confirmed cases and 1199 deaths." where the source continues ", and
    # continues to record the highest provincial CFR". The numbers are correct
    # and rejecting them would discard real data, so trailing sentence
    # punctuation is ignored. This cannot admit fabricated content: every word
    # must still appear, in order, in the source.
    trimmed = normalised_evidence.rstrip(".;,: ")
    if trimmed != normalised_evidence and normalised_source.find(trimmed) != -1:
        return True, "evidence found in the source text, ignoring a truncated sentence ending"

    return False, "evidence quote does not appear in the retrieved source text"


def check_label_proximity(
    value: int, field_name: str, evidence: str
) -> tuple[bool, str, str | None]:
    """Check that wording near the number matches what the field claims to count.

    Looks in a :data:`LABEL_WINDOW` character window around the number for one
    of the field's own labels and for any conflicting label. The number passes
    only when its own label is found and is at least as close as the nearest
    conflicting one.

    Args:
        value: The extracted number.
        field_name: The field it was assigned to.
        evidence: The sentence to inspect.

    Returns:
        ``(passed, detail, context)`` where ``context`` is the inspected window.

    Example:
        A correct assignment:

        >>> ok, _, _ = check_label_proximity(
        ...     76, "cases_confirmed", "Tshopo has recorded 76 cases and 27 deaths.")
        >>> ok
        True

        The real swap from the saved Agent response — 976 is followed by
        "confirmed cases", so assigning it to deaths fails:

        >>> ok, detail, _ = check_label_proximity(
        ...     976, "deaths",
        ...     "An additional 976 confirmed cases, including 482 confirmed deaths, "
        ...     "have been reported.")
        >>> ok
        False
        >>> "case" in detail
        True

        And a vaccination-coverage ratio is not a case count:

        >>> ok, _, _ = check_label_proximity(
        ...     1286, "cases_confirmed", "Four provinces were below the threshold: "
        ...     "Haut-Uele (89.9%; 1286/1430)")
        >>> ok
        False
    """
    labels = FIELD_LABELS.get(field_name)
    if labels is None:
        # A field with no label vocabulary cannot be checked this way; treat it
        # as passing so the check never silently rejects an unknown field.
        return True, f"no label vocabulary defined for '{field_name}'", None

    normalised = normalise_text(evidence)
    index = _find_number(normalised, value)
    if index == -1:
        return False, "number not present in the evidence sentence", None

    start = max(0, index - LABEL_WINDOW)
    end = min(len(normalised), index + len(str(value)) + LABEL_WINDOW)
    window = normalised[start:end]
    number_position = index - start

    def nearest(candidates: tuple[str, ...]) -> int | None:
        """Distance from the number to the closest listed phrase, or None."""
        best: int | None = None
        for phrase in candidates:
            search_from = 0
            while (at := window.find(phrase, search_from)) != -1:
                distance = abs(at - number_position)
                if best is None or distance < best:
                    best = distance
                search_from = at + 1
        return best

    own = nearest(labels)
    conflicting = nearest(CONFLICTING_LABELS.get(field_name, ()))

    if own is None:
        found = ", ".join(
            sorted({c for c in CONFLICTING_LABELS.get(field_name, ()) if c in window})
        )
        detail = f"no wording for '{field_name}' within {LABEL_WINDOW} characters of the number" + (
            f"; nearby wording instead describes: {found}" if found else ""
        )
        return False, detail, window
    if conflicting is not None and conflicting < own:
        closer = next((c for c in CONFLICTING_LABELS[field_name] if c in window), "other wording")
        detail = (
            f"wording for '{closer}' sits closer to the number than wording for "
            f"'{field_name}', so the value appears to have been assigned to the wrong field"
        )
        return False, detail, window
    return True, f"wording for '{field_name}' found beside the number", window


def ground_record(
    values: dict[str, int | None],
    evidence: str | None,
    source_text: str,
) -> GroundingReport:
    """Run the full gate over one extracted record.

    Args:
        values: Extracted numeric fields. ``None`` values are skipped, because
            "not stated" needs no grounding.
        evidence: The sentence the extractor quoted.
        source_text: The retrieved document text, the single reference for
            every check.

    Returns:
        A :class:`GroundingReport` whose ``usable_fields`` are the only values
        a caller may feed into a model.

    Example:
        >>> source = ("Ituri remains the epicentre, with 7040 cumulative confirmed "
        ...           "cases and 3271 deaths.")
        >>> report = ground_record(
        ...     {"cases_confirmed": 7040, "deaths": 3271, "cases_suspected": 9291},
        ...     evidence=source, source_text=source)
        >>> sorted(report.usable_fields)
        ['cases_confirmed', 'deaths']
        >>> [v.verdict.value for v in report.rejected_fields]
        ['not_in_source']
    """
    evidence_grounded, evidence_detail = check_evidence_grounded(evidence, source_text)
    normalised_source = normalise_text(source_text)

    verdicts: list[FieldVerdict] = []
    for field_name, value in values.items():
        if value is None:
            continue

        if _find_number(normalised_source, value) == -1:
            verdicts.append(
                FieldVerdict(
                    field_name=field_name,
                    value=value,
                    verdict=Verdict.NOT_IN_SOURCE,
                    detail=(
                        "the number does not appear anywhere in the retrieved source "
                        "text, in any thousands-separator form"
                    ),
                )
            )
            continue

        if not evidence_grounded:
            verdicts.append(
                FieldVerdict(
                    field_name=field_name,
                    value=value,
                    verdict=Verdict.NO_EVIDENCE_PROVIDED if not evidence else Verdict.GROUNDED_WEAK,
                    detail=(
                        f"the number is in the source text, but its evidence quote "
                        f"could not be verified ({evidence_detail})"
                    ),
                )
            )
            continue

        assert evidence is not None  # evidence_grounded implies a quote exists
        if _find_number(normalise_text(evidence), value) == -1:
            verdicts.append(
                FieldVerdict(
                    field_name=field_name,
                    value=value,
                    verdict=Verdict.NOT_IN_EVIDENCE,
                    detail=(
                        "the number is in the source document but not in the sentence "
                        "this record cites, so nothing ties it to this place and period"
                    ),
                )
            )
            continue

        passed, detail, context = check_label_proximity(value, field_name, evidence)
        verdicts.append(
            FieldVerdict(
                field_name=field_name,
                value=value,
                verdict=Verdict.GROUNDED if passed else Verdict.LABEL_MISMATCH,
                detail=detail,
                matched_context=context,
            )
        )

    return GroundingReport(
        evidence_grounded=evidence_grounded,
        evidence_detail=evidence_detail,
        fields=tuple(verdicts),
    )
