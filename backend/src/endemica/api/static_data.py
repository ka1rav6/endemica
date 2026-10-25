from __future__ import annotations

from fastapi import APIRouter, Response, status

from endemica.api.deps import AppSettings
from endemica.core.errors import DataUnavailableError
from endemica.datasets.build import AIRPORTS_FILE, BOUNDARIES_FILE

router = APIRouter(prefix="/data", tags=["reference"])

_CACHE_CONTROL = "public, max-age=3600"


@router.get(
    "/country_boundaries.geojson",
    summary="Country boundary polygons for the map",
    response_class=Response,
    responses={
        200: {"content": {"application/geo+json": {}}},
        409: {"description": "The processed boundary file has not been built."},
    },
)
def country_boundaries(settings: AppSettings) -> Response:
    path = settings.processed_data_dir / BOUNDARIES_FILE
    if not path.exists():
        msg = "run `just data-build` to generate the boundary file"
        raise DataUnavailableError("country_boundaries", msg)
    return Response(
        content=path.read_bytes(),
        media_type="application/geo+json",
        status_code=status.HTTP_200_OK,
        headers={"Cache-Control": _CACHE_CONTROL},
    )


@router.get(
    "/airports.geojson",
    summary="Airports with at least one scheduled route, for the zoomed-in map",
    response_class=Response,
    responses={
        200: {"content": {"application/geo+json": {}}},
        409: {"description": "The processed airport file has not been built."},
    },
)
def airports(settings: AppSettings) -> Response:
    path = settings.processed_data_dir / AIRPORTS_FILE
    if not path.exists():
        msg = "run `just data-build` to generate the airport file"
        raise DataUnavailableError("airports", msg)
    return Response(
        content=path.read_bytes(),
        media_type="application/geo+json",
        status_code=status.HTTP_200_OK,
        headers={"Cache-Control": _CACHE_CONTROL},
    )
