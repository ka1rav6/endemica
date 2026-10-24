from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from epiroute.schemas.common import (
    Assumption,
    BandedQuantity,
    DataFreshness,
    Quantity,
    ResponseWarning,
    UnavailableReason,
    ValueType,
)


class PresenceStatus(StrEnum):
    REPORTED = "reported"
    NOT_REPORTED = "not_reported"
    NOT_ESTIMABLE = "not_estimable"


class LocalPresence(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: PresenceStatus
    value_type: ValueType
    last_reported_at: datetime | None = None
    cases_confirmed: Quantity | None = None
    deaths: Quantity | None = None
    report_count: int = 0
    source_urls: list[HttpUrl] = Field(default_factory=list)
    detail: str
    unavailable_reason: UnavailableReason | None = None


class OriginContributionOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    origin_iso3: str
    origin_name: str
    arrival_rate_per_day: float
    share_of_total: float
    passengers_per_day: float
    passengers_value_type: ValueType
    passengers_source: str
    prevalence_central: float
    prevalence_per_100k: float
    prevalence_value_type: ValueType
    effective_distance: float | None = None
    via_hubs: list[str] = Field(default_factory=list)
    reported_cases: int | None = None
    report_url: HttpUrl | None = None
    report_published_at: datetime | None = None


class ImportationRisk(BaseModel):
    model_config = ConfigDict(frozen=True)

    probability: BandedQuantity
    arrival_rate_per_day: BandedQuantity
    horizon_days: float
    is_saturated: bool = False
    origin_count_considered: int = 0
    origin_count_usable: int = 0
    top_origins: list[OriginContributionOut] = Field(default_factory=list)
    excluded_origins: list[dict[str, str]] = Field(default_factory=list)


class EstablishmentRisk(BaseModel):
    model_config = ConfigDict(frozen=True)

    probability_per_introduction: BandedQuantity
    probability_within_horizon: BandedQuantity
    horizon_days: float
    reproduction_number_used: BandedQuantity
    dispersion_used: BandedQuantity
    subcritical: bool = False
    detail: str


class ScenarioMarker(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    day_offset: float | None
    date: datetime | None = None
    threshold: float
    reached: bool
    detail: str


class PathogenSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str | None
    label: str
    confidence: str | None = None
    establishment_estimable: bool = True
    establishment_note: str | None = None
    references: list[str] = Field(default_factory=list)


class RiskResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    destination_iso3: str
    destination_name: str
    pathogen: PathogenSummary
    horizon_days: float
    computed_at: datetime
    model_version: str

    presence: LocalPresence
    importation: ImportationRisk
    establishment: EstablishmentRisk
    scenario_markers: list[ScenarioMarker] = Field(default_factory=list)

    assumptions: list[Assumption] = Field(default_factory=list)
    warnings: list[ResponseWarning] = Field(default_factory=list)
    data: list[DataFreshness] = Field(default_factory=list)
    disclaimer: str


class RiskQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    pathogen_key: str | None = None
    horizon_days: Annotated[float, Field(ge=1, le=365)] = 14.0
    underreporting_low: Annotated[float, Field(ge=1, le=100)] = 2.0
    underreporting_central: Annotated[float, Field(ge=1, le=100)] = 4.0
    underreporting_high: Annotated[float, Field(ge=1, le=100)] = 10.0
    alpha: Annotated[float, Field(ge=0, le=1)] | None = None
    sigma: Annotated[float, Field(ge=0, le=0.9)] = 0.0
    reproduction_number: Annotated[float, Field(ge=0, le=20)] | None = None
    dispersion_k: Annotated[float, Field(gt=0, le=1000)] | None = None
    passenger_scale: Annotated[float, Field(gt=0, le=10)] = 1.0
    threshold: Annotated[float, Field(gt=0, lt=1)] = 0.5
    max_origins: Annotated[int, Field(ge=1, le=50)] = 10
