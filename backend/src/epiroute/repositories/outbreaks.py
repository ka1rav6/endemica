from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, or_, select
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
) -> list[tuple[OutbreakObservation, OutbreakReport]]:
    statement = (
        select(OutbreakObservation, OutbreakReport)
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(OutbreakObservation.country_iso3 == country_iso3.upper(), *_feeds_model())
        .order_by(OutbreakReport.published_at.desc().nullslast())
    )
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
) -> list[CumulativePoint]:
    rows = verified_observations_for_country(
        session, country_iso3, pathogen_key=pathogen_key, disease_label=disease_label
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
    since: datetime | None = None,
) -> list[str]:
    statement = (
        select(OutbreakObservation.country_iso3)
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(*_feeds_model())
        .distinct()
    )
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


@dataclass(frozen=True, slots=True)
class DiseaseFocus:
    disease_label: str | None
    pathogen_key: str | None
    published_at: datetime | None


def latest_focus_for_country(session: Session, country_iso3: str) -> DiseaseFocus | None:
    """The most recent grounded disease reported for one country."""
    row = session.execute(
        select(
            OutbreakReport.disease_label,
            OutbreakReport.pathogen_key,
            OutbreakReport.published_at,
        )
        .join(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(
            OutbreakObservation.country_iso3 == country_iso3.upper(),
            OutbreakReport.disease_label.is_not(None),
            *_feeds_model(),
        )
        .order_by(OutbreakReport.published_at.desc().nullslast())
        .limit(1)
    ).first()
    if row is None:
        return None
    return DiseaseFocus(disease_label=row[0], pathogen_key=row[1], published_at=row[2])


def latest_global_focus(session: Session) -> DiseaseFocus | None:
    row = session.execute(
        select(
            OutbreakReport.disease_label,
            OutbreakReport.pathogen_key,
            OutbreakReport.published_at,
        )
        .join(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(OutbreakReport.disease_label.is_not(None), *_feeds_model())
        .order_by(OutbreakReport.published_at.desc().nullslast())
        .limit(1)
    ).first()
    if row is None:
        return None
    return DiseaseFocus(disease_label=row[0], pathogen_key=row[1], published_at=row[2])


@dataclass(frozen=True, slots=True)
class DiseaseHistoryRecord:
    disease_label: str
    pathogen_key: str | None
    report_count: int
    country_count: int
    first_published_at: datetime | None
    last_published_at: datetime | None
    cases_confirmed: int | None
    deaths: int | None
    grounded_country_count: int


def list_disease_history(session: Session) -> list[DiseaseHistoryRecord]:
    """Every disease in the archive, with its full span and footprint."""
    totals = session.execute(
        select(
            OutbreakReport.disease_label,
            func.count(func.distinct(OutbreakReport.id)),
            func.min(OutbreakReport.published_at),
            func.max(OutbreakReport.published_at),
            func.count(func.distinct(OutbreakObservation.country_iso3)),
        )
        .outerjoin(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(OutbreakReport.disease_label.is_not(None))
        .group_by(OutbreakReport.disease_label)
    ).all()

    keys = dict(
        session.execute(
            select(OutbreakReport.disease_label, func.max(OutbreakReport.pathogen_key))
            .where(
                OutbreakReport.disease_label.is_not(None),
                OutbreakReport.pathogen_key.is_not(None),
            )
            .group_by(OutbreakReport.disease_label)
        ).all()
    )

    peaks = session.execute(
        select(
            OutbreakReport.disease_label,
            OutbreakObservation.country_iso3,
            func.max(OutbreakObservation.cases_confirmed),
            func.max(OutbreakObservation.deaths),
        )
        .join(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(OutbreakReport.disease_label.is_not(None), *_feeds_model())
        .group_by(OutbreakReport.disease_label, OutbreakObservation.country_iso3)
    ).all()

    cases: dict[str, int] = {}
    deaths: dict[str, int] = {}
    grounded: dict[str, set[str]] = {}
    for label, iso3, peak_cases, peak_deaths in peaks:
        grounded.setdefault(label, set()).add(iso3)
        if peak_cases is not None:
            cases[label] = cases.get(label, 0) + int(peak_cases)
        if peak_deaths is not None:
            deaths[label] = deaths.get(label, 0) + int(peak_deaths)

    records = [
        DiseaseHistoryRecord(
            disease_label=label,
            pathogen_key=keys.get(label),
            report_count=reports,
            country_count=countries,
            first_published_at=first,
            last_published_at=last,
            cases_confirmed=cases.get(label),
            deaths=deaths.get(label),
            grounded_country_count=len(grounded.get(label, ())),
        )
        for label, reports, first, last, countries in totals
        if label
    ]
    records.sort(key=lambda r: (r.last_published_at or datetime.min), reverse=True)
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


def country_spread_for_disease(session: Session, disease_label: str) -> list[CountrySpreadRecord]:
    """Which countries a disease reached, when, and with what counts."""
    rows = session.execute(
        select(
            OutbreakObservation.country_iso3,
            func.count(func.distinct(OutbreakReport.id)),
            func.min(OutbreakReport.published_at),
            func.max(OutbreakReport.published_at),
        )
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(func.lower(OutbreakReport.disease_label) == disease_label.casefold())
        .group_by(OutbreakObservation.country_iso3)
    ).all()

    grounded_rows = session.execute(
        select(
            OutbreakObservation.country_iso3,
            func.max(OutbreakObservation.cases_confirmed),
            func.max(OutbreakObservation.deaths),
        )
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(
            func.lower(OutbreakReport.disease_label) == disease_label.casefold(),
            *_feeds_model(),
        )
        .group_by(OutbreakObservation.country_iso3)
    ).all()
    grounded = {iso3: (c, d) for iso3, c, d in grounded_rows}

    url_rows = session.execute(
        select(OutbreakObservation.country_iso3, func.max(OutbreakReport.source_url))
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(func.lower(OutbreakReport.disease_label) == disease_label.casefold())
        .group_by(OutbreakObservation.country_iso3)
    ).all()
    urls = dict(url_rows)

    records: list[CountrySpreadRecord] = []
    for iso3, reports, first, last in rows:
        counts = grounded.get(iso3)
        records.append(
            CountrySpreadRecord(
                country_iso3=iso3,
                report_count=reports,
                first_published_at=first,
                last_published_at=last,
                cases_confirmed=int(counts[0]) if counts and counts[0] is not None else None,
                deaths=int(counts[1]) if counts and counts[1] is not None else None,
                grounded=iso3 in grounded,
                report_url=urls.get(iso3),
            )
        )
    records.sort(key=lambda r: (r.first_published_at or datetime.max))
    return records


@dataclass(frozen=True, slots=True)
class DiseaseTimelinePoint:
    period: str
    report_count: int
    country_count: int
    new_countries: tuple[str, ...]


def disease_timeline(session: Session, disease_label: str) -> list[DiseaseTimelinePoint]:
    """Reports and newly reached countries per year, so spread reads chronologically."""
    rows = session.execute(
        select(
            OutbreakReport.published_at,
            OutbreakReport.id,
            OutbreakObservation.country_iso3,
        )
        .outerjoin(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(
            func.lower(OutbreakReport.disease_label) == disease_label.casefold(),
            OutbreakReport.published_at.is_not(None),
        )
        .order_by(OutbreakReport.published_at)
    ).all()

    by_year: dict[str, tuple[set[str], list[str]]] = {}
    seen: set[str] = set()
    for published_at, report_id, iso3 in rows:
        year = str(published_at.year)
        reports, new = by_year.setdefault(year, (set(), []))
        reports.add(str(report_id))
        if iso3 and iso3 not in seen:
            seen.add(iso3)
            new.append(iso3)

    return [
        DiseaseTimelinePoint(
            period=year,
            report_count=len(reports),
            country_count=len(new),
            new_countries=tuple(new),
        )
        for year, (reports, new) in sorted(by_year.items())
    ]


def diseases_for_country(session: Session, country_iso3: str) -> list[CountrySpreadRecord]:
    """Every disease ever reported for one country, newest activity first."""
    rows = session.execute(
        select(
            OutbreakReport.disease_label,
            func.count(func.distinct(OutbreakReport.id)),
            func.min(OutbreakReport.published_at),
            func.max(OutbreakReport.published_at),
            func.max(OutbreakObservation.cases_confirmed),
            func.max(OutbreakObservation.deaths),
            func.max(OutbreakReport.source_url),
        )
        .join(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(
            OutbreakObservation.country_iso3 == country_iso3.upper(),
            OutbreakReport.disease_label.is_not(None),
        )
        .group_by(OutbreakReport.disease_label)
        .order_by(func.max(OutbreakReport.published_at).desc().nullslast())
    ).all()
    return [
        CountrySpreadRecord(
            country_iso3=label,
            report_count=reports,
            first_published_at=first,
            last_published_at=last,
            cases_confirmed=int(cases) if cases is not None else None,
            deaths=int(deaths) if deaths is not None else None,
            grounded=cases is not None or deaths is not None,
            report_url=url,
        )
        for label, reports, first, last, cases, deaths, url in rows
        if label
    ]


def disease_country_matrix(session: Session) -> dict[str, list[tuple[str, datetime | None]]]:
    """Diseases per country with their latest report date, for the map layer."""
    rows = session.execute(
        select(
            OutbreakObservation.country_iso3,
            OutbreakReport.disease_label,
            func.max(OutbreakReport.published_at),
        )
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(OutbreakReport.disease_label.is_not(None))
        .group_by(OutbreakObservation.country_iso3, OutbreakReport.disease_label)
    ).all()
    grouped: dict[str, list[tuple[str, datetime | None]]] = {}
    for iso3, label, last in rows:
        if label:
            grouped.setdefault(iso3, []).append((label, last))
    for entries in grouped.values():
        entries.sort(key=lambda e: (e[1] or datetime.min), reverse=True)
    return grouped
