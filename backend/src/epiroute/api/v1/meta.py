from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from epiroute.api.deps import DbSession
from epiroute.epidemiology.profiles import PROFILES
from epiroute.schemas.errors import ErrorResponse
from epiroute.schemas.outbreak import (
    GravityModelOut,
    IngestionRunOut,
    SourceListResponse,
)
from epiroute.schemas.risk import PathogenSummary
from epiroute.services import outbreaks as service

router = APIRouter(tags=["metadata"])


@router.get(
    "/sources",
    response_model=SourceListResponse,
    summary="Data sources with coverage, licence and known limitations",
)
def list_sources(session: DbSession) -> SourceListResponse:
    return service.list_sources(session)


@router.get(
    "/pathogens",
    response_model=list[PathogenSummary],
    summary="Pathogen parameter profiles",
)
def list_pathogens() -> list[PathogenSummary]:
    return [
        PathogenSummary(
            key=profile.key,
            label=profile.label,
            confidence=profile.confidence.value,
            establishment_estimable=profile.establishment_estimable,
            establishment_note=profile.establishment_note,
            references=list(profile.references),
        )
        for profile in PROFILES.values()
    ]


@router.get(
    "/model/gravity",
    response_model=GravityModelOut,
    summary="The fitted passenger-flow model and its held-out performance",
    responses={404: {"model": ErrorResponse, "description": "No model has been fitted."}},
)
def get_gravity_model(session: DbSession) -> GravityModelOut:
    return service.get_gravity_model(session)


@router.get(
    "/runs",
    response_model=list[IngestionRunOut],
    summary="Recent ingestion runs, including failures",
)
def list_runs(
    session: DbSession, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[IngestionRunOut]:
    return service.list_runs(session, limit=limit)
