from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from epiroute.core.errors import NotFoundError
from epiroute.datasets.iso import country_name
from epiroute.datasets.registry import DATASETS
from epiroute.db.models import OutbreakObservation, OutbreakReport
from epiroute.repositories import outbreaks as repo
from epiroute.repositories import reference as reference_repo
from epiroute.schemas.common import ExtractionStatus, Provenance
from epiroute.schemas.outbreak import (
    CountryListResponse,
    CountryOut,
    DiseaseOut,
    GravityModelOut,
    GroundingFieldOut,
    IngestionRunOut,
    ObservationOut,
    OutbreakListResponse,
    OutbreakReportDetail,
    OutbreakReportOut,
    RouteListResponse,
    RouteOut,
    SourceListResponse,
    SourceOut,
)


def _usable_for_models(observation: OutbreakObservation) -> bool:
    """Whether this row's stored counts may enter a risk calculation.

    Matches the repository filter: verified and partial rows whose failing
    fields were already dropped, and never an unverified row.
    """
    if observation.grounding_status not in (ExtractionStatus.VERIFIED, ExtractionStatus.PARTIAL):
        return False
    return any(
        value is not None
        for value in (
            observation.cases_confirmed,
            observation.cases_probable,
            observation.cases_suspected,
            observation.deaths,
        )
    )


def _observation_out(observation: OutbreakObservation) -> ObservationOut:
    return ObservationOut(
        id=str(observation.id),
        country_iso3=observation.country_iso3,
        country_name=country_name(observation.country_iso3),
        country_name_as_reported=observation.country_name_as_reported,
        subnational_name=observation.subnational_name,
        cases_confirmed=observation.cases_confirmed,
        cases_probable=observation.cases_probable,
        cases_suspected=observation.cases_suspected,
        deaths=observation.deaths,
        period_start=observation.period_start,
        period_end=observation.period_end,
        period_text=observation.period_text,
        evidence_text=observation.evidence_text,
        grounding_status=observation.grounding_status,
        value_type=observation.value_type,
        usable_for_models=_usable_for_models(observation),
    )


def _provenance(report: OutbreakReport) -> Provenance:
    return Provenance(
        source_name=report.source_name,
        source_url=report.source_url,  # type: ignore[arg-type]
        source_identifier=report.source_identifier,
        published_at=report.published_at,
        retrieved_at=report.retrieved_at,
        extraction_method=report.extraction_method,
        extraction_status=report.extraction_status,
        extraction_run_id=str(report.run_id) if report.run_id else None,
        license_note=report.license_note,
    )


def _report_out(report: OutbreakReport) -> OutbreakReportOut:
    observations = [_observation_out(o) for o in report.observations]
    return OutbreakReportOut(
        id=str(report.id),
        title=report.title,
        disease_label=report.disease_label,
        pathogen_key=report.pathogen_key,
        summary_text=report.summary_text,
        provenance=_provenance(report),
        extraction_method=report.extraction_method,
        extraction_status=report.extraction_status,
        countries=sorted({o.country_iso3 for o in observations}),
        observations=observations,
        warning_count=len(report.validation_warnings or []),
    )


def list_outbreaks(
    session: Session,
    *,
    pathogen_key: str | None = None,
    country_iso3: str | None = None,
    since: datetime | None = None,
    status: ExtractionStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> OutbreakListResponse:
    reports = repo.list_reports(
        session,
        pathogen_key=pathogen_key,
        country_iso3=country_iso3,
        since=since,
        status=status,
        limit=limit,
        offset=offset,
    )
    total = repo.count_reports(
        session,
        pathogen_key=pathogen_key,
        country_iso3=country_iso3,
        since=since,
        status=status,
    )
    return OutbreakListResponse(
        total=total, limit=limit, offset=offset, items=[_report_out(r) for r in reports]
    )


def get_outbreak(session: Session, report_id: str) -> OutbreakReportDetail:
    report = repo.get_report(session, report_id)
    if report is None:
        raise NotFoundError("outbreak report", report_id)

    grounding: list[GroundingFieldOut] = []
    for observation in report.observations:
        detail = observation.grounding_detail or {}
        fields = detail.get("fields")
        if not isinstance(fields, list):
            continue
        for entry in fields:
            if not isinstance(entry, dict):
                continue
            grounding.append(
                GroundingFieldOut(
                    field=str(entry.get("field", "")),
                    value=int(entry.get("value", 0)),
                    verdict=str(entry.get("verdict", "")),
                    detail=str(entry.get("detail", "")),
                    context=entry.get("context"),
                )
            )

    base = _report_out(report)
    return OutbreakReportDetail(
        **base.model_dump(),
        narrative_text=report.narrative_text,
        validation_warnings=list(report.validation_warnings or []),
        grounding_fields=grounding,
    )


def list_countries(session: Session) -> CountryListResponse:
    countries = reference_repo.list_countries(session)
    with_outbreaks = set(repo.countries_with_active_outbreaks(session))
    diseases = repo.diseases_by_country(session)
    items = [
        CountryOut(
            iso3=c.iso3,
            iso2=c.iso2,
            name=c.name,
            region=c.region,
            subregion=c.subregion,
            population=c.population,
            population_year=c.population_year,
            centroid_lat=c.centroid_lat,
            centroid_lon=c.centroid_lon,
            has_reported_outbreak=c.iso3 in with_outbreaks,
            diseases=diseases.get(c.iso3, []),
        )
        for c in countries
    ]
    return CountryListResponse(total=len(items), items=items)


def list_diseases(session: Session) -> list[DiseaseOut]:
    return [
        DiseaseOut(
            disease_label=record.disease_label,
            pathogen_key=record.pathogen_key,
            country_count=record.country_count,
            report_count=record.report_count,
            latest_published_at=record.latest_published_at,
        )
        for record in repo.list_diseases(session)
    ]


def list_routes(
    session: Session,
    *,
    origin_iso3: str | None = None,
    dest_iso3: str | None = None,
    limit: int = 50,
) -> RouteListResponse:
    if origin_iso3:
        rows = reference_repo.outbound_flows(session, origin_iso3)
    elif dest_iso3:
        rows = reference_repo.inbound_flows(session, dest_iso3)
    else:
        rows = reference_repo.all_flows(session)

    rows.sort(key=lambda r: r.passengers_per_day, reverse=True)
    total = len(rows)
    rows = rows[:limit]

    needed = {r.origin_iso3 for r in rows} | {r.dest_iso3 for r in rows}
    coordinates = {iso3: reference_repo.get_country(session, iso3) for iso3 in needed}

    items: list[RouteOut] = []
    for row in rows:
        origin = coordinates.get(row.origin_iso3)
        dest = coordinates.get(row.dest_iso3)
        items.append(
            RouteOut(
                origin_iso3=row.origin_iso3,
                origin_name=origin.name if origin else country_name(row.origin_iso3),
                dest_iso3=row.dest_iso3,
                dest_name=dest.name if dest else country_name(row.dest_iso3),
                passengers_per_day=row.passengers_per_day,
                value_type=row.value_type,
                source=row.source,
                reference_period=row.reference_period,
                uncertainty_factor=row.uncertainty_factor,
                direct_route_count=row.direct_route_count,
                origin_lat=origin.centroid_lat if origin else None,
                origin_lon=origin.centroid_lon if origin else None,
                dest_lat=dest.centroid_lat if dest else None,
                dest_lon=dest.centroid_lon if dest else None,
            )
        )
    return RouteListResponse(total=total, items=items)


def list_sources(session: Session) -> SourceListResponse:
    versions = {v.dataset: v for v in reference_repo.active_dataset_versions(session)}
    items: list[SourceOut] = []
    for key, spec in DATASETS.items():
        version = versions.get(key)
        items.append(
            SourceOut(
                key=key,
                name=spec.name,
                kind=spec.kind.value,
                url=spec.url,  # type: ignore[arg-type]
                coverage=spec.coverage,
                licence=spec.licence,
                limitations=list(spec.limitations),
                fields_used=list(spec.fields_used),
                retrieved_at=version.retrieved_at if version else None,
                record_count=version.record_count if version else None,
                notes=spec.notes or None,
            )
        )
    return SourceListResponse(items=items)


def get_gravity_model(session: Session) -> GravityModelOut:
    fit = reference_repo.active_gravity_fit(session)
    if fit is None:
        raise NotFoundError("gravity model fit", "active")
    sigma = fit.residual_sigma_log10
    return GravityModelOut(
        fitted_at=fit.fitted_at,
        specification=fit.specification,
        training_source=fit.training_source,
        training_period=fit.training_period,
        n_train=fit.n_train,
        n_test=fit.n_test,
        random_seed=fit.random_seed,
        intercept=fit.intercept,
        coefficients=fit.coefficients,
        metrics=fit.metrics,
        residual_sigma_log10=sigma,
        uncertainty_factor=min(10.0 ** (2.0 * sigma), 100.0),
        notes=fit.notes,
        caveat=(
            "These are held-out metrics for predicting passenger volume on country pairs "
            "the training agencies do not observe. They say nothing about how well EpiRoute "
            "predicts outbreaks; no epidemiological validation has been performed."
        ),
    )


def list_runs(session: Session, *, limit: int = 20) -> list[IngestionRunOut]:
    return [
        IngestionRunOut(
            id=str(run.id),
            source=run.source,
            mode=run.mode,
            trigger=run.trigger,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            records_seen=run.records_seen,
            records_created=run.records_created,
            records_updated=run.records_updated,
            records_skipped=run.records_skipped,
            observations_created=run.observations_created,
            observations_unverified=run.observations_unverified,
            error_code=run.error_code,
            error_message=run.error_message,
            detail=run.detail,
        )
        for run in repo.list_runs(session, limit=limit)
    ]
