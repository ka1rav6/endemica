from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from epiroute.api.deps import DbSession
from epiroute.schemas.outbreak import RouteListResponse
from epiroute.services import outbreaks as service

router = APIRouter(prefix="/routes", tags=["reference"])


@router.get(
    "",
    response_model=RouteListResponse,
    summary="Country-pair passenger flows",
    description=(
        "Each row states whether its passenger volume is `observed` (from a statistical "
        "agency) or `estimated` (gravity model). Estimated rows carry the multiplicative "
        "`uncertainty_factor` derived from the model's held-out residual spread."
    ),
)
def list_routes(
    session: DbSession,
    origin: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    dest: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> RouteListResponse:
    return service.list_routes(session, origin_iso3=origin, dest_iso3=dest, limit=limit)
