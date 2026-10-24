from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from epiroute.core.clock import utc_now
from epiroute.core.config import Settings, get_settings
from epiroute.core.errors import DataUnavailableError
from epiroute.datasets.eurostat import load_observed_flows
from epiroute.datasets.gravity import GravityFit, build_feature_table, fit_gravity_model
from epiroute.datasets.naturalearth import load_country_geometries
from epiroute.datasets.openflights import (
    airport_route_degrees,
    country_centroids_from_airports,
    load_airports,
    load_country_topology,
)
from epiroute.datasets.population import load_population
from epiroute.datasets.registry import get_spec
from epiroute.schemas.common import ValueType

logger = logging.getLogger(__name__)

DEFAULT_POPULATION_YEAR = 2024

COUNTRIES_TABLE = "countries.parquet"
FLOWS_TABLE = "country_flows.parquet"
TOPOLOGY_TABLE = "airport_routes.parquet"
BOUNDARIES_FILE = "country_boundaries.geojson"
AIRPORTS_FILE = "airports.geojson"
GRAVITY_FILE = "gravity_fit.json"

MIN_MODELLED_PASSENGERS_PER_DAY = 0.05

# An airport with no scheduled route in OpenFlights cannot carry anyone in or
# out, so it is left out of the map file rather than drawn as a dot that means
# nothing.
MIN_AIRPORT_ROUTES = 1


@dataclass(frozen=True, slots=True)
class BuildResult:
    countries: int
    observed_flows: int
    modelled_flows: int
    topology_pairs: int
    gravity: GravityFit | None
    written: tuple[Path, ...]


def _write_era_flows(raw: Path, out: Path) -> None:
    """Observed-only passenger tables for the years a backtest is allowed to use."""
    from epiroute.datasets.eurostat import FLOW_YEARS, load_observed_flows, raw_filename

    for year in FLOW_YEARS:
        path = raw / raw_filename(year)
        if not path.exists():
            continue
        observed = load_observed_flows(path)
        rows = [
            {
                "origin_iso3": key[0],
                "dest_iso3": key[1],
                "passengers_per_day": flow.passengers_per_year / 365.0,
                "reference_period": str(year),
                "source": flow.source,
                "value_type": ValueType.OBSERVED.value,
            }
            for key, flow in observed.items()
        ]
        pd.DataFrame(rows).to_parquet(out / f"flows_{year}.parquet", index=False)


def _require(path: Path, dataset_key: str) -> Path:
    if not path.exists():
        spec = get_spec(dataset_key)
        msg = f"missing {spec.filename}; run `just data-fetch`"
        raise DataUnavailableError(dataset_key, msg)
    return path


def build_processed_tables(
    *,
    settings: Settings | None = None,
    population_year: int = DEFAULT_POPULATION_YEAR,
) -> BuildResult:
    settings = settings or get_settings()
    raw = settings.raw_data_dir
    out = settings.processed_data_dir
    out.mkdir(parents=True, exist_ok=True)

    population = load_population(
        _require(raw / get_spec("un_wpp_population").filename, "un_wpp_population"),
        year=population_year,
    )
    geometries = load_country_geometries(
        _require(raw / get_spec("natural_earth_countries").filename, "natural_earth_countries")
    )
    airports = load_airports(
        _require(raw / get_spec("openflights_airports").filename, "openflights_airports")
    )
    topology = load_country_topology(
        _require(raw / get_spec("openflights_routes").filename, "openflights_routes"), airports
    )

    geometry_by_iso3 = {g.iso3: g for g in geometries}
    airport_centroids = country_centroids_from_airports(airports)
    airport_counts: dict[str, int] = {}
    for airport in airports.values():
        airport_counts[airport.country_iso3] = airport_counts.get(airport.country_iso3, 0) + 1

    country_rows: list[dict[str, object]] = []
    for iso3, record in sorted(population.items()):
        geometry = geometry_by_iso3.get(iso3)
        centroid = (
            (geometry.centroid_lat, geometry.centroid_lon)
            if geometry
            else airport_centroids.get(iso3)
        )
        country_rows.append(
            {
                "iso3": iso3,
                "iso2": geometry.iso2 if geometry else None,
                "name": geometry.name if geometry else None,
                "official_name": geometry.official_name if geometry else None,
                "region": geometry.region if geometry else None,
                "subregion": geometry.subregion if geometry else None,
                "population": record.population,
                "population_year": record.year,
                "population_source": get_spec("un_wpp_population").name,
                "centroid_lat": centroid[0] if centroid else None,
                "centroid_lon": centroid[1] if centroid else None,
                "centroid_source": (
                    "natural_earth_polygon"
                    if geometry
                    else ("openflights_airport_mean" if centroid else None)
                ),
                "airport_count": airport_counts.get(iso3, 0),
                "has_boundary": geometry is not None,
            }
        )

    from epiroute.datasets.iso import country_name

    for row in country_rows:
        if not row["name"]:
            row["name"] = country_name(str(row["iso3"]))

    countries = pd.DataFrame(country_rows)
    countries_path = out / COUNTRIES_TABLE
    countries.to_parquet(countries_path, index=False)

    topology_rows = [
        {
            "origin_iso3": t.origin_iso3,
            "dest_iso3": t.dest_iso3,
            "route_count": t.route_count,
            "airline_count": t.airline_count,
            "airport_pair_count": t.airport_pair_count,
        }
        for t in topology.values()
    ]
    topology_df = pd.DataFrame(topology_rows)
    topology_path = out / TOPOLOGY_TABLE
    topology_df.to_parquet(topology_path, index=False)

    boundaries = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": g.iso3,
                "properties": {"iso3": g.iso3, "name": g.name},
                "geometry": g.geometry,
            }
            for g in geometries
        ],
    }
    boundaries_path = out / BOUNDARIES_FILE
    boundaries_path.write_text(json.dumps(boundaries, separators=(",", ":")), encoding="utf-8")

    degrees = airport_route_degrees(
        _require(raw / get_spec("openflights_routes").filename, "openflights_routes"), airports
    )
    # Busiest first, so a client that reads only the head of the file still
    # gets the airports that matter.
    ranked = sorted(
        (a for a in airports.values() if degrees.get(a.iata, 0) >= MIN_AIRPORT_ROUTES),
        key=lambda airport: -degrees[airport.iata],
    )
    airport_features = [
        {
            "type": "Feature",
            "properties": {
                "iata": airport.iata,
                "name": airport.name,
                "iso3": airport.country_iso3,
                "routes": degrees[airport.iata],
            },
            "geometry": {"type": "Point", "coordinates": [airport.longitude, airport.latitude]},
        }
        for airport in ranked
    ]
    airports_path = out / AIRPORTS_FILE
    airports_path.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": airport_features}, separators=(",", ":")
        ),
        encoding="utf-8",
    )

    populations = {iso3: record.population for iso3, record in population.items()}
    centroids: dict[str, tuple[float, float]] = {}
    for row in country_rows:
        lat, lon = row["centroid_lat"], row["centroid_lon"]
        if isinstance(lat, float) and isinstance(lon, float):
            centroids[str(row["iso3"])] = (lat, lon)
    topology_features = {
        (t.origin_iso3, t.dest_iso3): (t.route_count, t.airline_count) for t in topology.values()
    }

    eurostat_path = raw / get_spec("eurostat_avia_par").filename
    observed = load_observed_flows(eurostat_path) if eurostat_path.exists() else {}
    dot_path = raw / "dot_t100_2024.csv"
    if dot_path.exists() and observed:
        from epiroute.datasets.dot_t100 import (
            agreement_rate,
            direct_flows,
            undirected_country_totals,
        )

        dot_directed, dot_checks = direct_flows(
            undirected_country_totals(dot_path, airports), observed, year=2024
        )
        for key, flow in dot_directed.items():
            if key not in observed:
                observed[key] = flow
        (out / "dot_eurostat_crosscheck.json").write_text(
            json.dumps(
                {"agreement_rate": agreement_rate(dot_checks), "pairs": dot_checks},
                indent=2,
            ),
            encoding="utf-8",
        )
    _write_era_flows(raw, out)

    gravity: GravityFit | None = None
    flow_rows: list[dict[str, object]] = []

    if observed:
        observed_features = build_feature_table(
            list(observed), populations, centroids, topology_features
        )
        training = [
            (observed_features[key], flow.passengers_per_year / 365.0)
            for key, flow in observed.items()
            if key in observed_features and flow.passengers_per_year > 0
        ]
        gravity = fit_gravity_model(
            training,
            training_source=get_spec("eurostat_avia_par").name,
            training_period=str(next(iter(observed.values())).reference_year),
        )
        (out / GRAVITY_FILE).write_text(
            json.dumps(
                {
                    "fitted_at": utc_now().isoformat(),
                    "specification": gravity.specification,
                    "feature_names": list(gravity.feature_names),
                    "intercept": gravity.intercept,
                    "coefficients": gravity.coefficients,
                    "training_source": gravity.training_source,
                    "training_period": gravity.training_period,
                    "n_train": gravity.n_train,
                    "n_test": gravity.n_test,
                    "random_seed": gravity.random_seed,
                    "residual_sigma_log10": gravity.residual_sigma_log10,
                    "uncertainty_factor": gravity.uncertainty_factor,
                    "test_metrics": gravity.test_metrics.as_dict(),
                    "notes": gravity.notes,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        for key, flow in observed.items():
            flow_rows.append(
                {
                    "origin_iso3": key[0],
                    "dest_iso3": key[1],
                    "passengers_per_day": flow.passengers_per_year / 365.0,
                    "value_type": ValueType.OBSERVED.value,
                    "source": "eurostat_avia_par",
                    "reference_period": str(flow.reference_year),
                    "uncertainty_factor": None,
                    "direct_route_count": topology_features.get(key, (0, 0))[0],
                    "cross_check_source": flow.cross_check_source,
                    "cross_check_ratio": flow.cross_check_ratio,
                }
            )

    if gravity is not None:
        joinable = sorted(set(populations) & set(centroids))
        candidate_pairs = [
            (origin, dest)
            for origin in joinable
            for dest in joinable
            if origin != dest and (origin, dest) not in observed
        ]
        candidate_features = build_feature_table(
            candidate_pairs, populations, centroids, topology_features
        )
        for key, features in candidate_features.items():
            predicted = gravity.predict_passengers_per_day(features)
            if predicted < MIN_MODELLED_PASSENGERS_PER_DAY:
                continue
            has_routes = features.route_count > 0
            flow_rows.append(
                {
                    "origin_iso3": key[0],
                    "dest_iso3": key[1],
                    "passengers_per_day": predicted,
                    "value_type": ValueType.ESTIMATED.value,
                    "source": "gravity_model" if has_routes else "gravity_model_no_direct_route",
                    "reference_period": gravity.training_period,
                    "uncertainty_factor": gravity.uncertainty_factor_for(
                        has_direct_routes=has_routes
                    ),
                    "direct_route_count": features.route_count,
                    "cross_check_source": None,
                    "cross_check_ratio": None,
                }
            )

    flows_df = pd.DataFrame(flow_rows)
    flows_path = out / FLOWS_TABLE
    flows_df.to_parquet(flows_path, index=False)

    observed_count = (
        int((flows_df["value_type"] == ValueType.OBSERVED.value).sum()) if flow_rows else 0
    )
    modelled_count = (
        int((flows_df["value_type"] == ValueType.ESTIMATED.value).sum()) if flow_rows else 0
    )

    logger.info(
        "processed tables built",
        extra={
            "countries": len(countries),
            "observed_flows": observed_count,
            "modelled_flows": modelled_count,
            "topology_pairs": len(topology_df),
        },
    )
    return BuildResult(
        countries=len(countries),
        observed_flows=observed_count,
        modelled_flows=modelled_count,
        topology_pairs=len(topology_df),
        gravity=gravity,
        written=(countries_path, flows_path, topology_path, boundaries_path, airports_path),
    )
