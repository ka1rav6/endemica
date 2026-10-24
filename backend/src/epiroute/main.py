"""FastAPI application factory and process entry point.

Run in development with ``just dev-backend``. The module-level ``app`` object
is what uvicorn imports.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from epiroute import __version__
from epiroute.api import health as health_router
from epiroute.core.config import Settings, get_settings
from epiroute.core.errors import (
    DataUnavailableError,
    DataValidationError,
    EpiRouteError,
    ExternalServiceError,
    NotFoundError,
)
from epiroute.core.logging import configure_logging
from epiroute.schemas.errors import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)

DESCRIPTION = """
EpiRoute connects public-health outbreak reports to the global air-travel
network and publishes three *separate* quantities for a destination:

1. **Local presence** — is there evidence the pathogen is already there?
2. **Importation risk** — probability that at least one infected traveller
   arrives within a time horizon.
3. **Local establishment risk** — probability that an introduction leads to
   sustained local transmission.

Every numeric field carries a `value_type` of `observed`, `estimated`,
`modelled`, `scenario` or `unknown`. A value that cannot be computed is
returned as `null` with an `unavailable_reason` — never as `0`.

For situational awareness and education only. Not a diagnostic tool, not an
official forecast, and not a substitute for WHO or national travel guidance.
"""


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configure logging at startup and dispose the engine at shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "epiroute starting",
        extra={
            "version": __version__,
            "environment": settings.env,
            "database": settings.safe_database_url,
            "tinyfish_enabled": settings.tinyfish_enabled,
        },
    )
    yield
    # Close pooled connections so a reload or container stop is clean.
    from epiroute.db.session import reset_engine_cache

    reset_engine_cache()
    logger.info("epiroute stopped")


def _error_response(
    code: str, message: str, http_status: int, details: list[ErrorDetail] | None = None
) -> JSONResponse:
    """Build a uniform error body."""
    payload = ErrorResponse(code=code, message=message, details=details or [])
    return JSONResponse(status_code=http_status, content=payload.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI) -> None:
    """Translate domain errors into the uniform error envelope.

    Keeping the mapping here means services raise meaningful exceptions and
    never import FastAPI, so the same services are usable from the CLI.
    """

    @app.exception_handler(NotFoundError)
    async def _not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
        return _error_response("not_found", str(exc), status.HTTP_404_NOT_FOUND)

    @app.exception_handler(DataValidationError)
    async def _validation_failure(_request: Request, exc: DataValidationError) -> JSONResponse:
        details = [ErrorDetail(field=exc.field, message=str(exc))] if exc.field else []
        return _error_response(
            "validation_failed", str(exc), status.HTTP_422_UNPROCESSABLE_CONTENT, details
        )

    @app.exception_handler(DataUnavailableError)
    async def _data_unavailable(_request: Request, exc: DataUnavailableError) -> JSONResponse:
        # 409 rather than 404: the endpoint exists and the request is valid,
        # but a prerequisite dataset has not been prepared.
        return _error_response("data_unavailable", str(exc), status.HTTP_409_CONFLICT)

    @app.exception_handler(ExternalServiceError)
    async def _external(_request: Request, exc: ExternalServiceError) -> JSONResponse:
        logger.warning(
            "external service error",
            extra={"service": exc.service, "upstream_status": exc.status_code},
        )
        return _error_response(
            "upstream_unavailable",
            f"{exc.service} is unavailable. Previously cached data is unaffected.",
            status.HTTP_502_BAD_GATEWAY,
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            ErrorDetail(field=".".join(str(p) for p in err["loc"][1:]) or None, message=err["msg"])
            for err in exc.errors()
        ]
        return _error_response(
            "invalid_request",
            "One or more request parameters are invalid.",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            details,
        )

    @app.exception_handler(EpiRouteError)
    async def _fallback(_request: Request, _exc: EpiRouteError) -> JSONResponse:
        # Deliberate last resort for our own exception hierarchy. The message
        # is logged with its traceback but not returned to the client.
        logger.exception("unhandled EpiRoute error")
        return _error_response(
            "internal_error",
            "An internal error occurred. See the server log for details.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Args:
        settings: Override settings, used by tests. Defaults to the
            process-wide settings.

    Returns:
        A configured :class:`fastapi.FastAPI` instance.
    """
    settings = settings or get_settings()

    app = FastAPI(
        title="EpiRoute API",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-TinyFish-Signature"],
    )

    register_exception_handlers(app)
    app.include_router(health_router.router)
    return app


app = create_app()
