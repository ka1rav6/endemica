from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
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
    source_name: str = ""
    disease_id: str = ""
    cases_probable: int | None = None
    cases_suspected: int | None = None

    @property
    def cases_any(self) -> int | None:
        """The widest case figure the source gave, confirmed first.

        A death toll is only comparable with a case count that is at least as
        wide as the one the deaths were counted over, so the consistency check
        uses this rather than the confirmed column alone.
        """
        widest = _greater(self.cases_confirmed, self.cases_probable)
        return _greater(widest, self.cases_suspected)


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


def _points_for_rows(
    rows: list[tuple[OutbreakObservation, OutbreakReport]],
) -> list[CumulativePoint]:
    """One cumulative point per report, for rows that already share a source and disease."""
    by_report: dict[str, CumulativePoint] = {}
    for observation, report in rows:
        if report.published_at is None:
            continue
        existing = by_report.get(report.source_identifier)
        confirmed = observation.cases_confirmed
        deaths = observation.deaths
        probable = observation.cases_probable
        suspected = observation.cases_suspected
        if existing is not None:
            confirmed = _greater(existing.cases_confirmed, confirmed)
            deaths = _greater(existing.deaths, deaths)
            probable = _greater(existing.cases_probable, probable)
            suspected = _greater(existing.cases_suspected, suspected)
        by_report[report.source_identifier] = CumulativePoint(
            published_at=report.published_at,
            cases_confirmed=confirmed,
            deaths=deaths,
            cases_probable=probable,
            cases_suspected=suspected,
            report_identifier=report.source_identifier,
            report_url=report.source_url,
            outbreak_started_on=find_outbreak_start(report.narrative_text or ""),
            source_name=report.source_name,
            disease_id=report.disease_key or (report.disease_label or ""),
        )
    ordered = sorted(by_report.values(), key=lambda point: point.published_at)
    return _running_max(_latest_episode(ordered))


def _aware(value: datetime) -> datetime:
    """Treat a naive timestamp as UTC so it can be compared with stored times."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def published_at_or_before(published: datetime | None, as_of: datetime | None) -> bool:
    """Whether a report had been published by ``as_of``. Missing dates are kept."""
    if published is None or as_of is None:
        return True
    return _aware(published) <= _aware(as_of)


def _latest_episode(points: list[CumulativePoint]) -> list[CumulativePoint]:
    """Keep only the points that belong to the newest outbreak in the series.

    Differencing across the restart would treat a new outbreak's first total as
    a change from an epidemic that ended years earlier.
    """
    if not points:
        return []
    start = 0
    best: int | None = None
    previous: CumulativePoint | None = None
    for index, point in enumerate(points):
        if _starts_new_episode(point, best, previous):
            start = index
            best = point.cases_confirmed
        else:
            best = _greater(best, point.cases_confirmed)
        previous = point
    return points[start:]


def choose_single_series(
    groups: dict[tuple[str, str], list[CumulativePoint]],
) -> list[CumulativePoint]:
    """Pick one source and one disease. Never difference counts across either.

    The chosen series is the one whose latest report is newest. A longer series
    breaks a tie, so a single later bulletin does not discard a fuller source
    published at the same moment.
    """
    ranked = [
        (series[-1].published_at, len(series), series) for series in groups.values() if series
    ]
    if not ranked:
        return []
    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[-1][2]


def cumulative_series(
    session: Session,
    country_iso3: str,
    pathogen_key: str,
    *,
    disease_label: str | None = None,
    disease_key: str | None = None,
    as_of: datetime | None = None,
) -> list[CumulativePoint]:
    rows = [
        (observation, report)
        for observation, report in verified_observations_for_country(
            session,
            country_iso3,
            pathogen_key=pathogen_key,
            disease_label=disease_label,
            disease_key=disease_key,
        )
        if published_at_or_before(report.published_at, as_of)
    ]
    groups: dict[tuple[str, str], list[tuple[OutbreakObservation, OutbreakReport]]] = {}
    for observation, report in rows:
        disease_id = report.disease_key or (report.disease_label or "").casefold()
        groups.setdefault((report.source_name, disease_id), []).append((observation, report))
    built = {key: _points_for_rows(group) for key, group in groups.items()}
    return choose_single_series(built)


def _greater(a: int | None, b: int | None) -> int | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


# A later report whose cumulative count sits this far below the running total
# is counting a different outbreak, not revising the same one downwards.
_NEW_EPISODE_RATIO = 0.9

# One country can report the same disease again years later. A gap this long
# separates two outbreaks even when the counts happen to keep rising.
_NEW_EPISODE_GAP_DAYS = 365


def _starts_new_episode(
    point: CumulativePoint, best_cases: int | None, previous: CumulativePoint | None
) -> bool:
    """Whether this report belongs to a later outbreak than the running total.

    Cumulative counts only ever rise inside one outbreak, so a figure well
    below the running total means the source has moved on to a new episode.
    Without this, a country's current outbreak inherits the peak of a far
    larger one years earlier and reads as having no new cases at all.
    """
    if previous is not None:
        gap = (point.published_at - previous.published_at).days
        if gap > _NEW_EPISODE_GAP_DAYS:
            return True
    if best_cases is None or point.cases_confirmed is None:
        return False
    return point.cases_confirmed < best_cases * _NEW_EPISODE_RATIO


def _running_max(series: list[CumulativePoint]) -> list[CumulativePoint]:
    """Carry each cumulative count forward, restarting at every new outbreak."""
    best_cases: int | None = None
    best_deaths: int | None = None
    best_probable: int | None = None
    best_suspected: int | None = None
    previous: CumulativePoint | None = None
    out: list[CumulativePoint] = []
    for point in series:
        if _starts_new_episode(point, best_cases, previous):
            best_cases = point.cases_confirmed
            best_deaths = point.deaths
            best_probable = point.cases_probable
            best_suspected = point.cases_suspected
        else:
            best_cases = _greater(best_cases, point.cases_confirmed)
            best_deaths = _greater(best_deaths, point.deaths)
            best_probable = _greater(best_probable, point.cases_probable)
            best_suspected = _greater(best_suspected, point.cases_suspected)
        out.append(
            CumulativePoint(
                published_at=point.published_at,
                cases_confirmed=best_cases,
                deaths=best_deaths,
                cases_probable=best_probable,
                cases_suspected=best_suspected,
                report_identifier=point.report_identifier,
                report_url=point.report_url,
                outbreak_started_on=point.outbreak_started_on,
                source_name=point.source_name,
                disease_id=point.disease_id,
            )
        )
        previous = point
    return out


def countries_with_active_outbreaks(
    session: Session,
    *,
    pathogen_key: str | None = None,
    disease_label: str | None = None,
    disease_key: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
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
    if until is not None:
        statement = statement.where(OutbreakReport.published_at <= _aware(until))
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


# ---------------------------------------------------------------------------
# Paired country endpoints
#
# Every total the app shows is built from these. The previous version asked
# SQL for max(cases) and max(deaths) over a whole disease, which took the two
# numbers from whatever report happened to hold the largest of each. Over a
# disease that has flared repeatedly for thirty years that pairs a case count
# from one epidemic with a death toll from another, which is how the app came
# to show more deaths than cases for 26 of its 56 diseases.
#
# An endpoint instead is the last point of one country's latest episode of one
# source's series, so the two numbers were published together, in the same
# bulletin, about the same outbreak, and carry the date they were current on.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SeriesEndpoint:
    """Where one country's latest episode of one disease had got to."""

    disease_key: str
    country_iso3: str
    cases_confirmed: int | None
    cases_probable: int | None
    cases_suspected: int | None
    deaths: int | None
    as_of: datetime
    episode_report_count: int
    source_name: str
    report_identifier: str
    report_url: str

    @property
    def cases_any(self) -> int | None:
        widest = _greater(self.cases_confirmed, self.cases_probable)
        return _greater(widest, self.cases_suspected)

    @property
    def consistent(self) -> bool:
        """Whether the deaths can sit beside the cases in one sentence.

        A toll larger than every case figure on the same report means the two
        were counted over different scopes - commonly deaths across a whole
        region against cases in one province. Such a pair is reported as a
        count that could not be reconciled rather than silently summed.
        """
        cases = self.cases_any
        if self.deaths is None or cases is None:
            return True
        return self.deaths <= cases


def _endpoint_rows(
    session: Session, *, disease_key: str | None, since: datetime | None
) -> list[tuple[OutbreakObservation, OutbreakReport]]:
    statement = (
        select(OutbreakObservation, OutbreakReport)
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(
            OutbreakReport.disease_key.is_not(None),
            OutbreakReport.published_at.is_not(None),
            *_feeds_model(),
        )
    )
    if disease_key is not None:
        statement = statement.where(OutbreakReport.disease_key == disease_key)
    if since is not None:
        statement = statement.where(OutbreakReport.published_at >= since)
    return [(observation, report) for observation, report in session.execute(statement)]


def series_endpoints(
    session: Session,
    *,
    disease_key: str | None = None,
    since: datetime | None = None,
) -> dict[tuple[str, str], SeriesEndpoint]:
    """One paired endpoint per (disease, country), keyed by that pair.

    ``since`` restricts the reports the series is built from, which is what the
    active view wants: the current episode as the last month described it.
    """
    grouped: dict[
        tuple[str, str], dict[tuple[str, str], list[tuple[OutbreakObservation, OutbreakReport]]]
    ] = {}
    for observation, report in _endpoint_rows(session, disease_key=disease_key, since=since):
        key = (str(report.disease_key), observation.country_iso3)
        source_key = (report.source_name, str(report.disease_key))
        grouped.setdefault(key, {}).setdefault(source_key, []).append((observation, report))

    endpoints: dict[tuple[str, str], SeriesEndpoint] = {}
    for (disease, iso3), by_source in grouped.items():
        built = {source: _points_for_rows(rows) for source, rows in by_source.items()}
        series = choose_single_series(built)
        if not series:
            continue
        last = series[-1]
        endpoints[(disease, iso3)] = SeriesEndpoint(
            disease_key=disease,
            country_iso3=iso3,
            cases_confirmed=last.cases_confirmed,
            cases_probable=last.cases_probable,
            cases_suspected=last.cases_suspected,
            deaths=last.deaths,
            as_of=last.published_at,
            episode_report_count=len(series),
            source_name=last.source_name,
            report_identifier=last.report_identifier,
            report_url=last.report_url,
        )
    return endpoints


@dataclass(frozen=True, slots=True)
class CountTotals:
    """A case total and a death total taken over the same set of countries."""

    cases_confirmed: int | None
    cases_reported: int | None
    deaths: int | None
    as_of: datetime | None
    counted_country_count: int
    unreconciled_country_count: int


def total_counts(endpoints: Iterable[SeriesEndpoint]) -> CountTotals:
    """Sum the endpoints that can carry both numbers, and count the rest.

    Only a country with some case figure contributes. A country that reported
    deaths but no case count would otherwise push the death total above the
    case total over a set of countries that never had one, which is how a
    disease came to be shown with more deaths than cases. Those countries are
    reported as unreconciled instead of being folded in.

    ``cases_reported`` is the widest figure each source gave and
    ``cases_confirmed`` only the laboratory-confirmed column. Cholera and
    yellow fever are reported in suspected cases far more often than
    confirmed ones, so the confirmed total alone would be a small fraction of
    the outbreak the death toll was counted over.
    """
    confirmed = 0
    reported = 0
    deaths = 0
    has_confirmed = False
    has_deaths = False
    counted = 0
    unreconciled = 0
    as_of: datetime | None = None
    for endpoint in endpoints:
        widest = endpoint.cases_any
        if widest is None or not endpoint.consistent:
            unreconciled += 1
            continue
        counted += 1
        reported += widest
        if endpoint.cases_confirmed is not None:
            confirmed += endpoint.cases_confirmed
            has_confirmed = True
        if endpoint.deaths is not None:
            deaths += endpoint.deaths
            has_deaths = True
        moment = _aware(endpoint.as_of)
        as_of = moment if as_of is None else max(as_of, moment)
    return CountTotals(
        cases_confirmed=confirmed if has_confirmed else None,
        cases_reported=reported if counted else None,
        deaths=deaths if has_deaths else None,
        as_of=as_of,
        counted_country_count=counted,
        unreconciled_country_count=unreconciled,
    )


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
    cases_reported: int | None
    deaths: int | None
    counts_as_of: datetime | None
    counted_country_count: int
    unreconciled_country_count: int
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

    # One paired endpoint per country, then summed. Both numbers in a row come
    # from the same bulletin about the same episode, so they can be added up
    # without mixing one epidemic's cases into another's deaths.
    by_disease: dict[str, list[SeriesEndpoint]] = {}
    for (key, _iso3), endpoint in series_endpoints(session).items():
        by_disease.setdefault(key, []).append(endpoint)
    totals = {key: total_counts(group) for key, group in by_disease.items()}

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
            cases_confirmed=totals[key].cases_confirmed if key in totals else None,
            cases_reported=totals[key].cases_reported if key in totals else None,
            deaths=totals[key].deaths if key in totals else None,
            counts_as_of=totals[key].as_of if key in totals else None,
            counted_country_count=totals[key].counted_country_count if key in totals else 0,
            unreconciled_country_count=(
                totals[key].unreconciled_country_count if key in totals else 0
            ),
            grounded_country_count=len(by_disease.get(key, ())),
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
    cases_reported: int | None
    deaths: int | None
    counts_as_of: datetime | None
    counts_reconciled: bool
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
        iso3: endpoint
        for (_key, iso3), endpoint in series_endpoints(session, disease_key=disease_key).items()
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
        endpoint = grounded.get(iso3)
        url, title = latest.get(iso3, (None, None))
        records.append(
            CountrySpreadRecord(
                country_iso3=iso3,
                report_count=reports,
                first_published_at=first,
                last_published_at=last,
                cases_confirmed=endpoint.cases_confirmed if endpoint else None,
                cases_reported=endpoint.cases_any if endpoint else None,
                deaths=endpoint.deaths if endpoint else None,
                counts_as_of=endpoint.as_of if endpoint else None,
                counts_reconciled=endpoint.consistent if endpoint else True,
                grounded=endpoint is not None,
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


def _sum_or_none(values: Iterable[int | None]) -> int | None:
    present = [int(value) for value in values if value is not None]
    return sum(present) if present else None


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
            {"reports": set(), "countries": set(), "new": [], "pairs": {}},
        )
        bucket["reports"].add(str(report_id))
        if not iso3:
            continue
        bucket["countries"].add(iso3)
        if iso3 not in seen:
            seen.add(iso3)
            bucket["new"].append(iso3)
        if status in (ExtractionStatus.VERIFIED, ExtractionStatus.PARTIAL):
            pair = bucket["pairs"].get(iso3)
            if pair is None or published_at >= pair[0]:
                # Both numbers from the latest report of the year, so a year's
                # deaths are never paired with another year's case count.
                bucket["pairs"][iso3] = (published_at, cases, deaths)

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
                cases_confirmed=_sum_or_none(
                    cases for _when, cases, _deaths in bucket["pairs"].values()
                ),
                deaths=_sum_or_none(deaths for _when, _cases, deaths in bucket["pairs"].values()),
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
    cases_reported: int | None
    deaths: int | None
    counts_as_of: datetime | None
    counts_reconciled: bool
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
        key: endpoint
        for (key, country), endpoint in series_endpoints(session).items()
        if country == iso3
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
            cases_confirmed=grounded[key].cases_confirmed if key in grounded else None,
            cases_reported=grounded[key].cases_any if key in grounded else None,
            deaths=grounded[key].deaths if key in grounded else None,
            counts_as_of=grounded[key].as_of if key in grounded else None,
            counts_reconciled=grounded[key].consistent if key in grounded else True,
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


@dataclass(frozen=True, slots=True)
class ActiveDisease:
    disease_key: str
    disease_name: str
    pathogen_key: str | None
    country_count: int
    report_count: int
    last_published_at: datetime | None


def active_diseases(session: Session, *, since: datetime) -> list[ActiveDisease]:
    """Diseases with at least one grounded report since ``since``.

    This is the set the "all active" view answers about, so it uses the same
    grounding gate as every other number rather than counting bare mentions.
    """
    rows = session.execute(
        select(
            OutbreakReport.disease_key,
            func.max(OutbreakReport.disease_name),
            func.max(OutbreakReport.pathogen_key),
            func.count(func.distinct(OutbreakObservation.country_iso3)),
            func.count(func.distinct(OutbreakReport.id)),
            func.max(OutbreakReport.published_at),
        )
        .join(OutbreakObservation, OutbreakObservation.report_id == OutbreakReport.id)
        .where(
            OutbreakReport.disease_key.is_not(None),
            OutbreakReport.published_at >= since,
            *_feeds_model(),
        )
        .group_by(OutbreakReport.disease_key)
        .order_by(func.max(OutbreakReport.published_at).desc())
    ).all()
    return [
        ActiveDisease(
            disease_key=key,
            disease_name=name or key,
            pathogen_key=pathogen,
            country_count=countries,
            report_count=reports,
            last_published_at=last,
        )
        for key, name, pathogen, countries, reports, last in rows
        if key
    ]


@dataclass(frozen=True, slots=True)
class ActiveCountryRecord:
    country_iso3: str
    disease_count: int
    report_count: int
    cases_confirmed: int | None
    cases_reported: int | None
    deaths: int | None
    last_published_at: datetime | None
    diseases: tuple[tuple[str, str], ...]


def active_countries(session: Session, *, since: datetime) -> list[ActiveCountryRecord]:
    """Every country with a grounded report since ``since``, and for which diseases."""
    rows = session.execute(
        select(
            OutbreakObservation.country_iso3,
            OutbreakReport.disease_key,
            func.max(OutbreakReport.disease_name),
            func.count(func.distinct(OutbreakReport.id)),
            func.max(OutbreakReport.published_at),
        )
        .join(OutbreakReport, OutbreakObservation.report_id == OutbreakReport.id)
        .where(
            OutbreakReport.disease_key.is_not(None),
            OutbreakReport.published_at >= since,
            *_feeds_model(),
        )
        .group_by(OutbreakObservation.country_iso3, OutbreakReport.disease_key)
    ).all()

    # The window is part of the series, not applied after it: a country's
    # active figure is where the last month's bulletins left its current
    # episode, not the largest number it ever reported for that disease.
    endpoints = series_endpoints(session, since=since)
    grouped: dict[str, dict[str, Any]] = {}
    for iso3, key, name, reports, last in rows:
        bucket = grouped.setdefault(
            iso3,
            {"reports": 0, "last": None, "diseases": [], "endpoints": []},
        )
        bucket["reports"] += reports
        endpoint = endpoints.get((key, iso3))
        if endpoint is not None:
            bucket["endpoints"].append(endpoint)
        if last is not None and (bucket["last"] is None or last > bucket["last"]):
            bucket["last"] = last
        bucket["diseases"].append((key, name or key))

    for bucket in grouped.values():
        bucket["totals"] = total_counts(bucket["endpoints"])

    records = [
        ActiveCountryRecord(
            country_iso3=iso3,
            disease_count=len(bucket["diseases"]),
            report_count=bucket["reports"],
            cases_confirmed=bucket["totals"].cases_confirmed,
            cases_reported=bucket["totals"].cases_reported,
            deaths=bucket["totals"].deaths,
            last_published_at=bucket["last"],
            diseases=tuple(sorted(bucket["diseases"], key=lambda entry: entry[1])),
        )
        for iso3, bucket in grouped.items()
    ]
    records.sort(key=lambda r: (r.disease_count, r.cases_confirmed or 0), reverse=True)
    return records
