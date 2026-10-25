"""The single error envelope returned by every failing endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    """One field-level problem within an error response."""

    model_config = ConfigDict(frozen=True)

    field: str | None = None
    message: str


class ErrorResponse(BaseModel):
    """Uniform error body.

    Internal exception text and stack traces are never included: ``code`` is a
    stable machine-readable string and ``message`` is written for an operator.
    """

    model_config = ConfigDict(frozen=True)

    code: str = Field(description="Stable error code, e.g. 'not_found'.")
    message: str = Field(description="Human-readable summary, safe to display.")
    details: list[ErrorDetail] = Field(default_factory=list)
