"""Initial EpiRoute schema.

Creates the eight tables described in docs/data-model.md: the reference data
(countries, dataset_versions), the ingestion audit trail (ingestion_runs,
outbreak_reports, outbreak_observations), the connectivity layer
(country_flows, gravity_model_fits) and the border-policy review queue
(policy_flags).

Revision ID: 9b1f01336904
Revises:
Create Date: 2026-10-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "9b1f01336904"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# PostgreSQL ENUM types need explicit handling in both directions.
#
# Implicit creation (the default when a CREATE TABLE mentions the type) fails
# if the type already exists, and `op.drop_table` never drops the type at all.
# So the types are created once up front with `checkfirst=True`, the column
# definitions below are marked `create_type=False`, and `downgrade` drops them
# after the tables. Without this, `just db-reset` fails on its second run with
# "type value_type already exists".
_VALUE_TYPE = postgresql.ENUM(
    "observed",
    "estimated",
    "modelled",
    "scenario",
    "unknown",
    name="value_type",
    create_type=False,
)
_EXTRACTION_STATUS = postgresql.ENUM(
    "verified",
    "unverified",
    "partial",
    "failed",
    "not_attempted",
    name="extraction_status",
    create_type=False,
)
_EXTRACTION_METHOD = postgresql.ENUM(
    "who_api_field",
    "deterministic_parser",
    "tinyfish_agent",
    "tinyfish_fetch",
    name="extraction_method",
    create_type=False,
)
_ENUM_TYPES = (_VALUE_TYPE, _EXTRACTION_STATUS, _EXTRACTION_METHOD)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in _ENUM_TYPES:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "countries",
        sa.Column("iso3", sa.String(length=3), nullable=False),
        sa.Column("iso2", sa.String(length=2), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("official_name", sa.String(length=256), nullable=True),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("subregion", sa.String(length=64), nullable=True),
        sa.Column(
            "who_region",
            sa.String(length=8),
            nullable=True,
            comment="WHO region code (AFR, AMR, SEAR, EUR, EMR, WPR) where known.",
        ),
        sa.Column(
            "population",
            sa.Integer(),
            nullable=True,
            comment="Total population, persons. Denominator N in the prevalence term.",
        ),
        sa.Column("population_year", sa.Integer(), nullable=True),
        sa.Column("population_source", sa.String(length=128), nullable=True),
        sa.Column("centroid_lat", sa.Float(), nullable=True),
        sa.Column("centroid_lon", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "centroid_lat IS NULL OR (centroid_lat BETWEEN -90 AND 90)",
            name=op.f("ck_countries_lat_in_range"),
        ),
        sa.CheckConstraint(
            "centroid_lon IS NULL OR (centroid_lon BETWEEN -180 AND 180)",
            name=op.f("ck_countries_lon_in_range"),
        ),
        sa.CheckConstraint(
            "population IS NULL OR population >= 0",
            name=op.f("ck_countries_population_non_negative"),
        ),
        sa.PrimaryKeyConstraint("iso3", name=op.f("pk_countries")),
        comment="Countries and territories with population and geometry reference data.",
    )
    op.create_index(op.f("ix_countries_iso2"), "countries", ["iso2"], unique=False)
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("dataset", sa.String(length=64), nullable=False),
        sa.Column("source_name", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reference_period",
            sa.String(length=64),
            nullable=True,
            comment="Period the data describes, e.g. '2019' or '2024'.",
        ),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("license_note", sa.Text(), nullable=True),
        sa.Column("notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_versions")),
        comment="Provenance and freshness for each loaded reference dataset.",
    )
    op.create_index(
        op.f("ix_dataset_versions_dataset"), "dataset_versions", ["dataset"], unique=False
    )
    op.create_index(
        "ix_dataset_versions_dataset_active",
        "dataset_versions",
        ["dataset", "is_active"],
        unique=False,
    )
    op.create_table(
        "gravity_model_fits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("fitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "specification", sa.Text(), nullable=False, comment="The regression equation in words."
        ),
        sa.Column("feature_names", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("coefficients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("intercept", sa.Float(), nullable=False),
        sa.Column("training_source", sa.String(length=128), nullable=False),
        sa.Column("training_period", sa.String(length=32), nullable=True),
        sa.Column("n_train", sa.Integer(), nullable=False),
        sa.Column("n_test", sa.Integer(), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=False),
        sa.Column(
            "metrics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Held-out metrics: r2_log, mae_log10, rmse_log10, median_ratio_error.",
        ),
        sa.Column(
            "residual_sigma_log10",
            sa.Float(),
            nullable=False,
            comment="Standard deviation of held-out residuals on log10 scale; drives the band.",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("n_test >= 0", name=op.f("ck_gravity_model_fits_n_test_non_negative")),
        sa.CheckConstraint("n_train > 0", name=op.f("ck_gravity_model_fits_n_train_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gravity_model_fits")),
        comment="Fitted gravity models with their measured held-out performance.",
    )
    op.create_index(
        op.f("ix_gravity_model_fits_is_active"), "gravity_model_fits", ["is_active"], unique=False
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "mode",
            sa.String(length=32),
            nullable=False,
            comment="Extraction mode actually used: 'tinyfish_agent' or 'direct_fetch'.",
        ),
        sa.Column(
            "trigger", sa.String(length=32), nullable=False, comment="manual | webhook | scheduled"
        ),
        sa.Column(
            "status", sa.String(length=16), nullable=False, comment="running | succeeded | failed"
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_seen", sa.Integer(), nullable=False),
        sa.Column("records_created", sa.Integer(), nullable=False),
        sa.Column("records_updated", sa.Integer(), nullable=False),
        sa.Column("records_skipped", sa.Integer(), nullable=False),
        sa.Column("observations_created", sa.Integer(), nullable=False),
        sa.Column("observations_unverified", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Per-step counters and non-fatal warnings.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')",
            name=op.f("ck_ingestion_runs_status_known"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_runs")),
        comment="Audit trail of ingestion executions, including failures.",
    )
    op.create_table(
        "country_flows",
        sa.Column("origin_iso3", sa.String(length=3), nullable=False),
        sa.Column("dest_iso3", sa.String(length=3), nullable=False),
        sa.Column("passengers_per_day", sa.Float(), nullable=False),
        sa.Column("value_type", _VALUE_TYPE, nullable=False),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            comment="e.g. 'eurostat_avia_par' or 'gravity_model'.",
        ),
        sa.Column("reference_period", sa.String(length=32), nullable=True),
        sa.Column(
            "uncertainty_factor",
            sa.Float(),
            nullable=True,
            comment="Multiplicative spread: the low/high band uses passengers / factor and passengers * factor. NULL for observed rows.",
        ),
        sa.Column(
            "direct_route_count",
            sa.Integer(),
            nullable=True,
            comment="Scheduled airport-pair routes behind this flow (OpenFlights topology).",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("origin_iso3 <> dest_iso3", name=op.f("ck_country_flows_no_self_flow")),
        sa.CheckConstraint(
            "passengers_per_day >= 0", name=op.f("ck_country_flows_passengers_non_negative")
        ),
        sa.CheckConstraint(
            "uncertainty_factor IS NULL OR uncertainty_factor >= 1",
            name=op.f("ck_country_flows_uncertainty_factor_at_least_one"),
        ),
        sa.ForeignKeyConstraint(
            ["dest_iso3"],
            ["countries.iso3"],
            name=op.f("fk_country_flows_dest_iso3_countries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["origin_iso3"],
            ["countries.iso3"],
            name=op.f("fk_country_flows_origin_iso3_countries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("origin_iso3", "dest_iso3", name=op.f("pk_country_flows")),
        comment="Directed country-pair passenger flows, observed or gravity-model estimated.",
    )
    op.create_index("ix_country_flows_dest", "country_flows", ["dest_iso3"], unique=False)
    op.create_index(
        op.f("ix_country_flows_value_type"), "country_flows", ["value_type"], unique=False
    )
    op.create_table(
        "outbreak_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_name", sa.String(length=128), nullable=False),
        sa.Column(
            "source_identifier",
            sa.String(length=128),
            nullable=False,
            comment="Publisher's own id, e.g. WHO DON '2026-DON622'.",
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("license_note", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "disease_label",
            sa.String(length=256),
            nullable=True,
            comment="Disease exactly as the source words it.",
        ),
        sa.Column(
            "pathogen_key",
            sa.String(length=64),
            nullable=True,
            comment="EpiRoute pathogen profile key this report maps to, or NULL if unmapped.",
        ),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column(
            "narrative_text",
            sa.Text(),
            nullable=True,
            comment="Plain-text rendering of the source narrative. Retained as the grounding reference for every extracted number.",
        ),
        sa.Column(
            "content_sha256",
            sa.String(length=64),
            nullable=False,
            comment="Hash of the normalised narrative; makes re-ingestion idempotent.",
        ),
        sa.Column("extraction_method", _EXTRACTION_METHOD, nullable=False),
        sa.Column("extraction_status", _EXTRACTION_STATUS, nullable=False),
        sa.Column("validation_warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_outbreak_reports_run_id_ingestion_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbreak_reports")),
        sa.UniqueConstraint("source_name", "source_identifier", name="uq_report_source_identifier"),
        comment="Source outbreak bulletins with full provenance.",
    )
    op.create_index(
        op.f("ix_outbreak_reports_disease_label"),
        "outbreak_reports",
        ["disease_label"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbreak_reports_extraction_status"),
        "outbreak_reports",
        ["extraction_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbreak_reports_pathogen_key"), "outbreak_reports", ["pathogen_key"], unique=False
    )
    op.create_index(
        "ix_outbreak_reports_published_desc",
        "outbreak_reports",
        [sa.literal_column("published_at DESC")],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbreak_reports_run_id"), "outbreak_reports", ["run_id"], unique=False
    )
    op.create_table(
        "policy_flags",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("country_iso3", sa.String(length=3), nullable=False),
        sa.Column(
            "measure",
            sa.String(length=32),
            nullable=False,
            comment="entry_screening | quarantine | entry_ban | none_stated",
        ),
        sa.Column(
            "applies_to",
            sa.String(length=256),
            nullable=True,
            comment="Origins or traveller groups the measure applies to, as stated.",
        ),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column(
            "sigma_if_confirmed",
            sa.Float(),
            nullable=True,
            comment="Screening effectiveness this measure would imply, 0-0.9. An assumption mapped from the measure type, not a measurement.",
        ),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_name", sa.String(length=128), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            comment="pending_review | confirmed | rejected",
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_note", sa.Text(), nullable=True),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "measure IN ('entry_screening','quarantine','entry_ban','none_stated')",
            name=op.f("ck_policy_flags_measure_known"),
        ),
        sa.CheckConstraint(
            "status IN ('pending_review','confirmed','rejected')",
            name=op.f("ck_policy_flags_status_known"),
        ),
        sa.CheckConstraint(
            "sigma_if_confirmed IS NULL OR (sigma_if_confirmed BETWEEN 0 AND 0.9)",
            name=op.f("ck_policy_flags_sigma_in_documented_range"),
        ),
        sa.ForeignKeyConstraint(
            ["country_iso3"],
            ["countries.iso3"],
            name=op.f("fk_policy_flags_country_iso3_countries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["ingestion_runs.id"],
            name=op.f("fk_policy_flags_run_id_ingestion_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_flags")),
        comment="Human-confirmed border measures feeding the sigma term.",
    )
    op.create_index(
        op.f("ix_policy_flags_country_iso3"), "policy_flags", ["country_iso3"], unique=False
    )
    op.create_index(op.f("ix_policy_flags_status"), "policy_flags", ["status"], unique=False)
    op.create_table(
        "outbreak_observations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("country_iso3", sa.String(length=3), nullable=False),
        sa.Column("country_name_as_reported", sa.String(length=256), nullable=True),
        sa.Column(
            "subnational_name",
            sa.String(length=256),
            nullable=True,
            comment="Admin-1 or finer place name as reported, when stated.",
        ),
        sa.Column("cases_confirmed", sa.Integer(), nullable=True),
        sa.Column("cases_probable", sa.Integer(), nullable=True),
        sa.Column("cases_suspected", sa.Integer(), nullable=True),
        sa.Column("deaths", sa.Integer(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column(
            "period_text",
            sa.String(length=256),
            nullable=True,
            comment="Period as worded by the source, when it cannot be parsed to dates.",
        ),
        sa.Column(
            "evidence_text",
            sa.Text(),
            nullable=True,
            comment="The source sentence each number was taken from.",
        ),
        sa.Column("grounding_status", _EXTRACTION_STATUS, nullable=False),
        sa.Column(
            "grounding_detail",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Per-field grounding verdicts from epiroute.ingestion.grounding.",
        ),
        sa.Column("value_type", _VALUE_TYPE, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "cases_confirmed IS NULL OR cases_confirmed >= 0",
            name=op.f("ck_outbreak_observations_cases_confirmed_non_negative"),
        ),
        sa.CheckConstraint(
            "cases_probable IS NULL OR cases_probable >= 0",
            name=op.f("ck_outbreak_observations_cases_probable_non_negative"),
        ),
        sa.CheckConstraint(
            "cases_suspected IS NULL OR cases_suspected >= 0",
            name=op.f("ck_outbreak_observations_cases_suspected_non_negative"),
        ),
        sa.CheckConstraint(
            "deaths IS NULL OR deaths >= 0",
            name=op.f("ck_outbreak_observations_deaths_non_negative"),
        ),
        sa.CheckConstraint(
            "period_start IS NULL OR period_end IS NULL OR period_start <= period_end",
            name=op.f("ck_outbreak_observations_period_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["country_iso3"],
            ["countries.iso3"],
            name=op.f("fk_outbreak_observations_country_iso3_countries"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["outbreak_reports.id"],
            name=op.f("fk_outbreak_observations_report_id_outbreak_reports"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbreak_observations")),
        sa.UniqueConstraint(
            "report_id",
            "country_iso3",
            "subnational_name",
            "period_text",
            name="uq_observation_report_place_period",
        ),
        comment="Case and death counts attributed to a place by a source report.",
    )
    op.create_index(
        op.f("ix_outbreak_observations_country_iso3"),
        "outbreak_observations",
        ["country_iso3"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbreak_observations_grounding_status"),
        "outbreak_observations",
        ["grounding_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outbreak_observations_report_id"),
        "outbreak_observations",
        ["report_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_outbreak_observations_report_id"), table_name="outbreak_observations")
    op.drop_index(
        op.f("ix_outbreak_observations_grounding_status"), table_name="outbreak_observations"
    )
    op.drop_index(op.f("ix_outbreak_observations_country_iso3"), table_name="outbreak_observations")
    op.drop_table("outbreak_observations")
    op.drop_index(op.f("ix_policy_flags_status"), table_name="policy_flags")
    op.drop_index(op.f("ix_policy_flags_country_iso3"), table_name="policy_flags")
    op.drop_table("policy_flags")
    op.drop_index(op.f("ix_outbreak_reports_run_id"), table_name="outbreak_reports")
    op.drop_index("ix_outbreak_reports_published_desc", table_name="outbreak_reports")
    op.drop_index(op.f("ix_outbreak_reports_pathogen_key"), table_name="outbreak_reports")
    op.drop_index(op.f("ix_outbreak_reports_extraction_status"), table_name="outbreak_reports")
    op.drop_index(op.f("ix_outbreak_reports_disease_label"), table_name="outbreak_reports")
    op.drop_table("outbreak_reports")
    op.drop_index(op.f("ix_country_flows_value_type"), table_name="country_flows")
    op.drop_index("ix_country_flows_dest", table_name="country_flows")
    op.drop_table("country_flows")
    op.drop_table("ingestion_runs")
    op.drop_index(op.f("ix_gravity_model_fits_is_active"), table_name="gravity_model_fits")
    op.drop_table("gravity_model_fits")
    op.drop_index("ix_dataset_versions_dataset_active", table_name="dataset_versions")
    op.drop_index(op.f("ix_dataset_versions_dataset"), table_name="dataset_versions")
    op.drop_table("dataset_versions")
    op.drop_index(op.f("ix_countries_iso2"), table_name="countries")
    op.drop_table("countries")

    bind = op.get_bind()
    for enum_type in _ENUM_TYPES:
        enum_type.drop(bind, checkfirst=True)
