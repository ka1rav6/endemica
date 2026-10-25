from __future__ import annotations

from fastapi import APIRouter

from endemica.api.deps import DbSession
from endemica.schemas.outbreak import CountryListResponse
from endemica.services import outbreaks as service

router = APIRouter(prefix="/countries", tags=["reference"])


@router.get("", response_model=CountryListResponse, summary="List countries")
def list_countries(session: DbSession) -> CountryListResponse:
    return service.list_countries(session)
