from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass
from pathlib import Path

WPP_VARIANT = "Medium"
WPP_LOCATION_TYPE = "Country/Area"


@dataclass(frozen=True, slots=True)
class PopulationRecord:
    iso3: str
    year: int
    population: int


def load_population(path: Path, *, year: int) -> dict[str, PopulationRecord]:
    records: dict[str, PopulationRecord] = {}
    wanted_year = str(year)
    with gzip.open(path, mode="rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("Time") != wanted_year:
                continue
            if row.get("Variant") != WPP_VARIANT:
                continue
            if row.get("LocTypeName") != WPP_LOCATION_TYPE:
                continue
            iso3 = (row.get("ISO3_code") or "").strip().upper()
            if len(iso3) != 3:
                continue
            raw = (row.get("PopTotal") or "").strip()
            if not raw:
                continue
            try:
                thousands = float(raw)
            except ValueError:
                continue
            if thousands <= 0:
                continue
            records[iso3] = PopulationRecord(
                iso3=iso3, year=year, population=round(thousands * 1000)
            )
    return records


def latest_available_year(path: Path, *, not_after: int) -> int | None:
    years: set[int] = set()
    with gzip.open(path, mode="rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("Variant") != WPP_VARIANT:
                continue
            raw = row.get("Time")
            if not raw:
                continue
            try:
                value = int(raw)
            except ValueError:
                continue
            if value <= not_after:
                years.add(value)
    return max(years) if years else None
