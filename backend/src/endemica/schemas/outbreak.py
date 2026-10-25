from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from endemica.schemas.common import (
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


class DiseaseHistoryOut(BaseModel):
    """One canonical disease across the whole archive."""

    model_config = ConfigDict(frozen=True)

    disease_key: str
    disease_name: str
    disease_family: str | None = None
    pathogen_key: str | None = None
    report_count: int
    country_count: int
    grounded_country_count: int
    first_published_at: datetime | None = None
    last_published_at: datetime | None = None
    cases_confirmed: int | None = None
    cases_reported: int | None = Field(
        default=None,
        description=(
            "The widest case figure the source gave, which for cholera and yellow "
            "fever is usually suspected rather than confirmed cases. The death "
            "toll was counted over this figure, not over the confirmed one."
        ),
    )
    deaths: int | None = None
    counts_as_of: datetime | None = Field(
        default=None,
        description=(
            "When the counts on this row were current. Both numbers come from one "
            "bulletin about one episode, so a stale date means the source stopped "
            "reporting, not that the outbreak stopped."
        ),
    )
    counted_country_count: int = Field(
        default=0,
        description="Countries whose own case and death figures could be reconciled.",
    )
    unreconciled_country_count: int = Field(
        default=0,
        description=(
            "Countries left out of the totals because the source's death toll was "
            "larger than every case figure on the same report, so the two were "
            "counted over different areas."
        ),
    )
    source_labels: list[str] = Field(default_factory=list)


class CountrySpreadOut(BaseModel):
    """One country's involvement in one disease."""

    model_config = ConfigDict(frozen=True)

    country_iso3: str
    country_name: str
    centroid_lat: float | None = None
    centroid_lon: float | None = None
    report_count: int
    first_published_at: datetime | None = None
    last_published_at: datetime | None = None
    cases_confirmed: int | None = None
    cases_reported: int | None = Field(
        default=None,
        description=(
            "The widest case figure the source gave, which for cholera and yellow "
            "fever is usually suspected rather than confirmed cases. The death "
            "toll was counted over this figure, not over the confirmed one."
        ),
    )
    deaths: int | None = None
    counts_as_of: datetime | None = Field(
        default=None,
        description=(
            "When the counts on this row were current. Both numbers come from one "
            "bulletin about one episode, so a stale date means the source stopped "
            "reporting, not that the outbreak stopped."
        ),
    )
    counts_reconciled: bool = True
    grounded: bool
    report_url: HttpUrl | None = None
    report_title: str | None = None
    arrival_order: int


class DiseaseTimelineOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    year: int
    report_count: int
    country_count: int
    new_country_count: int
    cumulative_country_count: int
    new_countries: list[str] = Field(default_factory=list)
    cases_confirmed: int | None = None
    deaths: int | None = None


class DiseaseSpreadResponse(BaseModel):
    """A disease's full recorded history: who it reached, when, and how widely."""

    model_config = ConfigDict(frozen=True)

    disease_key: str
    disease_name: str
    disease_family: str | None = None
    pathogen_key: str | None = None
    report_count: int
    country_count: int
    first_published_at: datetime | None = None
    last_published_at: datetime | None = None
    cases_confirmed: int | None = None
    cases_reported: int | None = None
    deaths: int | None = None
    counts_as_of: datetime | None = None
    counted_country_count: int = 0
    unreconciled_country_count: int = 0
    coverage_note: str | None = Field(
        default=None,
        description=(
            "Set when the newest figure is much older than the newest report, "
            "which means the source carried on naming the disease after it "
            "stopped publishing counts for it."
        ),
    )
    is_active: bool
    countries: list[CountrySpreadOut] = Field(default_factory=list)
    timeline: list[DiseaseTimelineOut] = Field(default_factory=list)
    note: str


class CountryDiseaseOut(BaseModel):
    """One disease ever reported for one country."""

    model_config = ConfigDict(frozen=True)

    disease_key: str
    disease_name: str
    disease_family: str | None = None
    pathogen_key: str | None = None
    report_count: int
    first_published_at: datetime | None = None
    last_published_at: datetime | None = None
    cases_confirmed: int | None = None
    cases_reported: int | None = Field(
        default=None,
        description=(
            "The widest case figure the source gave, which for cholera and yellow "
            "fever is usually suspected rather than confirmed cases. The death "
            "toll was counted over this figure, not over the confirmed one."
        ),
    )
    deaths: int | None = None
    counts_as_of: datetime | None = Field(
        default=None,
        description=(
            "When the counts on this row were current. Both numbers come from one "
            "bulletin about one episode, so a stale date means the source stopped "
            "reporting, not that the outbreak stopped."
        ),
    )
    counts_reconciled: bool = True
    grounded: bool
    is_active: bool
    report_url: HttpUrl | None = None


class CountryProfileResponse(BaseModel):
    """Everything Endemica holds about one country's outbreak record."""

    model_config = ConfigDict(frozen=True)

    iso3: str
    name: str
    region: str | None = None
    subregion: str | None = None
    population: int | None = None
    centroid_lat: float | None = None
    centroid_lon: float | None = None
    inbound_flow_count: int = 0
    report_count: int
    active_disease_count: int
    diseases: list[CountryDiseaseOut] = Field(default_factory=list)


class ActiveDiseaseOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    disease_key: str
    disease_name: str
    pathogen_key: str | None = None
    country_count: int
    report_count: int
    last_published_at: datetime | None = None


class ActiveCountryOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    country_iso3: str
    country_name: str
    centroid_lat: float | None = None
    centroid_lon: float | None = None
    disease_count: int
    report_count: int
    cases_confirmed: int | None = None
    cases_reported: int | None = Field(
        default=None,
        description=(
            "The widest case figure the source gave, which for cholera and yellow "
            "fever is usually suspected rather than confirmed cases. The death "
            "toll was counted over this figure, not over the confirmed one."
        ),
    )
    deaths: int | None = None
    last_published_at: datetime | None = None
    disease_keys: list[str] = Field(default_factory=list)
    disease_names: list[str] = Field(default_factory=list)


class ActiveSummaryResponse(BaseModel):
    """Everything reported anywhere in the recent window, as one picture."""

    model_config = ConfigDict(frozen=True)

    window_days: int
    since: datetime
    disease_count: int
    country_count: int
    report_count: int
    cases_confirmed: int | None = None
    deaths: int | None = None
    diseases: list[ActiveDiseaseOut] = Field(default_factory=list)
    countries: list[ActiveCountryOut] = Field(default_factory=list)
    note: str
