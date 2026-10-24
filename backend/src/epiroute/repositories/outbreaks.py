from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.elements import ColumnElement

from epiroute.db.models import IngestionRun, OutbreakObservation, OutbreakReport
from epiroute.ingestion.parser import find_outbreak_start
from epiroute.schemas.common import ExtractionStatus


@dataclass(frozen=True, slots=True)
class CumulativePoint:
    published_at: datetime
    cases_confirmed: int | None
    deaths: int | None
    report_identifier: str
    report_url: str
    outbreak_started_on: date | None = None


def get_report(session: Session, report_id: str) -> OutbreakReport | None:
    import uuid

    try:
        parsed = uuid.UUID(report_id)
    except ValueError:
        return session.scalar(
            select(OutbreakReport)
            .options(selectinload(OutbreakReport.observations))
            .where(OutbreakReport.source_identifier == report_id)
        )
    return session.scalar(
        select(OutbreakReport)
        .options(selectinload(OutbreakReport.observations))
        .where(OutbreakReport.id == parsed)
    )


def list_reports(
    session: Session,
    *,
    pathogen_key: str | None = None,
    country_iso3: str | None = None,
    since: datetime | None = None,
    status: ExtractionStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[OutbreakReport]:
    statement = (
        select(OutbreakReport)
        .options(selectinload(OutbreakReport.observations))
        .order_by(OutbreakReport.published_at.desc().nullslast())
    )
    if pathogen_key:
        statement = statement.where(OutbreakReport.pathogen_key == pathogen_key)
    if since:
        statement = statement.where(OutbreakReport.published_at >= since)
    if status:
        statement = statement.where(OutbreakReport.extraction_status == status)
    if country_iso3:
        statement = statement.where(
            OutbreakReport.id.in_(
                select(OutbreakObservation.report_id).where(
                    OutbreakObservation.country_iso3 == country_iso3.upper()
                )
            )
        )
    return list(session.scalars(statement.limit(limit).offset(offset)))


def count_reports(
    session: Session,
    *,
    pathogen_key: str | None = None,
    country_iso3: str | None = None,
    since: datetime | None = None,
    status: ExtractionStatus | None = None,
) -> int:
    statement = select(func.count()).select_from(OutbreakReport)
    if pathogen_key:
        statement = statement.where(OutbreakReport.pathogen_key == pathogen_key)
    if since:
        statement = statement.where(OutbreakReport.published_at >= since)
    if status:
        statement = statement.where(OutbreakReport.extraction_status == status)
    if country_iso3:
        statement = statement.where(
            OutbreakReport.id.in_(
                select(OutbreakObservation.report_id).where(
                    OutbreakObservation.country_iso3 == country_iso3.upper()
                )
            )
        )
    return session.scalar(statement) or 0


def _feeds_model() -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    """Rows whose stored counts were grounded and may enter a calculation.

    ``partial`` means at least one field passed grounding and the failing
    fields were discarded before storage. ``unverified`` means nothing stored
    was found in the source, so those rows stay out.
    """
    return (
        OutbreakObservation.grounding_status.in_(
            (ExtractionStatus.VERIFIED, ExtractionStatus.PARTIAL)
        ),
        or_(
            OutbreakObservation.cases_confirmed.is_not(None),
            OutbreakObservation.cases_probable.is_not(None),
            OutbreakObservation.cases_suspected.is_not(None),
            OutbreakObservation.deaths.is_not(None),
        ),
    )


def verified_observations_for_country(
    session: Session,
    country_iso3: str,
    *,
    pathogen_key: str | None = None,
    disease_label: str | None = None,
    disease_key: str | None = None,
) -> list[tuple[OutbreakObservation, OutbreakReport]]:
    """Grounded rows for one country.

    ``disease_key`` is the precise filter and wins outright: it groups the
    source's wording variants onto one disease. ``pathogen_key`` is only a
    parameter profile and several diseases share one, so it is used alone
    when no disease was identified.
    """
    statement = (
        select(OutbreakObservation, OutbreakReport)
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(OutbreakObservation.country_iso3 == country_iso3.upper(), *_feeds_model())
        .order_by(OutbreakReport.published_at.desc().nullslast())
    )
    if disease_key:
        statement = statement.where(OutbreakReport.disease_key == disease_key)
    else:
        if pathogen_key:
            statement = statement.where(OutbreakReport.pathogen_key == pathogen_key)
        if disease_label:
            statement = statement.where(
                func.lower(OutbreakReport.disease_label) == disease_label.casefold()
            )
    return [(obs, rep) for obs, rep in session.execute(statement)]


def cumulative_series(
    session: Session,
    country_iso3: str,
    pathogen_key: str,
    *,
    disease_label: str | None = None,
    disease_key: str | None = None,
) -> list[CumulativePoint]:
    rows = verified_observations_for_country(
        session,
        country_iso3,
        pathogen_key=pathogen_key,
        disease_label=disease_label,
        disease_key=disease_key,
    )
    by_report: dict[str, CumulativePoint] = {}
    for observation, report in rows:
        if report.published_at is None:
            continue
        existing = by_report.get(report.source_identifier)
        confirmed = observation.cases_confirmed
        deaths = observation.deaths
        if existing is not None:
            confirmed = _greater(existing.cases_confirmed, confirmed)
            deaths = _greater(existing.deaths, deaths)
        by_report[report.source_identifier] = CumulativePoint(
            published_at=report.published_at,
            cases_confirmed=confirmed,
            deaths=deaths,
            report_identifier=report.source_identifier,
            report_url=report.source_url,
            outbreak_started_on=find_outbreak_start(report.narrative_text or ""),
        )

    series = sorted(by_report.values(), key=lambda p: p.published_at)
    return _running_max(series)


def _greater(a: int | None, b: int | None) -> int | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


def _running_max(series: list[CumulativePoint]) -> list[CumulativePoint]:
    best_cases: int | None = None
    best_deaths: int | None = None
    out: list[CumulativePoint] = []
    for point in series:
        best_cases = _greater(best_cases, point.cases_confirmed)
        best_deaths = _greater(best_deaths, point.deaths)
        out.append(
            CumulativePoint(
                published_at=point.published_at,
                cases_confirmed=best_cases,
                deaths=best_deaths,
                report_identifier=point.report_identifier,
                report_url=point.report_url,
                outbreak_started_on=point.outbreak_started_on,
            )
        )
    return out


def countries_with_active_outbreaks(
    session: Session,
    *,
    pathogen_key: str | None = None,
    disease_label: str | None = None,
    disease_key: str | None = None,
    since: datetime | None = None,
) -> list[str]:
    statement = (
        select(OutbreakObservation.country_iso3)
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(*_feeds_model())
        .distinct()
    )
    if disease_key:
        statement = statement.where(OutbreakReport.disease_key == disease_key)
    else:
        if pathogen_key:
            statement = statement.where(OutbreakReport.pathogen_key == pathogen_key)
        if disease_label:
            statement = statement.where(
                func.lower(OutbreakReport.disease_label) == disease_label.casefold()
            )
    if since:
        statement = statement.where(OutbreakReport.published_at >= since)
    return list(session.scalars(statement))


def latest_run(session: Session) -> IngestionRun | None:
    return session.scalar(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(1))


def list_runs(session: Session, *, limit: int = 20) -> list[IngestionRun]:
    return list(
        session.scalars(select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit))
    )


@dataclass(frozen=True, slots=True)
class DiseaseRecord:
    disease_label: str
    pathogen_key: str | None
    country_count: int
    report_count: int
    latest_published_at: datetime | None


def list_diseases(session: Session) -> list[DiseaseRecord]:
    """Diseases that have at least one grounded count, newest first."""
    rows = session.execute(
        select(
            OutbreakReport.disease_label,
            OutbreakReport.pathogen_key,
            func.count(func.distinct(OutbreakObservation.country_iso3)),
            func.count(func.distinct(OutbreakReport.id)),
            func.max(OutbreakReport.published_at),
        )
        .join(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(*_feeds_model(), OutbreakReport.disease_label.is_not(None))
        .group_by(OutbreakReport.disease_label, OutbreakReport.pathogen_key)
        .order_by(func.max(OutbreakReport.published_at).desc().nullslast())
    )
    return [
        DiseaseRecord(
            disease_label=label,
            pathogen_key=pathogen_key,
            country_count=countries,
            report_count=reports,
            latest_published_at=published,
        )
        for label, pathogen_key, countries, reports, published in rows
        if label
    ]


def diseases_by_country(session: Session) -> dict[str, list[str]]:
    """Grounded disease names reported for each country."""
    rows = session.execute(
        select(OutbreakObservation.country_iso3, OutbreakReport.disease_label)
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(*_feeds_model(), OutbreakReport.disease_label.is_not(None))
        .distinct()
    )
    grouped: dict[str, list[str]] = {}
    for iso3, label in rows:
        if not label:
            continue
        names = grouped.setdefault(iso3, [])
        if label not in names:
            names.append(label)
    return grouped


def pathogen_key_for_disease(session: Session, disease_label: str) -> str | None:
    return session.scalar(
        select(OutbreakReport.pathogen_key)
        .where(
            func.lower(OutbreakReport.disease_label) == disease_label.casefold(),
            OutbreakReport.pathogen_key.is_not(None),
        )
        .order_by(OutbreakReport.published_at.desc().nullslast())
        .limit(1)
    )


def latest_disease_label(
    session: Session, pathogen_key: str | None, *, country_iso3: str | None = None
) -> str | None:
    statement = (
        select(OutbreakReport.disease_label)
        .where(OutbreakReport.disease_label.is_not(None))
        .order_by(OutbreakReport.published_at.desc().nullslast())
        .limit(1)
    )
    if pathogen_key:
        statement = statement.where(OutbreakReport.pathogen_key == pathogen_key)
    if country_iso3:
        statement = statement.where(
            OutbreakReport.id.in_(
                select(OutbreakObservation.report_id).where(
                    OutbreakObservation.country_iso3 == country_iso3.upper()
                )
            )
        )
    return session.scalar(statement)


def observation_counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(OutbreakObservation.grounding_status, func.count()).group_by(
            OutbreakObservation.grounding_status
        )
    )
    return {str(status.value): count for status, count in rows}


# ---------------------------------------------------------------------------
# Canonical-disease history
#
# Every query below groups on ``disease_key`` so that wording variants in the
# source titles ("Yellow fever", "Yellow Fever", "Yellow fever in Ghana")
# collapse into one disease. ``_feeds_model()`` still gates anything numeric;
# rows without a grounded count contribute location and dates only.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DiseaseFocus:
    disease_key: str | None
    disease_name: str | None
    disease_label: str | None
    pathogen_key: str | None
    published_at: datetime | None


_FocusRow = tuple[str | None, str | None, str | None, str | None, datetime | None]


def _focus_statement() -> Select[_FocusRow]:
    return (
        select(
            OutbreakReport.disease_key,
            OutbreakReport.disease_name,
            OutbreakReport.disease_label,
            OutbreakReport.pathogen_key,
            OutbreakReport.published_at,
        )
        .where(OutbreakReport.disease_key.is_not(None))
        .order_by(OutbreakReport.published_at.desc().nullslast())
        .limit(1)
    )


def latest_focus_for_country(session: Session, country_iso3: str) -> DiseaseFocus | None:
    """The most recent disease reported for one country.

    Used so that selecting a country shows the disease that country actually
    has, instead of whatever was published most recently anywhere.
    """
    statement = _focus_statement().where(
        OutbreakReport.id.in_(
            select(OutbreakObservation.report_id).where(
                OutbreakObservation.country_iso3 == country_iso3.upper()
            )
        )
    )
    row = session.execute(statement).first()
    if row is None:
        return None
    return DiseaseFocus(*row)


def latest_global_focus(session: Session) -> DiseaseFocus | None:
    row = session.execute(_focus_statement()).first()
    return DiseaseFocus(*row) if row is not None else None


def focus_for_disease(session: Session, disease_key: str) -> DiseaseFocus | None:
    row = session.execute(
        _focus_statement().where(OutbreakReport.disease_key == disease_key)
    ).first()
    return DiseaseFocus(*row) if row is not None else None


@dataclass(frozen=True, slots=True)
class DiseaseHistoryRecord:
    disease_key: str
    disease_name: str
    disease_family: str | None
    pathogen_key: str | None
    report_count: int
    country_count: int
    first_published_at: datetime | None
    last_published_at: datetime | None
    cases_confirmed: int | None
    deaths: int | None
    grounded_country_count: int
    source_labels: tuple[str, ...]


def list_disease_history(session: Session) -> list[DiseaseHistoryRecord]:
    """Every disease in the archive with its full span and footprint."""
    spans = session.execute(
        select(
            OutbreakReport.disease_key,
            func.max(OutbreakReport.disease_name),
            func.max(OutbreakReport.disease_family),
            func.count(OutbreakReport.id),
            func.min(OutbreakReport.published_at),
            func.max(OutbreakReport.published_at),
        )
        .where(OutbreakReport.disease_key.is_not(None))
        .group_by(OutbreakReport.disease_key)
    ).all()

    countries: dict[str | None, int] = {}
    for key, count in session.execute(
        select(
            OutbreakReport.disease_key,
            func.count(func.distinct(OutbreakObservation.country_iso3)),
        )
        .join(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(OutbreakReport.disease_key.is_not(None))
        .group_by(OutbreakReport.disease_key)
    ).all():
        countries[key] = count

    pathogens: dict[str | None, str | None] = {}
    for key, pathogen in session.execute(
        select(OutbreakReport.disease_key, func.max(OutbreakReport.pathogen_key))
        .where(
            OutbreakReport.disease_key.is_not(None),
            OutbreakReport.pathogen_key.is_not(None),
        )
        .group_by(OutbreakReport.disease_key)
    ).all():
        pathogens[key] = pathogen

    # Case counts are cumulative per report, so the per-country peak is the
    # right summary; summing reports would multiply-count the same outbreak.
    peaks = session.execute(
        select(
            OutbreakReport.disease_key,
            OutbreakObservation.country_iso3,
            func.max(OutbreakObservation.cases_confirmed),
            func.max(OutbreakObservation.deaths),
        )
        .join(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(OutbreakReport.disease_key.is_not(None), *_feeds_model())
        .group_by(OutbreakReport.disease_key, OutbreakObservation.country_iso3)
    ).all()

    cases: dict[str, int] = {}
    deaths: dict[str, int] = {}
    grounded: dict[str, set[str]] = {}
    for key, iso3, peak_cases, peak_deaths in peaks:
        grounded.setdefault(key, set()).add(iso3)
        if peak_cases is not None:
            cases[key] = cases.get(key, 0) + int(peak_cases)
        if peak_deaths is not None:
            deaths[key] = deaths.get(key, 0) + int(peak_deaths)

    labels: dict[str, list[str]] = {}
    for key, label in session.execute(
        select(OutbreakReport.disease_key, OutbreakReport.disease_label)
        .where(
            OutbreakReport.disease_key.is_not(None),
            OutbreakReport.disease_label.is_not(None),
        )
        .distinct()
    ).all():
        if label:
            labels.setdefault(key, []).append(label)

    records = [
        DiseaseHistoryRecord(
            disease_key=key,
            disease_name=name or key,
            disease_family=family,
            pathogen_key=pathogens.get(key),
            report_count=reports,
            country_count=countries.get(key, 0),
            first_published_at=first,
            last_published_at=last,
            cases_confirmed=cases.get(key),
            deaths=deaths.get(key),
            grounded_country_count=len(grounded.get(key, ())),
            source_labels=tuple(sorted(labels.get(key, []))[:8]),
        )
        for key, name, family, reports, first, last in spans
        if key
    ]
    records.sort(key=lambda r: r.report_count, reverse=True)
    return records


@dataclass(frozen=True, slots=True)
class CountrySpreadRecord:
    country_iso3: str
    report_count: int
    first_published_at: datetime | None
    last_published_at: datetime | None
    cases_confirmed: int | None
    deaths: int | None
    grounded: bool
    report_url: str | None
    report_title: str | None


def country_spread_for_disease(session: Session, disease_key: str) -> list[CountrySpreadRecord]:
    """Which countries a disease reached, when it arrived, and with what counts."""
    rows = session.execute(
        select(
            OutbreakObservation.country_iso3,
            func.count(func.distinct(OutbreakReport.id)),
            func.min(OutbreakReport.published_at),
            func.max(OutbreakReport.published_at),
        )
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(OutbreakReport.disease_key == disease_key)
        .group_by(OutbreakObservation.country_iso3)
    ).all()

    grounded = {
        iso3: (cases, deaths)
        for iso3, cases, deaths in session.execute(
            select(
                OutbreakObservation.country_iso3,
                func.max(OutbreakObservation.cases_confirmed),
                func.max(OutbreakObservation.deaths),
            )
            .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
            .where(OutbreakReport.disease_key == disease_key, *_feeds_model())
            .group_by(OutbreakObservation.country_iso3)
        ).all()
    }

    latest = {
        iso3: (url, title)
        for iso3, url, title in session.execute(
            select(
                OutbreakObservation.country_iso3,
                OutbreakReport.source_url,
                OutbreakReport.title,
            )
            .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
            .where(OutbreakReport.disease_key == disease_key)
            .order_by(OutbreakReport.published_at.asc().nullsfirst())
        ).all()
    }

    records: list[CountrySpreadRecord] = []
    for iso3, reports, first, last in rows:
        counts = grounded.get(iso3)
        url, title = latest.get(iso3, (None, None))
        records.append(
            CountrySpreadRecord(
                country_iso3=iso3,
                report_count=reports,
                first_published_at=first,
                last_published_at=last,
                cases_confirmed=int(counts[0]) if counts and counts[0] is not None else None,
                deaths=int(counts[1]) if counts and counts[1] is not None else None,
                grounded=iso3 in grounded,
                report_url=url,
                report_title=title,
            )
        )
    records.sort(key=lambda r: r.first_published_at or datetime.max)
    return records


@dataclass(frozen=True, slots=True)
class DiseaseTimelinePoint:
    year: int
    report_count: int
    country_count: int
    new_country_count: int
    cumulative_country_count: int
    new_countries: tuple[str, ...]
    cases_confirmed: int | None
    deaths: int | None


def disease_timeline(session: Session, disease_key: str) -> list[DiseaseTimelinePoint]:
    """Per-year reports, countries and newly reached countries for one disease."""
    rows = session.execute(
        select(
            OutbreakReport.published_at,
            OutbreakReport.id,
            OutbreakObservation.country_iso3,
            OutbreakObservation.cases_confirmed,
            OutbreakObservation.deaths,
            OutbreakObservation.grounding_status,
        )
        .outerjoin(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(
            OutbreakReport.disease_key == disease_key,
            OutbreakReport.published_at.is_not(None),
        )
        .order_by(OutbreakReport.published_at)
    ).all()

    years: dict[int, dict[str, Any]] = {}
    seen: set[str] = set()
    for published_at, report_id, iso3, cases, deaths, status in rows:
        bucket = years.setdefault(
            published_at.year,
            {"reports": set(), "countries": set(), "new": [], "cases": {}, "deaths": {}},
        )
        bucket["reports"].add(str(report_id))
        if not iso3:
            continue
        bucket["countries"].add(iso3)
        if iso3 not in seen:
            seen.add(iso3)
            bucket["new"].append(iso3)
        if status in (ExtractionStatus.VERIFIED, ExtractionStatus.PARTIAL):
            if cases is not None:
                bucket["cases"][iso3] = max(bucket["cases"].get(iso3, 0), int(cases))
            if deaths is not None:
                bucket["deaths"][iso3] = max(bucket["deaths"].get(iso3, 0), int(deaths))

    points: list[DiseaseTimelinePoint] = []
    running = 0
    for year in sorted(years):
        bucket = years[year]
        running += len(bucket["new"])
        points.append(
            DiseaseTimelinePoint(
                year=year,
                report_count=len(bucket["reports"]),
                country_count=len(bucket["countries"]),
                new_country_count=len(bucket["new"]),
                cumulative_country_count=running,
                new_countries=tuple(bucket["new"]),
                cases_confirmed=sum(bucket["cases"].values()) or None,
                deaths=sum(bucket["deaths"].values()) or None,
            )
        )
    return points


@dataclass(frozen=True, slots=True)
class CountryDiseaseRecord:
    disease_key: str
    disease_name: str
    disease_family: str | None
    pathogen_key: str | None
    report_count: int
    first_published_at: datetime | None
    last_published_at: datetime | None
    cases_confirmed: int | None
    deaths: int | None
    grounded: bool
    report_url: str | None


def diseases_for_country(session: Session, country_iso3: str) -> list[CountryDiseaseRecord]:
    """Every disease ever reported for one country, most recent activity first."""
    iso3 = country_iso3.upper()
    rows = session.execute(
        select(
            OutbreakReport.disease_key,
            func.max(OutbreakReport.disease_name),
            func.max(OutbreakReport.disease_family),
            func.max(OutbreakReport.pathogen_key),
            func.count(func.distinct(OutbreakReport.id)),
            func.min(OutbreakReport.published_at),
            func.max(OutbreakReport.published_at),
        )
        .join(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(
            OutbreakObservation.country_iso3 == iso3,
            OutbreakReport.disease_key.is_not(None),
        )
        .group_by(OutbreakReport.disease_key)
    ).all()

    grounded = {
        key: (cases, deaths)
        for key, cases, deaths in session.execute(
            select(
                OutbreakReport.disease_key,
                func.max(OutbreakObservation.cases_confirmed),
                func.max(OutbreakObservation.deaths),
            )
            .join(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
            .where(OutbreakObservation.country_iso3 == iso3, *_feeds_model())
            .group_by(OutbreakReport.disease_key)
        ).all()
    }

    urls: dict[str | None, str | None] = {}
    for key, url in session.execute(
        select(OutbreakReport.disease_key, func.max(OutbreakReport.source_url))
        .join(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(OutbreakObservation.country_iso3 == iso3)
        .group_by(OutbreakReport.disease_key)
    ).all():
        urls[key] = url

    records = [
        CountryDiseaseRecord(
            disease_key=key,
            disease_name=name or key,
            disease_family=family,
            pathogen_key=pathogen,
            report_count=reports,
            first_published_at=first,
            last_published_at=last,
            cases_confirmed=(
                int(grounded[key][0]) if key in grounded and grounded[key][0] is not None else None
            ),
            deaths=(
                int(grounded[key][1]) if key in grounded and grounded[key][1] is not None else None
            ),
            grounded=key in grounded,
            report_url=urls.get(key),
        )
        for key, name, family, pathogen, reports, first, last in rows
        if key
    ]
    records.sort(key=lambda r: r.last_published_at or datetime.min, reverse=True)
    return records


def country_disease_summary(session: Session) -> dict[str, list[tuple[str, str, datetime | None]]]:
    """``iso3 -> [(disease_key, disease_name, last_report)]`` for the map layer."""
    rows = session.execute(
        select(
            OutbreakObservation.country_iso3,
            OutbreakReport.disease_key,
            func.max(OutbreakReport.disease_name),
            func.max(OutbreakReport.published_at),
        )
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(OutbreakReport.disease_key.is_not(None))
        .group_by(OutbreakObservation.country_iso3, OutbreakReport.disease_key)
    ).all()
    grouped: dict[str, list[tuple[str, str, datetime | None]]] = {}
    for iso3, key, name, last in rows:
        grouped.setdefault(iso3, []).append((key, name or key, last))
    for entries in grouped.values():
        entries.sort(key=lambda e: e[2] or datetime.min, reverse=True)
    return grouped


def countries_reporting_disease(
    session: Session,
    disease_key: str,
    *,
    since: datetime | None = None,
    grounded_only: bool = False,
) -> list[str]:
    statement = (
        select(OutbreakObservation.country_iso3)
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(OutbreakReport.disease_key == disease_key)
        .distinct()
    )
    if grounded_only:
        statement = statement.where(*_feeds_model())
    if since:
        statement = statement.where(OutbreakReport.published_at >= since)
    return list(session.scalars(statement))
