from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from epiroute.core.clock import utc_now
from epiroute.core.config import Settings, get_settings
from epiroute.core.errors import EpiRouteError
from epiroute.datasets.iso import find_countries, first_country
from epiroute.db.models import Country, IngestionRun, OutbreakObservation, OutbreakReport
from epiroute.ingestion.extraction import (
    ExtractionOutcome,
    extract_with_parser,
    extract_with_tinyfish,
)
from epiroute.ingestion.validate import validate_extraction
from epiroute.ingestion.who_don import LICENSE_NOTE, SOURCE_NAME, DonRecord, iter_recent_records
from epiroute.schemas.common import ExtractionStatus, ValueType
from epiroute.tinyfish.client import TinyFishClient, build_client_or_none

logger = logging.getLogger(__name__)

MODE_TINYFISH_AGENT = "tinyfish_agent"
MODE_TINYFISH_FETCH = "tinyfish_fetch"
MODE_DIRECT_FETCH = "direct_fetch"


@dataclass(slots=True)
class RunSummary:
    run_id: uuid.UUID
    mode: str
    status: str
    records_seen: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    observations_created: int = 0
    observations_unverified: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _resolve_mode(client: TinyFishClient | None, *, use_agent: bool) -> str:
    if client is None:
        return MODE_DIRECT_FETCH
    return MODE_TINYFISH_AGENT if use_agent else MODE_TINYFISH_FETCH


def _known_countries(session: Session) -> set[str]:
    return set(session.scalars(select(Country.iso3)).all())


_MAX_LOCATION_ONLY = 12


def _location_only_rows(record: DonRecord, usable: Sequence[object], known: set[str]) -> list[str]:
    """Countries named in the title that no grounded observation already covers.

    These rows carry no numbers. They exist so a report still places the
    outbreak on the map when the parser found no count it could ground.
    """
    already = {getattr(o, "country_iso3", None) for o in usable}
    found = find_countries(record.title)
    if not found:
        found = find_countries(record.summary_text or "")[:1]
    out: list[str] = []
    for iso3 in found[:_MAX_LOCATION_ONLY]:
        if iso3 in known and iso3 not in already and iso3 not in out:
            out.append(iso3)
    return out


def _upsert_report(
    session: Session,
    record: DonRecord,
    outcome: ExtractionOutcome,
    status: ExtractionStatus,
    warnings: list[dict[str, Any]],
    run_id: uuid.UUID,
) -> tuple[OutbreakReport, bool]:
    existing = session.scalar(
        select(OutbreakReport).where(
            OutbreakReport.source_name == SOURCE_NAME,
            OutbreakReport.source_identifier == record.source_identifier,
        )
    )
    created = existing is None
    report = existing or OutbreakReport(
        source_name=SOURCE_NAME, source_identifier=record.source_identifier
    )

    report.source_url = record.source_url
    report.published_at = record.published_at
    report.retrieved_at = record.retrieved_at
    report.license_note = LICENSE_NOTE
    report.title = record.title
    report.disease_label = record.disease_label
    report.disease_key = record.disease_key
    report.disease_name = record.disease_name
    report.disease_family = record.disease_family
    report.pathogen_key = record.pathogen_key
    report.summary_text = record.summary_text
    report.narrative_text = outcome.source_text
    report.content_sha256 = record.content_sha256
    report.extraction_method = outcome.method
    report.extraction_status = status
    report.validation_warnings = warnings or None
    report.run_id = run_id

    if created:
        session.add(report)
    session.flush()
    return report, created


def ingest_records(
    session: Session,
    records: Iterable[DonRecord],
    *,
    settings: Settings | None = None,
    client: TinyFishClient | None = None,
    use_agent: bool = True,
    trigger: str = "manual",
) -> RunSummary:
    settings = settings or get_settings()
    mode = _resolve_mode(client, use_agent=use_agent)
    run = IngestionRun(
        id=uuid.uuid4(),
        source="who_don",
        mode=mode,
        trigger=trigger,
        status="running",
        started_at=utc_now(),
    )
    session.add(run)
    session.flush()

    summary = RunSummary(run_id=run.id, mode=mode, status="running")
    known = _known_countries(session)
    agent_budget = settings.tinyfish_agent_max_pages_per_run
    agent_used = 0

    for record in records:
        summary.records_seen += 1
        try:
            if client is not None:
                allow_agent = use_agent and agent_used < agent_budget
                outcome = extract_with_tinyfish(
                    record, client, use_agent=allow_agent, settings=settings
                )
                if outcome.agent_run_id is not None:
                    agent_used += 1
            else:
                outcome = extract_with_parser(record)

            if not outcome.ok:
                summary.records_skipped += 1
                summary.warnings.append(
                    {
                        "code": "empty_source_text",
                        "message": "no narrative text available to ground against",
                        "record": record.source_identifier,
                    }
                )
                continue

            validation = validate_extraction(
                outcome.report.locations,
                source_text=outcome.source_text,
                report_published_at=record.published_at,
                fallback_iso3=first_country(record.title),
            )
            usable = [o for o in validation.observations if o.country_iso3 in known]
            location_only = _location_only_rows(record, usable, known)
            dropped = len(validation.observations) - len(usable)
            if dropped:
                validation.warnings.append(
                    {
                        "code": "unknown_country_reference",
                        "message": (
                            f"{dropped} observation(s) referenced countries that are "
                            f"absent from the reference table"
                        ),
                        "record": record.source_identifier,
                    }
                )

            if any(o.grounding_status is ExtractionStatus.VERIFIED for o in usable):
                report_status = ExtractionStatus.VERIFIED
            elif usable:
                report_status = ExtractionStatus.PARTIAL
            elif outcome.error:
                report_status = ExtractionStatus.FAILED
            else:
                report_status = ExtractionStatus.UNVERIFIED

            warnings = list(validation.warnings)
            if outcome.error:
                warnings.append({"code": "extraction_degraded", "message": outcome.error})

            report, created = _upsert_report(
                session, record, outcome, report_status, warnings, run.id
            )
            if created:
                summary.records_created += 1
            else:
                summary.records_updated += 1

            session.query(OutbreakObservation).filter(
                OutbreakObservation.report_id == report.id
            ).delete(synchronize_session=False)

            for iso3 in location_only:
                session.add(
                    OutbreakObservation(
                        report_id=report.id,
                        country_iso3=iso3,
                        country_name_as_reported=None,
                        evidence_text=record.title,
                        grounding_status=ExtractionStatus.NOT_ATTEMPTED,
                        value_type=ValueType.UNKNOWN,
                    )
                )

            for observation in usable:
                session.add(
                    OutbreakObservation(
                        report_id=report.id,
                        country_iso3=observation.country_iso3,
                        country_name_as_reported=observation.country_name_as_reported,
                        subnational_name=observation.subnational_name,
                        cases_confirmed=observation.cases_confirmed,
                        cases_probable=observation.cases_probable,
                        cases_suspected=observation.cases_suspected,
                        deaths=observation.deaths,
                        period_start=observation.period_start,
                        period_end=observation.period_end,
                        period_text=observation.period_text,
                        evidence_text=observation.evidence_text,
                        grounding_status=observation.grounding_status,
                        grounding_detail=observation.grounding_detail,
                        value_type=observation.value_type,
                    )
                )
                summary.observations_created += 1
                if observation.grounding_status is not ExtractionStatus.VERIFIED:
                    summary.observations_unverified += 1

            summary.warnings.extend(warnings)
            session.flush()

        except EpiRouteError as exc:
            session.rollback()
            summary.records_skipped += 1
            summary.errors.append(f"{record.source_identifier}: {exc}")
            logger.warning(
                "record ingestion failed; previously stored records are unaffected",
                extra={"record": record.source_identifier, "error": str(exc)},
            )
            run = session.get(IngestionRun, summary.run_id) or run

    run.status = "succeeded" if not summary.errors else "failed"
    run.finished_at = utc_now()
    run.records_seen = summary.records_seen
    run.records_created = summary.records_created
    run.records_updated = summary.records_updated
    run.records_skipped = summary.records_skipped
    run.observations_created = summary.observations_created
    run.observations_unverified = summary.observations_unverified
    if summary.errors:
        run.error_code = "record_failures"
        run.error_message = "; ".join(summary.errors[:5])
    run.detail = {
        "agent_runs_used": agent_used,
        "agent_budget": agent_budget,
        "warning_count": len(summary.warnings),
        "warning_codes": sorted({str(w.get("code")) for w in summary.warnings}),
    }
    summary.status = run.status
    session.flush()

    logger.info(
        "ingestion run finished",
        extra={
            "run_id": str(run.id),
            "mode": mode,
            "status": run.status,
            "records_seen": summary.records_seen,
            "records_created": summary.records_created,
            "records_updated": summary.records_updated,
            "observations_stored": summary.observations_created,
        },
    )
    return summary


def run_ingestion(
    session: Session,
    *,
    limit: int | None = None,
    settings: Settings | None = None,
    use_agent: bool = True,
    trigger: str = "manual",
) -> RunSummary:
    settings = settings or get_settings()
    client = build_client_or_none(settings)
    records = iter_recent_records(limit=limit, settings=settings)
    return ingest_records(
        session, records, settings=settings, client=client, use_agent=use_agent, trigger=trigger
    )
