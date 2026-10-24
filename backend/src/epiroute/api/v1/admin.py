from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body
from pydantic import BaseModel, ConfigDict, Field

from epiroute.api.deps import AppSettings, DbSession
from epiroute.ingestion.pipeline import run_ingestion
from epiroute.schemas.errors import ErrorResponse

router = APIRouter(prefix="/admin", tags=["admin"])


class IngestRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: Annotated[int, Field(ge=1, le=200)] = 20
    use_agent: bool = Field(
        default=False,
        description=(
            "Run TinyFish Agent extraction. Billed per step, so it is off by default; "
            "the deterministic parser runs either way."
        ),
    )


class IngestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    mode: str
    status: str
    records_seen: int
    records_created: int
    records_updated: int
    records_skipped: int
    observations_created: int
    observations_unverified: int
    warning_codes: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Run a WHO Disease Outbreak News ingestion pass",
    description=(
        "Synchronous. A failure for one record is isolated: previously stored records "
        "are never removed, and the run record retains the error."
    ),
    responses={502: {"model": ErrorResponse, "description": "The WHO API was unreachable."}},
)
def trigger_ingest(
    session: DbSession,
    settings: AppSettings,
    request: Annotated[IngestRequest, Body()] = IngestRequest(),
) -> IngestResponse:
    summary = run_ingestion(
        session,
        limit=request.limit,
        settings=settings,
        use_agent=request.use_agent,
        trigger="manual",
    )
    session.commit()

    codes: dict[str, int] = {}
    for warning in summary.warnings:
        code = str(warning.get("code"))
        codes[code] = codes.get(code, 0) + 1

    return IngestResponse(
        run_id=str(summary.run_id),
        mode=summary.mode,
        status=summary.status,
        records_seen=summary.records_seen,
        records_created=summary.records_created,
        records_updated=summary.records_updated,
        records_skipped=summary.records_skipped,
        observations_created=summary.observations_created,
        observations_unverified=summary.observations_unverified,
        warning_codes=codes,
        errors=summary.errors,
    )
