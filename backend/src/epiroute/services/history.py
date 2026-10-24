from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from epiroute.core.clock import utc_now
from epiroute.core.errors import NotFoundError
from epiroute.datasets.iso import country_name
from epiroute.repositories import outbreaks as repo
from epiroute.repositories import reference as reference_repo
from epiroute.schemas.outbreak import (
    ActiveCountryOut,
    ActiveDiseaseOut,
    ActiveSummaryResponse,
    CountryDiseaseOut,
    CountryProfileResponse,
    CountrySpreadOut,
    DiseaseHistoryOut,
    DiseaseSpreadResponse,
    DiseaseTimelineOut,
)
from epiroute.services.risk import PRESENCE_LOOKBACK_DAYS

# One definition of "active" everywhere: the same window the importation model
# treats as current, so the disease list, the map and the probabilities never
# disagree about which outbreaks are in scope.
ACTIVE_WINDOW_DAYS = PRESENCE_LOOKBACK_DAYS

_NOTE = (
    "A country's figures are the last report of its most recent episode: both "
    "numbers come from the same bulletin, so they describe the same outbreak on "
    "the same date. Countries are then summed. A country whose death toll "
    "exceeded every case figure on its own report is left out of the totals and "
    "counted separately, because the two were measured over different areas. "
    "Reports whose numbers could not be grounded in the source text still "
    "contribute the country and the dates, never a count. Absence of a report is "
    "not evidence of absence of disease."
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
            cases_reported=record.cases_reported,
            deaths=record.deaths,
            counts_as_of=record.counts_as_of,
            counted_country_count=record.counted_country_count,
            unreconciled_country_count=record.unreconciled_country_count,
            source_labels=list(record.source_labels),
        )
        for record in repo.list_disease_history(session)
    ]


# A source can keep naming a disease long after it stops publishing figures
# for it. WHO Disease Outbreak News is the clearest case: it carried COVID-19
# case counts only into January 2020 and then moved them to a dedicated
# dashboard, so the honest reading of 82 cases is "what this source last said",
# not "how large the outbreak got". A year is long enough that no ordinary
# reporting lag explains the gap.
_STALE_COUNT_DAYS = 365


def _coverage_note(record: repo.DiseaseHistoryRecord) -> str | None:
    if record.counts_as_of is None or record.last_published_at is None:
        return None
    if (record.last_published_at - record.counts_as_of).days < _STALE_COUNT_DAYS:
        return None
    return (
        f"The newest counts here are from {record.counts_as_of.date().isoformat()}, "
        "while this source went on naming the disease until "
        f"{record.last_published_at.date().isoformat()}. It stopped publishing "
        "figures, so these totals describe that date and not the outbreak since."
    )


def get_disease_spread(session: Session, disease_key: str) -> DiseaseSpreadResponse:
    # Built once and handed to both: the history row and the per-country
    # spread are two readings of the same paired endpoints.
    endpoints = repo.series_endpoints(session, disease_key=disease_key)
    history = {
        r.disease_key: r
        for r in repo.list_disease_history(session, disease_key=disease_key, endpoints=endpoints)
    }
    record = history.get(disease_key)
    if record is None:
        raise NotFoundError("disease", disease_key)

    spread = repo.country_spread_for_disease(session, disease_key, endpoints=endpoints)
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
                cases_reported=entry.cases_reported,
                deaths=entry.deaths,
                counts_as_of=entry.counts_as_of,
                counts_reconciled=entry.counts_reconciled,
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
        coverage_note=_coverage_note(record),
        cases_reported=record.cases_reported,
        counts_as_of=record.counts_as_of,
        counted_country_count=record.counted_country_count,
        unreconciled_country_count=record.unreconciled_country_count,
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
            cases_reported=record.cases_reported,
            deaths=record.deaths,
            counts_as_of=record.counts_as_of,
            counts_reconciled=record.counts_reconciled,
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


ACTIVE_RISK_WINDOW_DAYS = ACTIVE_WINDOW_DAYS

_ACTIVE_NOTE = (
    f"Active means a grounded report published in the last {ACTIVE_WINDOW_DAYS} days, "
    "the same window the importation model uses. A country's case figure is where "
    f"the last {ACTIVE_WINDOW_DAYS} days of bulletins left each active disease, "
    "summed over diseases, so it combines separate outbreaks rather than "
    "re-counting one."
)


def get_active_summary(session: Session) -> ActiveSummaryResponse:
    since = utc_now() - timedelta(days=ACTIVE_RISK_WINDOW_DAYS)
    diseases = repo.active_diseases(session, since=since)
    countries = repo.active_countries(session, since=since)

    country_rows: list[ActiveCountryOut] = []
    for record in countries:
        country = reference_repo.get_country(session, record.country_iso3)
        country_rows.append(
            ActiveCountryOut(
                country_iso3=record.country_iso3,
                country_name=country.name if country else country_name(record.country_iso3),
                centroid_lat=country.centroid_lat if country else None,
                centroid_lon=country.centroid_lon if country else None,
                disease_count=record.disease_count,
                report_count=record.report_count,
                cases_confirmed=record.cases_confirmed,
                cases_reported=record.cases_reported,
                deaths=record.deaths,
                last_published_at=record.last_published_at,
                disease_keys=[key for key, _ in record.diseases],
                disease_names=[name for _, name in record.diseases],
            )
        )

    return ActiveSummaryResponse(
        window_days=ACTIVE_RISK_WINDOW_DAYS,
        since=since,
        disease_count=len(diseases),
        country_count=len(country_rows),
        report_count=sum(disease.report_count for disease in diseases),
        cases_confirmed=sum(row.cases_confirmed or 0 for row in country_rows) or None,
        deaths=sum(row.deaths or 0 for row in country_rows) or None,
        diseases=[
            ActiveDiseaseOut(
                disease_key=disease.disease_key,
                disease_name=disease.disease_name,
                pathogen_key=disease.pathogen_key,
                country_count=disease.country_count,
                report_count=disease.report_count,
                last_published_at=disease.last_published_at,
            )
            for disease in diseases
        ],
        countries=country_rows,
        note=_ACTIVE_NOTE,
    )
