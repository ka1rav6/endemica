from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from epiroute.datasets.iso import resolve

_AIRPORT_COLUMNS = (
    "airport_id",
    "name",
    "city",
    "country",
    "iata",
    "icao",
    "latitude",
    "longitude",
    "altitude",
    "timezone",
    "dst",
    "tz_database",
    "type",
    "source",
)
_ROUTE_COLUMNS = (
    "airline",
    "airline_id",
    "source_airport",
    "source_airport_id",
    "destination_airport",
    "destination_airport_id",
    "codeshare",
    "stops",
    "equipment",
)

_NULL = r"\N"


@dataclass(frozen=True, slots=True)
class Airport:
    iata: str
    icao: str | None
    name: str
    country_iso3: str
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class CountryPairTopology:
    origin_iso3: str
    dest_iso3: str
    route_count: int
    airline_count: int
    airport_pair_count: int


def load_airports(path: Path) -> dict[str, Airport]:
    airports: dict[str, Airport] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, fieldnames=list(_AIRPORT_COLUMNS)):
            iata = (row["iata"] or "").strip()
            if len(iata) != 3 or iata == _NULL:
                continue
            iso3 = resolve(row["country"])
            if iso3 is None:
                continue
            try:
                lat = float(row["latitude"])
                lon = float(row["longitude"])
            except (TypeError, ValueError):
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            icao = (row["icao"] or "").strip()
            airports[iata] = Airport(
                iata=iata,
                icao=None if icao in ("", _NULL) else icao,
                name=(row["name"] or "").strip(),
                country_iso3=iso3,
                latitude=lat,
                longitude=lon,
            )
    return airports


def load_country_topology(
    routes_path: Path, airports: dict[str, Airport]
) -> dict[tuple[str, str], CountryPairTopology]:
    airlines: dict[tuple[str, str], set[str]] = defaultdict(set)
    pairs: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    counts: dict[tuple[str, str], int] = defaultdict(int)

    with routes_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, fieldnames=list(_ROUTE_COLUMNS)):
            source = (row["source_airport"] or "").strip()
            dest = (row["destination_airport"] or "").strip()
            if source not in airports or dest not in airports:
                continue
            if (row["stops"] or "0").strip() not in ("0", ""):
                continue
            origin_iso3 = airports[source].country_iso3
            dest_iso3 = airports[dest].country_iso3
            if origin_iso3 == dest_iso3:
                continue
            key = (origin_iso3, dest_iso3)
            counts[key] += 1
            airline = (row["airline"] or "").strip()
            if airline and airline != _NULL:
                airlines[key].add(airline)
            pairs[key].add((source, dest))

    return {
        key: CountryPairTopology(
            origin_iso3=key[0],
            dest_iso3=key[1],
            route_count=count,
            airline_count=len(airlines[key]),
            airport_pair_count=len(pairs[key]),
        )
        for key, count in counts.items()
    }


def airport_route_degrees(routes_path: Path, airports: dict[str, Airport]) -> dict[str, int]:
    """Scheduled non-stop routes touching each airport, by IATA code.

    Degree stands in for how prominent an airport is. OpenFlights has no seat
    counts, so the number of distinct routes an airport appears on - in either
    direction, domestic included - is the honest proxy the source supports.
    """
    degrees: dict[str, int] = defaultdict(int)
    seen: set[tuple[str, str, str]] = set()
    with routes_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, fieldnames=list(_ROUTE_COLUMNS)):
            source = (row["source_airport"] or "").strip()
            dest = (row["destination_airport"] or "").strip()
            if source not in airports or dest not in airports:
                continue
            if (row["stops"] or "0").strip() not in ("0", ""):
                continue
            airline = (row["airline"] or "").strip()
            key = (airline, source, dest)
            if key in seen:
                continue
            seen.add(key)
            degrees[source] += 1
            degrees[dest] += 1
    return dict(degrees)


def country_centroids_from_airports(
    airports: dict[str, Airport],
) -> dict[str, tuple[float, float]]:
    sums: dict[str, tuple[float, float, int]] = {}
    for airport in airports.values():
        lat, lon, n = sums.get(airport.country_iso3, (0.0, 0.0, 0))
        sums[airport.country_iso3] = (lat + airport.latitude, lon + airport.longitude, n + 1)
    return {iso3: (lat / n, lon / n) for iso3, (lat, lon, n) in sums.items() if n}
