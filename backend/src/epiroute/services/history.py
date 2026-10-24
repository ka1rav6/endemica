from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from epiroute.core.clock import utc_now
from epiroute.core.errors import NotFoundError
from epiroute.datasets.iso import country_name
from epiroute.repositories import outbreaks as repo
from epiroute.repositories import reference as reference_repo
from epiroute.schemas.outbreak import (
    CountryDiseaseOut,
    CountryProfileResponse,
    CountrySpreadOut,
    DiseaseHistoryOut,
    DiseaseSpreadResponse,
    DiseaseTimelineOut,
)

ACTIVE_WINDOW_DAYS = 180

_NOTE = (
    "Counts are cumulative as of each report's publication date and are summed "
    "across countries from each country's highest grounded figure. Reports whose "
    "numbers could not be grounded in the source text still contribute the country "
    "and the dates, never a count. Absence of a report is not evidence of absence "
    "of disease."
)


def _is_active(last_published_at: object) -> bool:
    if last_published_at is None:
        return False
    cutoff = utc_now() - timedelta(days=ACTIVE_WINDOW_DAYS)
    return bool(last_published_at >= cutoff)  # type: ignore[operator]


def list_disease_history(session: Session) -> list[DiseaseHistoryOut]:
    return [
        DiseaseHistoryOut(
            disease_key=record.disease_key,
            disease_name=record.disease_name,
            disease_family=record.disease_family,
            pathogen_key=record.pathogen_key,
            report_count=record.report_count,
            country_count=record.country_count,
            grounded_country_count=record.grounded_country_count,
            first_published_at=record.first_published_at,
            last_published_at=record.last_published_at,
            cases_confirmed=record.cases_confirmed,
            deaths=record.deaths,
            source_labels=list(record.source_labels),
        )
        for record in repo.list_disease_history(session)
    ]


def get_disease_spread(session: Session, disease_key: str) -> DiseaseSpreadResponse:
    history = {r.disease_key: r for r in repo.list_disease_history(session)}
    record = history.get(disease_key)
    if record is None:
        raise NotFoundError("disease", disease_key)

    spread = repo.country_spread_for_disease(session, disease_key)
    countries: list[CountrySpreadOut] = []
    for order, entry in enumerate(spread, start=1):
        country = reference_repo.get_country(session, entry.country_iso3)
        countries.append(
            CountrySpreadOut(
                country_iso3=entry.country_iso3,
                country_name=country.name if country else country_name(entry.country_iso3),
                centroid_lat=country.centroid_lat if country else None,
                centroid_lon=country.centroid_lon if country else None,
                report_count=entry.report_count,
                first_published_at=entry.first_published_at,
                last_published_at=entry.last_published_at,
                cases_confirmed=entry.cases_confirmed,
                deaths=entry.deaths,
                grounded=entry.grounded,
                report_url=entry.report_url,  # type: ignore[arg-type]
                report_title=entry.report_title,
                arrival_order=order,
            )
        )

    timeline = [
        DiseaseTimelineOut(
            year=point.year,
            report_count=point.report_count,
            country_count=point.country_count,
            new_country_count=point.new_country_count,
            cumulative_country_count=point.cumulative_country_count,
            new_countries=list(point.new_countries),
            cases_confirmed=point.cases_confirmed,
            deaths=point.deaths,
        )
        for point in repo.disease_timeline(session, disease_key)
    ]

    return DiseaseSpreadResponse(
        disease_key=record.disease_key,
        disease_name=record.disease_name,
        disease_family=record.disease_family,
        pathogen_key=record.pathogen_key,
        report_count=record.report_count,
        country_count=record.country_count,
        first_published_at=record.first_published_at,
        last_published_at=record.last_published_at,
        cases_confirmed=record.cases_confirmed,
        deaths=record.deaths,
        is_active=_is_active(record.last_published_at),
        countries=countries,
        timeline=timeline,
        note=_NOTE,
    )


def get_country_profile(session: Session, country_iso3: str) -> CountryProfileResponse:
    country = reference_repo.get_country(session, country_iso3)
    if country is None:
        raise NotFoundError("country", country_iso3)

    records = repo.diseases_for_country(session, country.iso3)
    diseases = [
        CountryDiseaseOut(
            disease_key=record.disease_key,
            disease_name=record.disease_name,
            disease_family=record.disease_family,
            pathogen_key=record.pathogen_key,
            report_count=record.report_count,
            first_published_at=record.first_published_at,
            last_published_at=record.last_published_at,
            cases_confirmed=record.cases_confirmed,
            deaths=record.deaths,
            grounded=record.grounded,
            is_active=_is_active(record.last_published_at),
            report_url=record.report_url,  # type: ignore[arg-type]
        )
        for record in records
    ]

    return CountryProfileResponse(
        iso3=country.iso3,
        name=country.name,
        region=country.region,
        subregion=country.subregion,
        population=country.population,
        centroid_lat=country.centroid_lat,
        centroid_lon=country.centroid_lon,
        inbound_flow_count=len(reference_repo.inbound_flows(session, country.iso3)),
        report_count=sum(d.report_count for d in diseases),
        active_disease_count=sum(1 for d in diseases if d.is_active),
        diseases=diseases,
    )
