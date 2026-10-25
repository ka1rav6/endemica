"""Health and readiness response models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from endemica.schemas.common import DataFreshness


class ComponentHealth(BaseModel):
    """Status of one subsystem the application depends on."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: Literal["ok", "degraded", "unavailable", "not_configured"]
    detail: str | None = None


class HealthResponse(BaseModel):
    """``GET /health`` payload.

    ``status`` is ``ok`` only when every *required* component is healthy. An
    unconfigured optional integration (TinyFish) reports
    ``not_configured`` and leaves the overall status at ``ok``, because the
    application is designed to run without it.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "degraded", "unavailable"]
    version: str
    environment: str
    checked_at: datetime
    components: Annotated[list[ComponentHealth], Field(default_factory=list)]
    data: Annotated[
        list[DataFreshness],
        Field(default_factory=list, description="Age and record count of each loaded dataset."),
    ]
