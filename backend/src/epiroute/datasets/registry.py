"""The authoritative list of external datasets EpiRoute uses.

Every entry records what AGENTS.md section 5.1 requires of
``docs/data-sources.md``: the official URL, what fields are consumed, the
coverage, the licence and the known limitations. Keeping it as data rather than
prose means `just data-check` can report on exactly the sources the code
actually reads.

**Not included, and why.** US BTS T-100 International Market would materially
improve passenger coverage, but it is only obtainable through an interactive
query form on transtats.bts.gov that produces a per-request download; there is
no stable bulk URL. The loader in :mod:`epiroute.datasets.bts` therefore reads
a manually downloaded CSV and is documented as an optional enrichment. See
docs/data-sources.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class DatasetKind(StrEnum):
    """What role a dataset plays."""

    GEOGRAPHY = "geography"
    POPULATION = "population"
    AIR_TOPOLOGY = "air_topology"
    AIR_PASSENGERS = "air_passengers"
    OUTBREAK_REPORTS = "outbreak_reports"


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """Metadata and acquisition details for one external dataset.

    Attributes:
        key: Stable identifier, also the ``dataset`` column in
            ``dataset_versions``.
        name: Human-readable source name.
        kind: Role the dataset plays in EpiRoute.
        url: Direct download URL, or ``None`` when acquisition is manual or
            parameterised per request (Eurostat is queried per country).
        filename: Target file name inside ``data/raw``.
        fields_used: The fields EpiRoute actually reads.
        coverage: Geographic and temporal coverage, as documented by the
            publisher.
        licence: Licence or reuse terms, with "verify" where the publisher's
            statement has not been confirmed by this project.
        limitations: Known biases and gaps that affect interpretation.
        required: Whether the application's core features need it.
        notes: Anything else an operator should know.
    """

    key: str
    name: str
    kind: DatasetKind
    url: str | None
    filename: str
    fields_used: tuple[str, ...]
    coverage: str
    licence: str
    limitations: tuple[str, ...]
    required: bool = True
    notes: str = ""


_SPECS: Final[tuple[DatasetSpec, ...]] = (
    DatasetSpec(
        key="natural_earth_countries",
        name="Natural Earth 1:110m Admin 0 Countries",
        kind=DatasetKind.GEOGRAPHY,
        url=(
            "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
            "master/geojson/ne_110m_admin_0_countries.geojson"
        ),
        filename="ne_110m_admin_0_countries.geojson",
        fields_used=(
            "ISO_A3",
            "ISO_A2",
            "ADMIN",
            "NAME_LONG",
            "CONTINENT",
            "SUBREGION",
            "geometry",
        ),
        coverage="Global, 1:110m resolution. Static reference boundaries.",
        licence="Public domain (Natural Earth terms of use).",
        limitations=(
            "Disputed borders are simplified and some territories carry the "
            "placeholder ISO code '-99', which EpiRoute resolves by name.",
            "1:110m geometry is for display at world scale, not for any "
            "area or adjacency calculation.",
            "Centroids derived from this file are geometric, not population-weighted.",
        ),
    ),
    DatasetSpec(
        key="un_wpp_population",
        name="UN World Population Prospects 2024, total population by sex",
        kind=DatasetKind.POPULATION,
        url=(
            "https://population.un.org/wpp/assets/Excel%20Files/"
            "1_Indicator%20(Standard)/CSV_FILES/WPP2024_TotalPopulationBySex.csv.gz"
        ),
        filename="WPP2024_TotalPopulationBySex.csv.gz",
        fields_used=("ISO3_code", "Time", "Variant", "LocTypeName", "PopTotal"),
        coverage="Global, by country and area, 1950-2100. EpiRoute reads the medium variant.",
        licence="UN data terms; CC BY 3.0 IGO for WPP outputs (verify before redistribution).",
        limitations=(
            "Values are estimates and projections, not a census. PopTotal is "
            "in thousands and is converted to persons on load.",
            "Provides the denominator N only; it says nothing about where "
            "within a country people are.",
        ),
    ),
    DatasetSpec(
        key="openflights_airports",
        name="OpenFlights airport database",
        kind=DatasetKind.AIR_TOPOLOGY,
        url="https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat",
        filename="openflights_airports.dat",
        fields_used=("iata", "icao", "country", "latitude", "longitude"),
        coverage="Global airport list. Community-maintained; route data is roughly 2014 vintage.",
        licence="Open Database License (ODbL) 1.0.",
        limitations=(
            "Country names are free text and must be normalised to ISO-3.",
            "Contains closed and non-commercial airports.",
        ),
    ),
    DatasetSpec(
        key="openflights_routes",
        name="OpenFlights route database",
        kind=DatasetKind.AIR_TOPOLOGY,
        url="https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat",
        filename="openflights_routes.dat",
        fields_used=("airline", "source_airport", "destination_airport", "stops", "equipment"),
        coverage="Scheduled airline routes as of roughly 2014.",
        licence="Open Database License (ODbL) 1.0.",
        limitations=(
            "A route is a scheduled connection, NOT a passenger count. "
            "EpiRoute uses it only as a connectivity feature and never writes "
            "a route count into a passenger field.",
            "The data is around a decade old, so some routes no longer "
            "operate and newer ones are absent.",
            "No frequency or seat information, so seats cannot be derived "
            "without an aircraft-configuration assumption.",
        ),
    ),
    DatasetSpec(
        key="eurostat_avia_par",
        name="Eurostat air passenger transport between reporting-country airport pairs",
        kind=DatasetKind.AIR_PASSENGERS,
        # Queried per reporting country as avia_par_<cc>; see
        # epiroute.datasets.eurostat for the URL template and country list.
        url=None,
        filename="eurostat_avia_par.json.gz",
        fields_used=("airp_pr", "tra_meas", "time", "value"),
        coverage=(
            "34 reporting countries (EU, EFTA, UK, Western Balkans, Turkiye) "
            "paired with airports worldwide. Annual. The live table is 2024; "
            "2019 and 2022 are kept for outbreak-era training."
        ),
        licence="Eurostat reuse policy: free reuse with source acknowledgement.",
        limitations=(
            "OBSERVED passenger counts, but only for routes with at least one "
            "endpoint in a reporting country. Flows between two non-reporting "
            "countries are absent entirely and are supplied by the gravity model.",
            "Counts passengers on board per airport pair, so a connecting "
            "itinerary is counted on each leg rather than origin-to-final-"
            "destination.",
            "Airport-pair rows are aggregated to country pairs by EpiRoute, "
            "which loses within-country structure.",
        ),
        notes=(
            "2024 is the live reference year. 2019 and 2022 are downloaded "
            "beside it so a backtest can use flows from the outbreak's era."
        ),
    ),
    DatasetSpec(
        key="who_don",
        name="WHO Disease Outbreak News API",
        kind=DatasetKind.OUTBREAK_REPORTS,
        url="https://www.who.int/api/news/diseaseoutbreaknews",
        filename="who_don_archive.json",
        fields_used=(
            "DonId",
            "UrlName",
            "Title",
            "PublicationDate",
            "PublicationDateAndTime",
            "Summary",
            "Overview",
            "Epidemiology",
            "Assessment",
        ),
        coverage="Global outbreak bulletins, 1996 to present. Live.",
        licence="WHO terms of use; attribution required, commercial reuse restricted.",
        limitations=(
            "Case counts sit inside narrative HTML rather than the structured "
            "Epidemiology field. Measured on 24 Oct 2026 over 250 items sampled "
            "across the archive: Epidemiology was empty for 91%, while Overview "
            "was present for 100%. The five most recent items are an exception "
            "(1 of 5 empty), so recency alone cannot be relied on.",
            "Counts are cumulative as of the report date, not current "
            "prevalence, and are subject to reporting lag and revision.",
            "Default ordering is not by date; EpiRoute requests "
            "$orderby=PublicationDateAndTime desc explicitly.",
        ),
        notes=(
            "OData $orderby, $top, $select and $count were verified against "
            "the live endpoint on 24 Oct 2026 and all work."
        ),
    ),
    DatasetSpec(
        key="dot_t100",
        name="US DOT International Report Passengers",
        kind=DatasetKind.AIR_PASSENGERS,
        url=None,
        filename="dot_t100_2024.csv",
        fields_used=("usg_apt", "fg_apt", "total"),
        coverage="Flights touching the United States, monthly. EpiRoute reads calendar 2024.",
        licence="US government work, public domain.",
        limitations=(
            "Rows have no direction column, so a pair is split using Eurostat's share "
            "or in half when Eurostat has no figure.",
            "Airport-to-country mapping uses OpenFlights, which is about a decade old.",
        ),
        required=False,
        notes="Fetched by data-fetch from data.transportation.gov dataset xgub-n9bw.",
    ),
    DatasetSpec(
        key="worldbank_population",
        name="World Bank total population SP.POP.TOTL",
        kind=DatasetKind.POPULATION,
        url=None,
        filename="worldbank_population_2024.json",
        fields_used=("countryiso3code", "value"),
        coverage="Global, annual. Used as a check on UN WPP, not as the denominator.",
        licence="CC BY 4.0.",
        limitations=("A gap above 5 percent is flagged. The UN figure remains the denominator.",),
        required=False,
    ),
)

DATASETS: Final[MappingProxyType[str, DatasetSpec]] = MappingProxyType({s.key: s for s in _SPECS})
"""Read-only registry of dataset specifications, keyed by :attr:`DatasetSpec.key`."""

DOWNLOADABLE: Final[tuple[DatasetSpec, ...]] = tuple(s for s in _SPECS if s.url is not None)
"""Datasets with a stable direct download URL, fetched by ``just data-fetch``."""


def get_spec(key: str) -> DatasetSpec:
    """Return the specification for ``key``.

    Raises:
        KeyError: If no dataset is registered under that key.
    """
    return DATASETS[key]
