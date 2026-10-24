from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from epiroute.schemas.common import (
    ExtractionMethod,
    ExtractionStatus,
    Provenance,
    ValueType,
)


class ObservationOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    country_iso3: str
    country_name: str
    country_name_as_reported: str | None = None
    subnational_name: str | None = None
    cases_confirmed: int | None = None
    cases_probable: int | None = None
    cases_suspected: int | None = None
    deaths: int | None = None
    period_start: date | None = None
    period_end: date | None = None
    period_text: str | None = None
    evidence_text: str | None = None
    grounding_status: ExtractionStatus
    value_type: ValueType
    usable_for_models: bool


class GroundingFieldOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    value: int
    verdict: str
    detail: str
    context: str | None = None


class OutbreakReportOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    disease_label: str | None = None
    pathogen_key: str | None = None
    summary_text: str | None = None
    provenance: Provenance
    extraction_method: ExtractionMethod
    extraction_status: ExtractionStatus
    countries: list[str] = Field(default_factory=list)
    observations: list[ObservationOut] = Field(default_factory=list)
    warning_count: int = 0


class OutbreakReportDetail(OutbreakReportOut):
    model_config = ConfigDict(frozen=True)

    narrative_text: str | None = None
    validation_warnings: list[dict[str, object]] = Field(default_factory=list)
    grounding_fields: list[GroundingFieldOut] = Field(default_factory=list)


class OutbreakListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    limit: int
    offset: int
    items: list[OutbreakReportOut] = Field(default_factory=list)


class CountryOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    iso3: str
    iso2: str | None = None
    name: str
    region: str | None = None
    subregion: str | None = None
    population: int | None = None
    population_year: int | None = None
    centroid_lat: float | None = None
    centroid_lon: float | None = None
    has_reported_outbreak: bool = False
    diseases: list[str] = Field(default_factory=list)
    inbound_flow_count: int = 0


class DiseaseOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    disease_label: str
    pathogen_key: str | None = None
    country_count: int
    report_count: int
    latest_published_at: datetime | None = None


class CountryListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    items: list[CountryOut] = Field(default_factory=list)


class RouteOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    origin_iso3: str
    origin_name: str
    dest_iso3: str
    dest_name: str
    passengers_per_day: float
    value_type: ValueType
    source: str
    reference_period: str | None = None
    uncertainty_factor: float | None = None
    direct_route_count: int | None = None
    origin_lat: float | None = None
    origin_lon: float | None = None
    dest_lat: float | None = None
    dest_lon: float | None = None


class RouteListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    items: list[RouteOut] = Field(default_factory=list)


class IngestionRunOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    source: str
    mode: str
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    records_seen: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    observations_created: int = 0
    observations_unverified: int = 0
    error_code: str | None = None
    error_message: str | None = None
    detail: dict[str, object] | None = None


class SourceOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    kind: str
    url: HttpUrl | None = None
    coverage: str
    licence: str
    limitations: list[str] = Field(default_factory=list)
    fields_used: list[str] = Field(default_factory=list)
    retrieved_at: datetime | None = None
    record_count: int | None = None
    notes: str | None = None


class SourceListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[SourceOut] = Field(default_factory=list)


class GravityModelOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    fitted_at: datetime
    specification: str
    training_source: str
    training_period: str | None = None
    n_train: int
    n_test: int
    random_seed: int
    intercept: float
    coefficients: dict[str, float]
    metrics: dict[str, float]
    residual_sigma_log10: float
    uncertainty_factor: float
    notes: dict[str, object] | None = None
    caveat: str
