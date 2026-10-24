from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi import Path as PathParam

from epiroute.api.deps import DbSession
from epiroute.schemas.errors import ErrorResponse
from epiroute.schemas.risk import RiskQuery, RiskResponse
from epiroute.services.risk import compute_risk

router = APIRouter(prefix="/risk", tags=["risk"])

_DESCRIPTION = """
Returns the three risk quantities for a destination, kept strictly separate:

* `presence` — whether a source report attributes grounded cases to this country.
  Flight connectivity is never an input.
* `importation` — probability that at least one infected traveller arrives within
  the horizon.
* `establishment` — probability that an introduction leads to sustained local
  transmission.

Every numeric field carries a `value_type`, and a field that cannot be computed is
`null` with an `unavailable_reason`. Bands are **scenario ranges**, not confidence
intervals; `band_basis` states how each was produced.
"""


@router.get(
    "/{destination_iso3}",
    response_model=RiskResponse,
    summary="Local presence, importation and establishment risk for a destination",
    description=_DESCRIPTION,
    responses={
        404: {"model": ErrorResponse, "description": "Unknown destination country."},
        422: {"model": ErrorResponse, "description": "A parameter is out of range."},
    },
)
def get_risk(
    session: DbSession,
    destination_iso3: Annotated[str, PathParam(min_length=3, max_length=3)],
    pathogen: Annotated[str | None, Query(description="Pathogen profile key.")] = None,
    horizon_days: Annotated[float, Query(ge=1, le=365)] = 14.0,
    underreporting_low: Annotated[float, Query(ge=1, le=100)] = 2.0,
    underreporting_central: Annotated[float, Query(ge=1, le=100)] = 4.0,
    underreporting_high: Annotated[float, Query(ge=1, le=100)] = 10.0,
    alpha: Annotated[float | None, Query(ge=0, le=1)] = None,
    sigma: Annotated[float, Query(ge=0, le=0.9)] = 0.0,
    reproduction_number: Annotated[float | None, Query(ge=0, le=20)] = None,
    dispersion_k: Annotated[float | None, Query(gt=0, le=1000)] = None,
    passenger_scale: Annotated[float, Query(gt=0, le=10)] = 1.0,
    threshold: Annotated[float, Query(gt=0, lt=1)] = 0.5,
    max_origins: Annotated[int, Query(ge=1, le=50)] = 10,
) -> RiskResponse:
    query = RiskQuery(
        pathogen_key=pathogen,
        horizon_days=horizon_days,
        underreporting_low=underreporting_low,
        underreporting_central=underreporting_central,
        underreporting_high=underreporting_high,
        alpha=alpha,
        sigma=sigma,
        reproduction_number=reproduction_number,
        dispersion_k=dispersion_k,
        passenger_scale=passenger_scale,
        threshold=threshold,
        max_origins=max_origins,
    )
    return compute_risk(session, destination_iso3, query)
