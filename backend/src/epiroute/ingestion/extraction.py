from __future__ import annotations

import logging
from dataclasses import dataclass

from epiroute.core.config import Settings, get_settings
from epiroute.core.errors import ExternalServiceError
from epiroute.ingestion.parser import parse_report
from epiroute.ingestion.who_don import DonRecord
from epiroute.schemas.common import ExtractionMethod
from epiroute.tinyfish.client import TinyFishClient, TinyFishCreditsExhaustedError
from epiroute.tinyfish.goals import OUTBREAK_EXTRACTION_GOAL
from epiroute.tinyfish.schemas import OUTPUT_SCHEMA, ExtractedReport

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    report: ExtractedReport
    source_text: str
    method: ExtractionMethod
    agent_run_id: str | None = None
    agent_steps: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.source_text.strip())


def extract_with_parser(record: DonRecord) -> ExtractionOutcome:
    report = parse_report(
        record.narrative_text, title=record.title, disease_label=record.disease_label
    )
    return ExtractionOutcome(
        report=report,
        source_text=record.narrative_text,
        method=ExtractionMethod.DETERMINISTIC_PARSER,
    )


def extract_with_tinyfish(
    record: DonRecord,
    client: TinyFishClient,
    *,
    use_agent: bool = True,
    settings: Settings | None = None,
) -> ExtractionOutcome:
    settings = settings or get_settings()

    source_text = record.narrative_text
    try:
        fetched = client.fetch([record.source_url])
    except TinyFishCreditsExhaustedError as exc:
        logger.warning("tinyfish credits exhausted", extra={"record": record.source_identifier})
        return ExtractionOutcome(
            report=parse_report(
                source_text, title=record.title, disease_label=record.disease_label
            ),
            source_text=source_text,
            method=ExtractionMethod.DETERMINISTIC_PARSER,
            error=str(exc),
        )
    except ExternalServiceError as exc:
        logger.warning(
            "tinyfish fetch failed; using the WHO API narrative instead",
            extra={"record": record.source_identifier, "error": str(exc)},
        )
    else:
        if fetched.results and fetched.results[0].text.strip():
            source_text = fetched.results[0].text

    if not use_agent:
        return ExtractionOutcome(
            report=parse_report(
                source_text, title=record.title, disease_label=record.disease_label
            ),
            source_text=source_text,
            method=ExtractionMethod.TINYFISH_FETCH,
        )

    outcome = client.run_agent(record.source_url, OUTBREAK_EXTRACTION_GOAL, OUTPUT_SCHEMA)
    if not outcome.succeeded or outcome.result is None:
        logger.warning(
            "agent extraction unavailable; using the deterministic parser",
            extra={
                "record": record.source_identifier,
                "status": outcome.status,
                "error": outcome.error,
            },
        )
        return ExtractionOutcome(
            report=parse_report(
                source_text, title=record.title, disease_label=record.disease_label
            ),
            source_text=source_text,
            method=ExtractionMethod.TINYFISH_FETCH,
            agent_run_id=outcome.run_id,
            agent_steps=outcome.steps,
            error=outcome.error or f"agent run ended as {outcome.status}",
        )

    try:
        report = ExtractedReport.model_validate(outcome.result)
    except ValueError as exc:
        logger.warning(
            "agent result failed schema validation",
            extra={"record": record.source_identifier, "error": str(exc)},
        )
        return ExtractionOutcome(
            report=parse_report(
                source_text, title=record.title, disease_label=record.disease_label
            ),
            source_text=source_text,
            method=ExtractionMethod.TINYFISH_FETCH,
            agent_run_id=outcome.run_id,
            agent_steps=outcome.steps,
            error=f"schema validation failed: {exc}",
        )

    return ExtractionOutcome(
        report=report,
        source_text=source_text,
        method=ExtractionMethod.TINYFISH_AGENT,
        agent_run_id=outcome.run_id,
        agent_steps=outcome.steps,
    )
