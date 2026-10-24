from __future__ import annotations

from fastapi import APIRouter

from epiroute.api.deps import DbSession
from epiroute.schemas.outbreak import CountryListResponse
from epiroute.services import outbreaks as service

router = APIRouter(prefix="/countries", tags=["reference"])


@router.get("", response_model=CountryListResponse, summary="List countries")
def list_countries(session: DbSession) -> CountryListResponse:
    return service.list_countries(session)
