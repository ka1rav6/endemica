"""A case count and a death toll are only summed when one report gave both."""

from __future__ import annotations

from datetime import UTC, datetime

from endemica.repositories.outbreaks import SeriesEndpoint, total_counts


def endpoint(
    iso3: str,
    *,
    confirmed: int | None = None,
    probable: int | None = None,
    suspected: int | None = None,
    deaths: int | None = None,
    year: int = 2024,
) -> SeriesEndpoint:
    return SeriesEndpoint(
        disease_key="cholera",
        country_iso3=iso3,
        cases_confirmed=confirmed,
        cases_probable=probable,
        cases_suspected=suspected,
        deaths=deaths,
        as_of=datetime(year, 6, 1, tzinfo=UTC),
        episode_report_count=1,
        source_name="WHO Disease Outbreak News",
        report_identifier=f"{year}-DON1-{iso3}",
        report_url="https://www.who.int/example",
    )


def test_a_country_reporting_deaths_without_cases_is_left_out_of_both_totals() -> None:
    # Summing its deaths into a total whose cases came from elsewhere is what
    # showed 26 of 56 diseases with more deaths than cases.
    totals = total_counts([endpoint("COD", confirmed=100, deaths=5), endpoint("KEN", deaths=40)])
    assert totals.cases_confirmed == 100
    assert totals.deaths == 5
    assert totals.counted_country_count == 1
    assert totals.unreconciled_country_count == 1


def test_a_toll_larger_than_every_case_figure_on_its_own_report_is_not_summed() -> None:
    totals = total_counts([endpoint("NGA", confirmed=10, suspected=20, deaths=500)])
    assert totals.cases_confirmed is None
    assert totals.deaths is None
    assert totals.unreconciled_country_count == 1


def test_suspected_cases_carry_the_toll_the_source_counted_over() -> None:
    # Cholera bulletins report suspected cases far more often than confirmed
    # ones, so the confirmed column alone cannot hold the death toll.
    totals = total_counts([endpoint("MOZ", suspected=4000, deaths=60)])
    assert totals.cases_reported == 4000
    assert totals.cases_confirmed is None
    assert totals.deaths == 60
    assert totals.counted_country_count == 1


def test_the_as_of_date_is_the_newest_contributing_report() -> None:
    totals = total_counts(
        [
            endpoint("COD", confirmed=10, deaths=1, year=2019),
            endpoint("KEN", confirmed=20, deaths=2, year=2024),
        ]
    )
    assert totals.as_of == datetime(2024, 6, 1, tzinfo=UTC)
    assert totals.cases_confirmed == 30
    assert totals.deaths == 3


def test_an_empty_set_of_endpoints_reports_no_total_rather_than_zero() -> None:
    totals = total_counts([])
    assert totals.cases_confirmed is None
    assert totals.cases_reported is None
    assert totals.deaths is None
