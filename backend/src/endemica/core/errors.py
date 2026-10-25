"""Application error types.

These are raised by services and translated into HTTP responses by the
exception handlers registered in :mod:`endemica.main`. Route handlers should
not construct :class:`fastapi.HTTPException` directly, so that the same service
layer can be reused by the CLI.
"""

from __future__ import annotations


class EndemicaError(Exception):
    """Base class for every error Endemica raises deliberately."""


class ConfigurationError(EndemicaError):
    """A required configuration value is missing or invalid."""


class NotFoundError(EndemicaError):
    """A requested entity does not exist.

    Attributes:
        entity: Human-readable entity name, e.g. ``"outbreak report"``.
        identifier: The identifier that was looked up.
    """

    def __init__(self, entity: str, identifier: object) -> None:
        self.entity = entity
        self.identifier = identifier
        super().__init__(f"{entity} '{identifier}' not found")


class DataValidationError(EndemicaError):
    """Externally supplied data failed Endemica's own validation rules.

    Distinct from :class:`pydantic.ValidationError`: this covers the
    domain-level checks in :mod:`endemica.ingestion.validate` (grounding,
    date sanity, ISO normalisation) rather than shape errors.

    Attributes:
        field: Name of the offending field, when the failure is field-specific.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)


class DataUnavailableError(EndemicaError):
    """A reference dataset needed for this operation has not been prepared.

    Raised instead of silently substituting zeros, so the API can answer
    "not estimable" with a reason rather than a fabricated number.
    """

    def __init__(self, dataset: str, hint: str | None = None) -> None:
        self.dataset = dataset
        self.hint = hint
        message = f"dataset '{dataset}' is not available"
        if hint:
            message = f"{message}: {hint}"
        super().__init__(message)


class ExternalServiceError(EndemicaError):
    """An upstream service failed or returned an unusable response.

    Attributes:
        service: Short service name used in logs and status reporting.
        status_code: HTTP status when the failure was an HTTP response.
        retryable: Whether retrying the same call could plausibly succeed.
    """

    def __init__(
        self,
        service: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        self.service = service
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(f"{service}: {message}")


class ModelInputError(EndemicaError):
    """A model received an input outside its documented domain.

    Epidemiological functions raise this (rather than returning ``nan``) so a
    programming error cannot propagate into a displayed probability.
    """
