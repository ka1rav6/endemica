from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from epiroute.datasets.iso import resolve
from epiroute.ingestion.grounding import GroundingReport, ground_record
from epiroute.schemas.common import ExtractionStatus, ValueType
from epiroute.tinyfish.schemas import ExtractedLocation

_PERIOD_CLEAN = re.compile(r"\s+")
MAX_PERIOD_TEXT = 240
MAX_EVIDENCE_TEXT = 1200
MAX_SUBNATIONAL = 240

_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


@dataclass(frozen=True, slots=True)
class ValidatedObservation:
    country_iso3: str
    country_name_as_reported: str | None
    subnational_name: str | None
    cases_confirmed: int | None
    cases_probable: int | None
    cases_suspected: int | None
    deaths: int | None
    period_start: date | None
    period_end: date | None
    period_text: str | None
    evidence_text: str | None
    grounding_status: ExtractionStatus
    grounding_detail: dict[str, object]
    value_type: ValueType

    @property
    def has_any_count(self) -> bool:
        return any(
            v is not None
            for v in (self.cases_confirmed, self.cases_probable, self.cases_suspected, self.deaths)
        )


@dataclass(slots=True)
class ValidationOutcome:
    observations: list[ValidatedObservation] = field(default_factory=list)
    warnings: list[dict[str, object]] = field(default_factory=list)

    @property
    def verified_count(self) -> int:
        return sum(1 for o in self.observations if o.grounding_status is ExtractionStatus.VERIFIED)

    @property
    def unverified_count(self) -> int:
        return len(self.observations) - self.verified_count


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    cleaned = _PERIOD_CLEAN.sub(" ", text).strip()
    if not cleaned:
        return None
    return cleaned[:limit]


def _parse_period(text: str | None) -> tuple[date | None, date | None]:
    if not text:
        return None, None
    matches = _ISO_DATE.findall(text)
    parsed: list[date] = []
    for year, month, day in matches[:2]:
        try:
            parsed.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    if not parsed:
        return None, None
    if len(parsed) == 1:
        return parsed[0], parsed[0]
    return min(parsed), max(parsed)


def _status_from_report(report: GroundingReport) -> ExtractionStatus:
    if not report.fields:
        return ExtractionStatus.NOT_ATTEMPTED
    if report.all_grounded:
        return ExtractionStatus.VERIFIED
    if report.any_grounded:
        return ExtractionStatus.PARTIAL
    return ExtractionStatus.UNVERIFIED


def validate_location(
    location: ExtractedLocation,
    *,
    source_text: str,
    report_published_at: datetime | None,
    fallback_iso3: str | None = None,
) -> tuple[ValidatedObservation | None, list[dict[str, object]]]:
    warnings: list[dict[str, object]] = []

    iso3 = resolve(location.country) or fallback_iso3
    if iso3 is None:
        warnings.append(
            {
                "code": "unresolved_country",
                "message": f"could not resolve country {location.country!r} to an ISO-3 code",
                "country_as_reported": location.country,
            }
        )
        return None, warnings

    report = ground_record(
        location.numeric_fields(), evidence=location.evidence, source_text=source_text
    )
    usable = report.usable_fields

    for rejected in report.rejected_fields:
        warnings.append(
            {
                "code": f"grounding_{rejected.verdict.value}",
                "message": rejected.detail,
                "field": rejected.field_name,
                "value": rejected.value,
                "country": iso3,
            }
        )

    confirmed = usable.get("cases_confirmed")
    probable = usable.get("cases_probable")
    suspected = usable.get("cases_suspected")
    deaths = usable.get("deaths")

    for name, value in (
        ("cases_confirmed", confirmed),
        ("cases_probable", probable),
        ("cases_suspected", suspected),
        ("deaths", deaths),
    ):
        if value is not None and value < 0:
            warnings.append(
                {"code": "negative_count", "message": f"{name} was negative", "field": name}
            )
            if name == "cases_confirmed":
                confirmed = None
            elif name == "cases_probable":
                probable = None
            elif name == "cases_suspected":
                suspected = None
            else:
                deaths = None

    if deaths is not None and confirmed is not None and deaths > confirmed:
        total_cases = confirmed + (probable or 0) + (suspected or 0)
        if deaths > total_cases:
            warnings.append(
                {
                    "code": "deaths_exceed_cases",
                    "message": (
                        f"{deaths} deaths exceed {total_cases} total cases; both values "
                        f"retained but the pair is flagged"
                    ),
                    "country": iso3,
                }
            )

    period_start, period_end = _parse_period(location.period)
    if report_published_at is not None and period_end is not None:
        published_date = report_published_at.date()
        if period_end > published_date:
            warnings.append(
                {
                    "code": "period_after_publication",
                    "message": f"period end {period_end} is after publication {published_date}",
                    "country": iso3,
                }
            )
            period_start, period_end = None, None

    status = _status_from_report(report)
    value_type = ValueType.OBSERVED if status is ExtractionStatus.VERIFIED else ValueType.UNKNOWN

    observation = ValidatedObservation(
        country_iso3=iso3,
        country_name_as_reported=_truncate(location.country, 256),
        subnational_name=_truncate(location.subnational, MAX_SUBNATIONAL),
        cases_confirmed=confirmed,
        cases_probable=probable,
        cases_suspected=suspected,
        deaths=deaths,
        period_start=period_start,
        period_end=period_end,
        period_text=_truncate(location.period, MAX_PERIOD_TEXT),
        evidence_text=_truncate(location.evidence, MAX_EVIDENCE_TEXT),
        grounding_status=status,
        grounding_detail=report.to_detail(),
        value_type=value_type,
    )
    return observation, warnings


def validate_extraction(
    locations: list[ExtractedLocation],
    *,
    source_text: str,
    report_published_at: datetime | None,
    fallback_iso3: str | None = None,
) -> ValidationOutcome:
    outcome = ValidationOutcome()
    best: dict[tuple[str, str | None, str | None], ValidatedObservation] = {}
    collapsed: dict[tuple[str, str | None, str | None], int] = {}

    for location in locations:
        observation, warnings = validate_location(
            location,
            source_text=source_text,
            report_published_at=report_published_at,
            fallback_iso3=fallback_iso3,
        )
        outcome.warnings.extend(warnings)
        if observation is None:
            continue

        key = (observation.country_iso3, observation.subnational_name, observation.period_text)
        incumbent = best.get(key)
        if incumbent is None:
            best[key] = observation
            continue

        collapsed[key] = collapsed.get(key, 0) + 1
        if _inclusiveness(observation) > _inclusiveness(incumbent):
            best[key] = observation

    for key, count in collapsed.items():
        outcome.warnings.append(
            {
                "code": "observations_collapsed",
                "message": (
                    f"{count} further observation(s) for this place and period were "
                    f"discarded in favour of the most inclusive figure; counts are never "
                    f"summed because a report may mix national totals with sub-national "
                    f"breakdowns"
                ),
                "country": key[0],
                "subnational": key[1],
                "discarded": count,
            }
        )

    outcome.observations.extend(best.values())
    return outcome


def _inclusiveness(observation: ValidatedObservation) -> tuple[int, int, int]:
    return (
        observation.cases_confirmed if observation.cases_confirmed is not None else -1,
        observation.cases_suspected if observation.cases_suspected is not None else -1,
        observation.deaths if observation.deaths is not None else -1,
    )
