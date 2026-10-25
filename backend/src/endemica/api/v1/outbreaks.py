from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from endemica.api.deps import DbSession
from endemica.schemas.common import ExtractionStatus
from endemica.schemas.errors import ErrorResponse
from endemica.schemas.outbreak import (
    OutbreakListResponse,
    OutbreakReportDetail,
)
from endemica.services import outbreaks as service

router = APIRouter(prefix="/outbreaks", tags=["outbreaks"])


@router.get("", response_model=OutbreakListResponse, summary="List outbreak reports")
def list_outbreaks(
    session: DbSession,
    pathogen: Annotated[str | None, Query(description="Pathogen profile key.")] = None,
    country: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    since: Annotated[
        datetime | None, Query(description="Only reports published at or after this time.")
    ] = None,
    status: Annotated[
        ExtractionStatus | None, Query(description="Filter by extraction status.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OutbreakListResponse:
    return service.list_outbreaks(
        session,
        pathogen_key=pathogen,
        country_iso3=country,
        since=since,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{report_id}",
    response_model=OutbreakReportDetail,
    summary="One outbreak report with provenance and grounding verdicts",
    responses={404: {"model": ErrorResponse, "description": "No such report."}},
)
def get_outbreak(session: DbSession, report_id: str) -> OutbreakReportDetail:
    return service.get_outbreak(session, report_id)
