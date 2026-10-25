"""SQLAlchemy models — the persisted data model.

Design notes that are not obvious from the column names:

* **Provenance is not optional.** Every table holding source-derived data
  carries the source URL, the publisher's identifier, the publication time and
  the retrieval time, plus the ingestion run that produced the row
  (AGENTS.md section 9.3).
* **Extraction status travels with the data.** An
  :class:`OutbreakObservation` whose numbers could not be found verbatim in the
  retrieved source text is stored with ``grounding_status='unverified'``. Such
  rows are displayed with their source link but excluded from every model
  input, which is enforced in the repository layer rather than by deleting the
  row — a rejected extraction is itself an auditable fact.
* **Counts are nullable.** A report that states deaths but not confirmed cases
  stores ``NULL`` for cases. Coalescing to zero would turn "not stated" into
  "none occurred".
* **Country-pair flows live in PostgreSQL** (at most ~200x200 directed rows),
  while airport-level topology stays in Parquet because it is large,
  read-only and only used during the build step.

See docs/data-model.md for the full field reference.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from endemica.db.base import Base, TimestampMixin
from endemica.schemas.common import (
    ExtractionMethod,
    ExtractionStatus,
    ValueType,
)

# Enum columns store the member *values* (the lowercase strings used in the
# API), so the database and the JSON contract cannot drift apart.
_VALUE_TYPE_ENUM = SAEnum(
    ValueType, name="value_type", values_callable=lambda e: [m.value for m in e]
)
_EXTRACTION_STATUS_ENUM = SAEnum(
    ExtractionStatus, name="extraction_status", values_callable=lambda e: [m.value for m in e]
)
_EXTRACTION_METHOD_ENUM = SAEnum(
    ExtractionMethod, name="extraction_method", values_callable=lambda e: [m.value for m in e]
)


def _uuid_pk() -> Mapped[uuid.UUID]:
    """A UUID primary key generated in Python.

    Generated client-side so an ingestion run can reference its own id in log
    lines before the transaction commits.
    """
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


class Country(Base, TimestampMixin):
    """A country or territory, keyed by ISO 3166-1 alpha-3.

    ISO-3 is the join key for every other table. Source country names are
    normalised to it during ingestion; an unmappable name is a validation
    failure, not a new country.
    """

    __tablename__ = "countries"

    iso3: Mapped[str] = mapped_column(String(3), primary_key=True)
    iso2: Mapped[str | None] = mapped_column(String(2), index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    official_name: Mapped[str | None] = mapped_column(String(256))
    region: Mapped[str | None] = mapped_column(String(64))
    subregion: Mapped[str | None] = mapped_column(String(64))
    who_region: Mapped[str | None] = mapped_column(
        String(8), comment="WHO region code (AFR, AMR, SEAR, EUR, EMR, WPR) where known."
    )

    population: Mapped[int | None] = mapped_column(
        Integer, comment="Total population, persons. Denominator N in the prevalence term."
    )
    population_year: Mapped[int | None] = mapped_column(Integer)
    population_source: Mapped[str | None] = mapped_column(String(128))

    # Population-weighted centroid is unavailable in the free datasets, so this
    # is the geometric centroid of the Natural Earth polygon. It is used for
    # the gravity model's distance term and for map placement, never for any
    # epidemiological claim about where people are.
    centroid_lat: Mapped[float | None] = mapped_column(Float)
    centroid_lon: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        CheckConstraint("population IS NULL OR population >= 0", name="population_non_negative"),
        CheckConstraint(
            "centroid_lat IS NULL OR (centroid_lat BETWEEN -90 AND 90)", name="lat_in_range"
        ),
        CheckConstraint(
            "centroid_lon IS NULL OR (centroid_lon BETWEEN -180 AND 180)", name="lon_in_range"
        ),
        {"comment": "Countries and territories with population and geometry reference data."},
    )


class DatasetVersion(Base, TimestampMixin):
    """One acquisition of one reference dataset.

    Powers `GET /health`'s freshness block and `just data-check`: the
    application can always say how old each dataset is and where it came from.
    """

    __tablename__ = "dataset_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    dataset: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reference_period: Mapped[str | None] = mapped_column(
        String(64), comment="Period the data describes, e.g. '2019' or '2024'."
    )
    record_count: Mapped[int | None] = mapped_column(Integer)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    license_note: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    __table_args__ = (
        Index("ix_dataset_versions_dataset_active", "dataset", "is_active"),
        {"comment": "Provenance and freshness for each loaded reference dataset."},
    )


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


class IngestionRun(Base, TimestampMixin):
    """One execution of the outbreak ingestion pipeline.

    Kept even when it fails: "the last run failed at 14:03 after 7 records" is
    the information an operator needs, and a failed run must never erase the
    records a previous successful run produced.
    """

    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="who_don")
    mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="Extraction mode actually used: 'tinyfish_agent' or 'direct_fetch'.",
    )
    trigger: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual", comment="manual | webhook | scheduled"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running", comment="running | succeeded | failed"
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    records_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    observations_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    observations_unverified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="Per-step counters and non-fatal warnings."
    )

    reports: Mapped[list[OutbreakReport]] = relationship(back_populates="run")

    __table_args__ = (
        CheckConstraint("status IN ('running','succeeded','failed')", name="status_known"),
        {"comment": "Audit trail of ingestion executions, including failures."},
    )


class OutbreakReport(Base, TimestampMixin):
    """One public-health outbreak bulletin, e.g. a WHO Disease Outbreak News item.

    The report is the unit of provenance. Numeric observations extracted from
    it live in :class:`OutbreakObservation` so that an unverifiable number can
    be rejected without discarding the report itself.
    """

    __tablename__ = "outbreak_reports"

    id: Mapped[uuid.UUID] = _uuid_pk()

    # --- Provenance -------------------------------------------------------
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_identifier: Mapped[str] = mapped_column(
        String(128), nullable=False, comment="Publisher's own id, e.g. WHO DON '2026-DON622'."
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="When the source says the counts were current, if not the publication time.",
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    license_note: Mapped[str | None] = mapped_column(Text)

    # --- Content ----------------------------------------------------------
    title: Mapped[str] = mapped_column(Text, nullable=False)
    disease_label: Mapped[str | None] = mapped_column(
        String(256), index=True, comment="Disease exactly as the source words it."
    )
    pathogen_key: Mapped[str | None] = mapped_column(
        String(64),
        index=True,
        comment="Endemica pathogen profile key this report maps to, or NULL if unmapped.",
    )
    disease_key: Mapped[str | None] = mapped_column(
        String(64),
        index=True,
        comment="Canonical disease key, so wording variants group into one disease.",
    )
    disease_name: Mapped[str | None] = mapped_column(
        String(128), index=True, comment="Canonical display name for disease_key."
    )
    disease_family: Mapped[str | None] = mapped_column(
        String(64), index=True, comment="Broad grouping, e.g. 'Viral haemorrhagic fever'."
    )
    summary_text: Mapped[str | None] = mapped_column(Text)
    narrative_text: Mapped[str | None] = mapped_column(
        Text,
        comment=(
            "Plain-text rendering of the source narrative. Retained as the "
            "grounding reference for every extracted number."
        ),
    )
    content_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Hash of the normalised narrative; makes re-ingestion idempotent.",
    )

    # --- Extraction -------------------------------------------------------
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        _EXTRACTION_METHOD_ENUM, nullable=False
    )
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        _EXTRACTION_STATUS_ENUM, nullable=False, index=True
    )
    validation_warnings: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL"), index=True
    )
    run: Mapped[IngestionRun | None] = relationship(back_populates="reports")
    observations: Mapped[list[OutbreakObservation]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("source_name", "source_identifier", name="uq_report_source_identifier"),
        Index("ix_outbreak_reports_published_desc", published_at.desc()),
        {"comment": "Source outbreak bulletins with full provenance."},
    )


class OutbreakObservation(Base, TimestampMixin):
    """Case and death counts attributed to one place by one report.

    Every count is nullable because reports routinely state some and omit
    others. ``grounding_status`` records whether the numbers were found
    verbatim in the retrieved text. A stored count on a ``verified`` or
    ``partial`` row passed that check; failing fields are stored as null and
    do not feed a model. An ``unverified`` row feeds nothing.
    """

    __tablename__ = "outbreak_observations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outbreak_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report: Mapped[OutbreakReport] = relationship(back_populates="observations")

    country_iso3: Mapped[str] = mapped_column(
        ForeignKey("countries.iso3", ondelete="RESTRICT"), nullable=False, index=True
    )
    country_name_as_reported: Mapped[str | None] = mapped_column(String(256))
    subnational_name: Mapped[str | None] = mapped_column(
        String(256), comment="Admin-1 or finer place name as reported, when stated."
    )

    cases_confirmed: Mapped[int | None] = mapped_column(Integer)
    cases_probable: Mapped[int | None] = mapped_column(Integer)
    cases_suspected: Mapped[int | None] = mapped_column(Integer)
    deaths: Mapped[int | None] = mapped_column(Integer)

    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    period_text: Mapped[str | None] = mapped_column(
        String(256), comment="Period as worded by the source, when it cannot be parsed to dates."
    )

    evidence_text: Mapped[str | None] = mapped_column(
        Text, comment="The source sentence each number was taken from."
    )
    grounding_status: Mapped[ExtractionStatus] = mapped_column(
        _EXTRACTION_STATUS_ENUM, nullable=False, index=True
    )
    grounding_detail: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="Per-field grounding verdicts from endemica.ingestion.grounding."
    )
    value_type: Mapped[ValueType] = mapped_column(_VALUE_TYPE_ENUM, nullable=False)
    data_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    corroboration_status: Mapped[str | None] = mapped_column(
        String(32),
        comment="corroborated, single_source, conflict, or gross_conflict.",
    )

    __table_args__ = (
        CheckConstraint(
            "cases_confirmed IS NULL OR cases_confirmed >= 0", name="cases_confirmed_non_negative"
        ),
        CheckConstraint(
            "cases_probable IS NULL OR cases_probable >= 0", name="cases_probable_non_negative"
        ),
        CheckConstraint(
            "cases_suspected IS NULL OR cases_suspected >= 0", name="cases_suspected_non_negative"
        ),
        CheckConstraint("deaths IS NULL OR deaths >= 0", name="deaths_non_negative"),
        CheckConstraint(
            "period_start IS NULL OR period_end IS NULL OR period_start <= period_end",
            name="period_ordered",
        ),
        # Deduplication key: one row per place and period within a report.
        UniqueConstraint(
            "report_id",
            "country_iso3",
            "subnational_name",
            "period_text",
            name="uq_observation_report_place_period",
        ),
        {"comment": "Case and death counts attributed to a place by a source report."},
    )


# ---------------------------------------------------------------------------
# Air-travel connectivity
# ---------------------------------------------------------------------------


class CountryFlow(Base, TimestampMixin):
    """Directed passenger flow between two countries, in passengers per day.

    ``value_type`` is the critical column:

    * ``observed`` — aggregated from a statistical agency's passenger counts.
    * ``estimated`` — predicted by the gravity model fitted on the observed
      rows. ``uncertainty_factor`` carries the multiplicative spread of that
      model's held-out residuals into the low/high risk band.

    Flight counts are never written here as if they were passenger counts.
    """

    __tablename__ = "country_flows"

    origin_iso3: Mapped[str] = mapped_column(
        ForeignKey("countries.iso3", ondelete="CASCADE"), primary_key=True
    )
    dest_iso3: Mapped[str] = mapped_column(
        ForeignKey("countries.iso3", ondelete="CASCADE"), primary_key=True
    )

    passengers_per_day: Mapped[float] = mapped_column(Float, nullable=False)
    value_type: Mapped[ValueType] = mapped_column(_VALUE_TYPE_ENUM, nullable=False, index=True)
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="e.g. 'eurostat_avia_par' or 'gravity_model'."
    )
    reference_period: Mapped[str | None] = mapped_column(String(32))
    uncertainty_factor: Mapped[float | None] = mapped_column(
        Float,
        comment=(
            "Multiplicative spread: the low/high band uses "
            "passengers / factor and passengers * factor. NULL for observed rows."
        ),
    )
    direct_route_count: Mapped[int | None] = mapped_column(
        Integer, comment="Scheduled airport-pair routes behind this flow (OpenFlights topology)."
    )
    cross_check_source: Mapped[str | None] = mapped_column(
        String(64), comment="Second passenger source this flow was compared with, when one exists."
    )
    cross_check_ratio: Mapped[float | None] = mapped_column(
        Float, comment="This source divided by the cross-check source. Near 1 means they agree."
    )

    __table_args__ = (
        CheckConstraint("passengers_per_day >= 0", name="passengers_non_negative"),
        CheckConstraint("origin_iso3 <> dest_iso3", name="no_self_flow"),
        CheckConstraint(
            "uncertainty_factor IS NULL OR uncertainty_factor >= 1",
            name="uncertainty_factor_at_least_one",
        ),
        Index("ix_country_flows_dest", "dest_iso3"),
        {"comment": "Directed country-pair passenger flows, observed or gravity-model estimated."},
    )


class GravityModelFit(Base, TimestampMixin):
    """A fitted passenger-flow gravity model and its held-out evaluation.

    Stored rather than recomputed so that every estimated flow can be traced
    to the exact coefficients and the exact measured error that produced it.
    Metrics here are the real output of
    :mod:`endemica.datasets.gravity`; no value in this table is ever written by
    hand.
    """

    __tablename__ = "gravity_model_fits"

    id: Mapped[uuid.UUID] = _uuid_pk()
    fitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    specification: Mapped[str] = mapped_column(
        Text, nullable=False, comment="The regression equation in words."
    )
    feature_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    coefficients: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    intercept: Mapped[float] = mapped_column(Float, nullable=False)

    training_source: Mapped[str] = mapped_column(String(128), nullable=False)
    training_period: Mapped[str | None] = mapped_column(String(32))
    n_train: Mapped[int] = mapped_column(Integer, nullable=False)
    n_test: Mapped[int] = mapped_column(Integer, nullable=False)
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False)

    metrics: Mapped[dict[str, float]] = mapped_column(
        JSONB,
        nullable=False,
        comment="Held-out metrics: r2_log, mae_log10, rmse_log10, median_ratio_error.",
    )
    residual_sigma_log10: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Standard deviation of held-out residuals on log10 scale; drives the band.",
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    notes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint("n_train > 0", name="n_train_positive"),
        CheckConstraint("n_test >= 0", name="n_test_non_negative"),
        {"comment": "Fitted gravity models with their measured held-out performance."},
    )


# ---------------------------------------------------------------------------
# Border policy (the sigma term)
# ---------------------------------------------------------------------------


class PolicyFlag(Base, TimestampMixin):
    """A candidate border or screening measure for one destination.

    OxCGRT ended in 2022, so a live outbreak has no policy tracker. A flag
    starts as ``pending_review`` and has **no effect on any model output**
    until a human confirms it: an extracted policy claim is not evidence.
    Default sigma stays 0 with a visible "no confirmed measure" label.
    """

    __tablename__ = "policy_flags"

    id: Mapped[uuid.UUID] = _uuid_pk()
    country_iso3: Mapped[str] = mapped_column(
        ForeignKey("countries.iso3", ondelete="CASCADE"), nullable=False, index=True
    )
    measure: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="entry_screening | quarantine | entry_ban | none_stated",
    )
    applies_to: Mapped[str | None] = mapped_column(
        String(256), comment="Origins or traveller groups the measure applies to, as stated."
    )
    effective_date: Mapped[date | None] = mapped_column(Date)
    sigma_if_confirmed: Mapped[float | None] = mapped_column(
        Float,
        comment=(
            "Screening effectiveness this measure would imply, 0-0.9. "
            "An assumption mapped from the measure type, not a measurement."
        ),
    )

    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(128))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending_review",
        index=True,
        comment="pending_review | confirmed | rejected",
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_note: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL")
    )

    __table_args__ = (
        CheckConstraint("status IN ('pending_review','confirmed','rejected')", name="status_known"),
        CheckConstraint(
            "measure IN ('entry_screening','quarantine','entry_ban','none_stated')",
            name="measure_known",
        ),
        CheckConstraint(
            "sigma_if_confirmed IS NULL OR (sigma_if_confirmed BETWEEN 0 AND 0.9)",
            name="sigma_in_documented_range",
        ),
        {"comment": "Human-confirmed border measures feeding the sigma term."},
    )


class ObservationCorroboration(Base):
    """One comparison between two sources' counts for the same place and disease."""

    __tablename__ = "observation_corroborations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    primary_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outbreak_observations.id", ondelete="CASCADE"), nullable=False
    )
    other_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("outbreak_observations.id", ondelete="CASCADE"), nullable=False
    )
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_value: Mapped[float] = mapped_column(Float, nullable=False)
    other_value: Mapped[float] = mapped_column(Float, nullable=False)
    aligned_value: Mapped[float | None] = mapped_column(Float)
    date_gap_days: Mapped[float | None] = mapped_column(Float)
    relative_difference: Mapped[float | None] = mapped_column(Float)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1")
