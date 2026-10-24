"""Health endpoint.

Deliberately unversioned and outside ``/api/v1``: deployment tooling and the
`just doctor` recipe rely on a stable path.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from epiroute.api.deps import AppSettings, DbSession
from epiroute.schemas.health import HealthResponse
from epiroute.services.health import build_health_response

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service and dependency health",
    responses={
        200: {"description": "All required components are healthy."},
        503: {
            "description": (
                "A required component is unavailable. The body still describes "
                "every component so an operator can see which one."
            )
        },
    },
)
def read_health(session: DbSession, settings: AppSettings, response: Response) -> HealthResponse:
    """Report application and dependency health.

    Returns HTTP 503 when a required component is down, while still returning
    the full component breakdown in the body.
    """
    payload = build_health_response(session, settings)
    if payload.status == "unavailable":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload
