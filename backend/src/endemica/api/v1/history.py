from __future__ import annotations

from fastapi import APIRouter
from fastapi import Path as PathParam

from endemica.api.deps import DbSession
from endemica.schemas.errors import ErrorResponse
from endemica.schemas.outbreak import (
    ActiveSummaryResponse,
    CountryProfileResponse,
    DiseaseHistoryOut,
    DiseaseSpreadResponse,
)
from endemica.services import history as service

router = APIRouter(tags=["history"])


@router.get(
    "/diseases/history",
    response_model=list[DiseaseHistoryOut],
    summary="Every disease in the archive, past and present",
    description=(
        "One row per canonical disease, covering the whole WHO Disease Outbreak News "
        "archive rather than only current activity. Wording variants in the source "
        "titles are grouped onto one `disease_key`, and `source_labels` lists the "
        "variants that were folded in."
    ),
)
def list_disease_history(session: DbSession) -> list[DiseaseHistoryOut]:
    return service.list_disease_history(session)


@router.get(
    "/diseases/active",
    response_model=ActiveSummaryResponse,
    summary="Every disease reported anywhere in the last 90 days, as one picture",
    description=(
        "Drives the 'all active' view: which diseases are currently reported, which "
        "countries they are in, and the combined case and death totals. Pair it with "
        "`/risk/{iso3}?scope=active` for the matching probabilities."
    ),
)
def get_active_summary(session: DbSession) -> ActiveSummaryResponse:
    return service.get_active_summary(session)


@router.get(
    "/diseases/{disease_key}/spread",
    response_model=DiseaseSpreadResponse,
    summary="How one disease spread: which countries it reached, in what order",
    description=(
        "`countries` is ordered by first report, so it reads as the arrival sequence. "
        "`timeline` gives per-year reports and newly reached countries, which is what "
        "drives the historical playback on the map."
    ),
    responses={404: {"model": ErrorResponse, "description": "No such disease."}},
)
def get_disease_spread(session: DbSession, disease_key: str) -> DiseaseSpreadResponse:
    return service.get_disease_spread(session, disease_key)


@router.get(
    "/countries/{iso3}/profile",
    response_model=CountryProfileResponse,
    summary="Every disease ever reported for one country",
    responses={404: {"model": ErrorResponse, "description": "Unknown country."}},
)
def get_country_profile(
    session: DbSession, iso3: str = PathParam(min_length=3, max_length=3)
) -> CountryProfileResponse:
    return service.get_country_profile(session, iso3)
