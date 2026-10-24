from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from epiroute.core.config import Settings, get_settings
from epiroute.datasets.build import COUNTRIES_TABLE, FLOWS_TABLE, TOPOLOGY_TABLE
from epiroute.datasets.iso import is_known_iso3
from epiroute.schemas.common import ValueType


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)


def _check(name: str, condition: bool, detail: str) -> Check:
    return Check(name=name, passed=condition, detail=detail)


def validate_processed_tables(*, settings: Settings | None = None) -> ValidationReport:
    settings = settings or get_settings()
    processed = settings.processed_data_dir
    checks: list[Check] = []

    countries_path = processed / COUNTRIES_TABLE
    flows_path = processed / FLOWS_TABLE
    topology_path = processed / TOPOLOGY_TABLE

    for label, path in (
        ("countries table present", countries_path),
        ("flows table present", flows_path),
        ("topology table present", topology_path),
    ):
        checks.append(_check(label, path.exists(), str(path.name)))

    if not countries_path.exists():
        return ValidationReport(checks=tuple(checks))

    countries = pd.read_parquet(countries_path)
    checks.append(
        _check("countries: iso3 unique", countries["iso3"].is_unique, f"{len(countries)} rows")
    )
    bad_iso = [c for c in countries["iso3"] if not is_known_iso3(str(c))]
    checks.append(
        _check("countries: every iso3 recognised", not bad_iso, f"unrecognised: {bad_iso[:5]}")
    )
    checks.append(
        _check(
            "countries: population positive",
            bool((countries["population"].dropna() > 0).all()),
            f"{int(countries['population'].notna().sum())} with population",
        )
    )
    with_centroid = int(countries["centroid_lat"].notna().sum())
    checks.append(
        _check(
            "countries: centroids present for most",
            with_centroid >= 0.9 * len(countries),
            f"{with_centroid}/{len(countries)}",
        )
    )
    lat_ok = countries["centroid_lat"].dropna().between(-90, 90).all()
    lon_ok = countries["centroid_lon"].dropna().between(-180, 180).all()
    checks.append(
        _check("countries: centroids in range", bool(lat_ok and lon_ok), "lat/lon bounds")
    )

    if not flows_path.exists():
        return ValidationReport(checks=tuple(checks))

    flows = pd.read_parquet(flows_path)
    known = set(countries["iso3"])
    checks.append(
        _check(
            "flows: no self pairs",
            bool((flows["origin_iso3"] != flows["dest_iso3"]).all()),
            f"{len(flows)} rows",
        )
    )
    checks.append(
        _check(
            "flows: directed pairs unique",
            not flows.duplicated(subset=["origin_iso3", "dest_iso3"]).any(),
            "no duplicate (origin, dest)",
        )
    )
    unknown = sorted((set(flows["origin_iso3"]) | set(flows["dest_iso3"])) - known)
    checks.append(
        _check("flows: endpoints are known countries", not unknown, f"unknown: {unknown[:5]}")
    )
    checks.append(
        _check(
            "flows: passengers non-negative",
            bool((flows["passengers_per_day"] >= 0).all()),
            f"max {flows['passengers_per_day'].max():,.0f}/day",
        )
    )
    checks.append(
        _check(
            "flows: value_type is observed or estimated",
            set(flows["value_type"]) <= {ValueType.OBSERVED.value, ValueType.ESTIMATED.value},
            f"types: {sorted(set(flows['value_type']))}",
        )
    )
    observed = flows[flows["value_type"] == ValueType.OBSERVED.value]
    estimated = flows[flows["value_type"] == ValueType.ESTIMATED.value]
    checks.append(
        _check(
            "flows: observed rows carry no uncertainty factor",
            bool(observed["uncertainty_factor"].isna().all()),
            f"{len(observed)} observed rows",
        )
    )
    checks.append(
        _check(
            "flows: estimated rows carry an uncertainty factor >= 1",
            bool(
                estimated.empty
                or (
                    estimated["uncertainty_factor"].notna() & (estimated["uncertainty_factor"] >= 1)
                ).all()
            ),
            f"{len(estimated)} estimated rows",
        )
    )
    checks.append(
        _check(
            "flows: observed and estimated do not overlap",
            not observed.merge(estimated, on=["origin_iso3", "dest_iso3"]).shape[0],
            "no pair appears as both",
        )
    )

    if topology_path.exists():
        topology = pd.read_parquet(topology_path)
        checks.append(
            _check(
                "topology: route counts positive",
                bool((topology["route_count"] > 0).all()),
                f"{len(topology)} pairs",
            )
        )
        merged = flows.merge(
            topology, on=["origin_iso3", "dest_iso3"], how="inner", suffixes=("", "_topo")
        )
        mismatch = (merged["direct_route_count"] != merged["route_count"]).sum()
        checks.append(
            _check(
                "flows: route counts agree with topology",
                mismatch == 0,
                f"{mismatch} mismatched of {len(merged)}",
            )
        )

    return ValidationReport(checks=tuple(checks))


def processed_table_paths(settings: Settings | None = None) -> dict[str, Path]:
    settings = settings or get_settings()
    return {
        "countries": settings.processed_data_dir / COUNTRIES_TABLE,
        "flows": settings.processed_data_dir / FLOWS_TABLE,
        "topology": settings.processed_data_dir / TOPOLOGY_TABLE,
    }
