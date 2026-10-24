from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi import Path as PathParam

from epiroute.api.deps import DbSession
from epiroute.schemas.errors import ErrorResponse
from epiroute.schemas.risk import RiskQuery, RiskResponse
from epiroute.services.forecast import rank_next_countries
from epiroute.services.risk import compute_risk

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get(
    "/next",
    summary="Countries most likely to report this disease next",
)
def get_next_countries(
    session: DbSession,
    disease_key: Annotated[str | None, Query()] = None,
    pathogen: Annotated[str | None, Query()] = None,
    horizon_days: Annotated[float, Query(ge=1, le=365)] = 28.0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, object]:
    query = RiskQuery(
        disease_key=disease_key,
        pathogen_key=pathogen,
        horizon_days=horizon_days,
        max_origins=limit,
    )
    return rank_next_countries(session, query, limit=limit)

_DESCRIPTION = """
Returns the three risk quantities for a destination, kept strictly separate:

* `presence` — whether a source report attributes grounded cases to this country.
  Flight connectivity is never an input.

With no `disease_key`, `pathogen` or `disease`, the disease is taken from the
destination's own most recent report, so two infected countries are each
answered about the disease they actually have. `pathogen.disease_source` states
which rule was applied.
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
    disease: Annotated[
        str | None, Query(description="Disease name as written on the source report.")
    ] = None,
    disease_key: Annotated[
        str | None,
        Query(
            description=(
                "Canonical disease key from /diseases/history. This is the precise "
                "filter; it groups the source's wording variants onto one disease."
            )
        ),
    ] = None,
    scope: Annotated[
        str,
        Query(
            pattern="^(disease|active)$",
            description=(
                "'disease' answers about one disease. 'active' sums over every disease "
                "reported anywhere in the last 90 days, so importation covers arriving "
                "with any of them; establishment is then not reported."
            ),
        ),
    ] = "disease",
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
        disease_label=disease,
        disease_key=disease_key,
        scope=scope,
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
