"""WHO's COVID-19 global data table as a second outbreak source.

Why this module exists
----------------------
Every other disease in Endemica arrives through Disease Outbreak News, and for
every other disease that is the right source: WHO publishes a DON per event and
keeps updating it, so the DON archive *is* the surveillance record.

COVID-19 is the one disease where that is false. WHO stopped describing
COVID-19 in Disease Outbreak News after the first weeks of 2020 and moved it to
a dedicated dashboard. The consequence is measurable: of the 3,159 items in the
DON archive only 17 published after December 2019 mention COVID-19 at all, and
most of those are variant notices with no country counts. Grounding those
against their narratives yields ten reports over six countries — which is what
the application showed, and which is obviously not COVID-19.

The counts themselves were never missing; they live in WHO's own
``WHO-COVID-19-global-daily-data.csv``, 240 reporting entities from 2020-01-04
onwards, with cumulative cases and cumulative deaths side by side in the same
row. This module reads that file and writes it into the same
``OutbreakReport`` / ``OutbreakObservation`` tables the DON pipeline uses, so
the rest of the application — history, spread, timeline, the hazard panel —
needs no special case for COVID-19.

What is and is not asserted
---------------------------
* ``extraction_method`` is ``who_api_field``: each number is a field of a WHO
  data product, not something a parser inferred from prose. ``grounding_status``
  is ``verified`` for the same reason — there is no narrative to disagree with.
* ``value_type`` is ``observed``: these are reported counts, not estimates.
  WHO's own caveat that reported counts undercount infections is a property of
  surveillance, not a transformation this project applied.
* One report is emitted per calendar month rather than per day. The daily file
  holds 583k rows; a monthly cumulative snapshot keeps the timeline legible,
  keeps ``series_endpoints`` cheap, and loses nothing the UI shows, because
  every panel reads cumulative totals rather than daily increments. The
  snapshot date is the last date WHO actually reported inside that month, not
  the calendar month end, so ``data_as_of`` never claims coverage WHO did not
  publish.
* Cases and deaths in one row come from one line of one file, which is the
  pairing invariant the repository layer depends on: a cumulative case count is
  never matched with a death toll from a different date.

Entities that are not countries ("International conveyance (Diamond
Princess)", "International commercial vessel") are skipped and counted in the
run detail. They have no ISO-3 code, no population and no air links, so they
cannot take part in any model here.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import uuid
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from endemica.core.clock import utc_now
from endemica.core.config import Settings, get_settings
from endemica.core.errors import ExternalServiceError
from endemica.core.http import build_client, request_with_retry
from endemica.datasets.iso import resolve
from endemica.db.models import (
    Country,
    DatasetVersion,
    IngestionRun,
    OutbreakObservation,
    OutbreakReport,
)
from endemica.schemas.common import ExtractionMethod, ExtractionStatus, ValueType

logger = logging.getLogger(__name__)

SOURCE_NAME = "WHO COVID-19 global data"
SOURCE_SLUG = "who_covid19_global"
DATA_URL = (
    "https://srhdpeuwpubsa.blob.core.windows.net/whdh/COVID/WHO-COVID-19-global-daily-data.csv"
)
LANDING_URL = "https://data.who.int/dashboards/covid19/data"
LICENSE_NOTE = "WHO terms of use: attribution required, commercial reuse restricted."
CACHE_NAME = "who_covid19_global_daily.csv"

DISEASE_KEY = "covid19"
DISEASE_NAME = "COVID-19"
DISEASE_FAMILY = "Respiratory viral infection"
PATHOGEN_KEY = "covid_19"
DISEASE_LABEL = "COVID-19"

_SERVICE = "WHO COVID-19 data"

# Reporting entities with no ISO-3 code: cruise ships and repatriation flights.
# WHO gives them XA-XL codes; they are not places and are excluded.
_NON_COUNTRY_PREFIX = "X"


@dataclass(frozen=True, slots=True)
class CountryCount:
    """One country's cumulative totals on one reporting date."""

    iso3: str
    name_as_reported: str
    cases: int
    deaths: int


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Every country's cumulative totals on the last reporting date of a month."""

    as_of: date
    counts: tuple[CountryCount, ...]

    @property
    def month(self) -> str:
        return self.as_of.strftime("%Y-%m")

    @property
    def source_identifier(self) -> str:
        return f"who-covid19-{self.month}"

    @property
    def title(self) -> str:
        return f"COVID-19 - global situation as of {self.as_of.isoformat()}"

    @property
    def total_cases(self) -> int:
        return sum(count.cases for count in self.counts)

    @property
    def total_deaths(self) -> int:
        return sum(count.deaths for count in self.counts)


def cache_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return settings.raw_data_dir / CACHE_NAME


def download(*, settings: Settings | None = None, force: bool = False) -> Path:
    """Fetch the daily data file, reusing the cached copy unless ``force``."""
    settings = settings or get_settings()
    target = cache_path(settings)
    if target.exists() and not force:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with build_client(settings) as client:
        response = request_with_retry(client, "GET", DATA_URL, service=_SERVICE)
    if response.status_code != 200 or not response.content:
        raise ExternalServiceError(
            _SERVICE,
            f"returned {response.status_code} with {len(response.content)} bytes",
            status_code=response.status_code,
            retryable=True,
        )
    target.write_bytes(response.content)
    return target


def _as_int(value: str | None) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def iter_rows(path: Path) -> Iterator[dict[str, str]]:
    # utf-8-sig: WHO ships the file with a byte-order mark.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def _iso2_index(session: Session) -> dict[str, str]:
    rows = session.execute(select(Country.iso2, Country.iso3)).all()
    return {iso2: iso3 for iso2, iso3 in rows if iso2}


def _resolve_iso3(name: str, iso2: str, *, known: set[str], by_iso2: dict[str, str]) -> str | None:
    """ISO-3 for a WHO reporting entity, or None when it is not a known country.

    Name resolution comes first because WHO's names are closer to the
    reference table's names than its two-letter codes are to ISO 3166-1
    alpha-2 (WHO reuses the X-prefixed user-assigned range for conveyances).
    """
    if iso2.upper().startswith(_NON_COUNTRY_PREFIX):
        return None
    candidate = resolve(name) or by_iso2.get(iso2.upper())
    if candidate is None or candidate not in known:
        return None
    return candidate


def monthly_snapshots(
    path: Path, *, known: set[str], by_iso2: dict[str, str]
) -> tuple[list[Snapshot], dict[str, int]]:
    """Cumulative totals per country at the last reported date of each month.

    Returns the snapshots in chronological order plus counters describing what
    was skipped, which the ingestion run stores so the exclusions are auditable
    rather than silent.
    """
    # Last reporting date seen in each month, and the totals each country had
    # on each date it reported. The file is a complete country x date grid, so
    # reading the last date of a month gives every country's running total.
    last_date: dict[str, date] = {}
    on_date: dict[date, dict[str, CountryCount]] = defaultdict(dict)
    skipped_entities: set[str] = set()
    rows_read = 0
    rows_without_counts = 0

    for row in iter_rows(path):
        rows_read += 1
        reported = _parse_date(row.get("Date_reported"))
        if reported is None:
            continue
        name = (row.get("Country") or "").strip()
        iso2 = (row.get("Country_code") or "").strip()
        iso3 = _resolve_iso3(name, iso2, known=known, by_iso2=by_iso2)
        if iso3 is None:
            skipped_entities.add(name or iso2)
            continue
        cases = _as_int(row.get("Cumulative_cases"))
        deaths = _as_int(row.get("Cumulative_deaths"))
        if cases is None and deaths is None:
            rows_without_counts += 1
            continue
        month = reported.strftime("%Y-%m")
        if last_date.get(month, date.min) < reported:
            last_date[month] = reported
        on_date[reported][iso3] = CountryCount(
            iso3=iso3,
            name_as_reported=name,
            cases=cases or 0,
            deaths=deaths or 0,
        )

    snapshots: list[Snapshot] = []
    # The totals a country was last written with. A snapshot repeats every
    # country's running total whether or not it moved, and storing an unmoved
    # total as a fresh observation would say the country reported this month
    # when it did not. In the final month of this file only 49 of 227 countries
    # moved; the other 178 stopped reporting COVID-19 long ago, and carrying
    # them forward made every one of them look currently active.
    #
    # Dropping them loses nothing downstream: the series is a running maximum,
    # so a country's total still stands at whatever the last month that moved
    # it recorded.
    carried = 0
    previous: dict[str, tuple[int, int]] = {}
    for month in sorted(last_date):
        as_of = last_date[month]
        counts = on_date.get(as_of, {})
        reporting = []
        for count in sorted(counts.values(), key=lambda count: count.iso3):
            # A country with no cases yet is not an outbreak country; including
            # it would claim WHO reported a zero where it reported nothing.
            if count.cases <= 0 and count.deaths <= 0:
                continue
            if previous.get(count.iso3) == (count.cases, count.deaths):
                carried += 1
                continue
            previous[count.iso3] = (count.cases, count.deaths)
            reporting.append(count)
        if not reporting:
            continue
        snapshots.append(Snapshot(as_of=as_of, counts=tuple(reporting)))

    detail = {
        "rows_read": rows_read,
        "rows_without_counts": rows_without_counts,
        "entities_skipped": len(skipped_entities),
        "rows_unchanged_since_previous_month": carried,
        "months": len(snapshots),
    }
    logger.info("who covid snapshots built", extra=detail)
    return snapshots, detail


def _narrative(snapshot: Snapshot) -> str:
    """The text a human would read to check the stored numbers.

    Written from the snapshot itself rather than fetched, because the source is
    a table: this is a rendering of the stored rows, which is why grounding is
    recorded as verified against it.
    """
    lines = [
        f"WHO COVID-19 global data, cumulative totals as reported on {snapshot.as_of.isoformat()}.",
        f"{len(snapshot.counts)} countries and areas reporting; "
        f"{snapshot.total_cases} cumulative confirmed cases and "
        f"{snapshot.total_deaths} cumulative deaths in total.",
        "",
    ]
    lines.extend(
        f"{count.name_as_reported}: {count.cases} cumulative cases, "
        f"{count.deaths} cumulative deaths."
        for count in snapshot.counts
    )
    return "\n".join(lines)


def _evidence(count: CountryCount, snapshot: Snapshot) -> str:
    return (
        f"{count.name_as_reported}: {count.cases} cumulative cases, "
        f"{count.deaths} cumulative deaths (WHO COVID-19 global data, "
        f"{snapshot.as_of.isoformat()})."
    )


def _as_of(snapshot: Snapshot) -> datetime:
    return datetime.combine(snapshot.as_of, time.min, tzinfo=UTC)


def _content_hash(narrative: str) -> str:
    return hashlib.sha256(narrative.encode("utf-8")).hexdigest()


def _upsert(
    session: Session,
    snapshot: Snapshot,
    *,
    run_id: uuid.UUID,
    retrieved_at: datetime,
) -> bool:
    narrative = _narrative(snapshot)
    existing = session.scalar(
        select(OutbreakReport).where(
            OutbreakReport.source_name == SOURCE_NAME,
            OutbreakReport.source_identifier == snapshot.source_identifier,
        )
    )
    created = existing is None
    report = existing or OutbreakReport(
        source_name=SOURCE_NAME, source_identifier=snapshot.source_identifier
    )
    report.source_url = LANDING_URL
    report.published_at = _as_of(snapshot)
    report.data_as_of = _as_of(snapshot)
    report.retrieved_at = retrieved_at
    report.license_note = LICENSE_NOTE
    report.title = snapshot.title
    report.disease_label = DISEASE_LABEL
    report.disease_key = DISEASE_KEY
    report.disease_name = DISEASE_NAME
    report.disease_family = DISEASE_FAMILY
    report.pathogen_key = PATHOGEN_KEY
    report.summary_text = narrative.split("\n\n", 1)[0]
    report.narrative_text = narrative
    report.content_sha256 = _content_hash(narrative)
    report.extraction_method = ExtractionMethod.WHO_API_FIELD
    report.extraction_status = ExtractionStatus.VERIFIED
    report.validation_warnings = None
    report.run_id = run_id
    if created:
        session.add(report)
    session.flush()

    session.query(OutbreakObservation).filter(OutbreakObservation.report_id == report.id).delete(
        synchronize_session=False
    )
    for count in snapshot.counts:
        session.add(
            OutbreakObservation(
                report_id=report.id,
                country_iso3=count.iso3,
                country_name_as_reported=count.name_as_reported,
                cases_confirmed=count.cases,
                deaths=count.deaths,
                period_end=snapshot.as_of,
                evidence_text=_evidence(count, snapshot),
                grounding_status=ExtractionStatus.VERIFIED,
                grounding_detail={"method": "tabular_field", "source": SOURCE_SLUG},
                value_type=ValueType.OBSERVED,
                data_as_of=_as_of(snapshot),
            )
        )
    return created


def file_digest(path: Path) -> str:
    """SHA-256 of the downloaded file.

    WHO revises this file in place, so two checkouts that download it on
    different days hold different data. Recording the digest is what lets
    ``just data-fingerprint`` say *why* two checkouts disagree instead of
    leaving it a mystery.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _record_dataset_version(
    session: Session, path: Path, *, snapshots: list[Snapshot], retrieved_at: datetime
) -> None:
    session.query(DatasetVersion).filter(
        DatasetVersion.dataset == SOURCE_SLUG, DatasetVersion.is_active.is_(True)
    ).update({DatasetVersion.is_active: False})
    first = snapshots[0].as_of if snapshots else None
    latest = snapshots[-1].as_of if snapshots else None
    period = (
        f"{first.isoformat()}..{latest.isoformat()}"
        if first is not None and latest is not None
        else None
    )
    session.add(
        DatasetVersion(
            dataset=SOURCE_SLUG,
            source_name=SOURCE_NAME,
            source_url=DATA_URL,
            retrieved_at=retrieved_at,
            reference_period=period,
            record_count=sum(len(snapshot.counts) for snapshot in snapshots),
            content_sha256=file_digest(path),
            license_note=LICENSE_NOTE,
            notes={
                "filename": path.name,
                "bytes": path.stat().st_size,
                "coverage": "Cumulative confirmed cases and deaths per country and area, daily.",
                "limitations": [
                    "Reported confirmed cases undercount infections; testing effort varies "
                    "by country and over time.",
                    "Stored monthly rather than daily: the snapshot date is the last date "
                    "WHO reported inside each month.",
                    "WHO revises this file in place, so the digest identifies the snapshot.",
                ],
                "fields_used": [
                    "Date_reported",
                    "Country",
                    "Country_code",
                    "Cumulative_cases",
                    "Cumulative_deaths",
                ],
            },
            is_active=True,
        )
    )


@dataclass(slots=True)
class CovidIngestSummary:
    run_id: uuid.UUID
    reports_created: int
    reports_updated: int
    observations_created: int
    months: int
    countries: int
    latest_as_of: date | None
    content_sha256: str
    detail: dict[str, int]


def ingest(
    session: Session,
    *,
    settings: Settings | None = None,
    force_download: bool = False,
    trigger: str = "manual",
) -> CovidIngestSummary:
    """Load WHO's COVID-19 table into the outbreak tables."""
    settings = settings or get_settings()
    path = download(settings=settings, force=force_download)
    known = set(session.scalars(select(Country.iso3)).all())
    if not known:
        raise ExternalServiceError(
            _SERVICE,
            "the countries reference table is empty; run data-load before ingesting COVID-19",
        )
    snapshots, detail = monthly_snapshots(path, known=known, by_iso2=_iso2_index(session))

    retrieved_at = utc_now()
    run = IngestionRun(
        id=uuid.uuid4(),
        source=SOURCE_SLUG,
        mode="direct_fetch",
        trigger=trigger,
        status="running",
        started_at=retrieved_at,
    )
    session.add(run)
    session.flush()

    created = updated = observations = 0
    countries: set[str] = set()
    for snapshot in snapshots:
        if _upsert(session, snapshot, run_id=run.id, retrieved_at=retrieved_at):
            created += 1
        else:
            updated += 1
        observations += len(snapshot.counts)
        countries.update(count.iso3 for count in snapshot.counts)

    run.status = "succeeded"
    run.finished_at = utc_now()
    run.records_seen = len(snapshots)
    run.records_created = created
    run.records_updated = updated
    run.observations_created = observations
    digest = file_digest(path)
    run.detail = {
        **detail,
        "countries": len(countries),
        "source_url": DATA_URL,
        "content_sha256": digest,
    }
    _record_dataset_version(session, path, snapshots=snapshots, retrieved_at=retrieved_at)
    session.flush()

    return CovidIngestSummary(
        run_id=run.id,
        reports_created=created,
        reports_updated=updated,
        observations_created=observations,
        months=len(snapshots),
        countries=len(countries),
        latest_as_of=snapshots[-1].as_of if snapshots else None,
        content_sha256=digest,
        detail=detail,
    )
