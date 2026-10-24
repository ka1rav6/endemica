from __future__ import annotations

import gzip
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from epiroute.core.config import Settings, get_settings
from epiroute.core.http import build_client, request_with_retry
from epiroute.datasets.iso import resolve

logger = logging.getLogger(__name__)

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

REPORTING_COUNTRIES: tuple[str, ...] = (
    "be",
    "bg",
    "dk",
    "de",
    "ee",
    "ie",
    "el",
    "es",
    "fr",
    "hr",
    "it",
    "cy",
    "lv",
    "lt",
    "lu",
    "hu",
    "mt",
    "nl",
    "at",
    "pl",
    "pt",
    "ro",
    "si",
    "sk",
    "fi",
    "se",
    "is",
    "no",
    "ch",
    "uk",
    "tr",
    "me",
    "mk",
    "rs",
    "ba",
)

DEFAULT_REFERENCE_YEAR = 2019

# Eurostat reports the geo dimension as <RC>_<ICAO>_<PC>_<ICAO>; the two-letter
# prefixes are the reporting and partner country codes.
_MEASURE_DEPARTURES = "PAS_BRD_DEP"
_MEASURE_ARRIVALS = "PAS_BRD_ARR"

_SERVICE = "Eurostat avia_par"


@dataclass(frozen=True, slots=True)
class ObservedFlow:
    origin_iso3: str
    dest_iso3: str
    passengers_per_year: float
    reference_year: int
    airport_pair_count: int


def _parse_airport_pair(code: str) -> tuple[str, str] | None:
    parts = code.split("_")
    if len(parts) != 4:
        return None
    origin = resolve(parts[0])
    dest = resolve(parts[2])
    if origin is None or dest is None or origin == dest:
        return None
    return origin, dest


def _iter_values(payload: dict[str, object]) -> list[tuple[str, float]]:
    dimension_ids = payload.get("id")
    sizes = payload.get("size")
    dimensions = payload.get("dimension")
    values = payload.get("value")
    if not (
        isinstance(dimension_ids, list)
        and isinstance(sizes, list)
        and isinstance(dimensions, dict)
        and isinstance(values, dict)
    ):
        return []

    try:
        pair_axis = dimension_ids.index("airp_pr")
    except ValueError:
        return []

    index_map = dimensions["airp_pr"]["category"]["index"]
    code_by_position = {position: code for code, position in index_map.items()}

    strides = [1] * len(sizes)
    for axis in range(len(sizes) - 2, -1, -1):
        strides[axis] = strides[axis + 1] * int(sizes[axis + 1])

    results: list[tuple[str, float]] = []
    for flat_index, raw in values.items():
        if raw is None:
            continue
        position = (int(flat_index) // strides[pair_axis]) % int(sizes[pair_axis])
        code = code_by_position.get(position)
        if code is None:
            continue
        try:
            results.append((code, float(raw)))
        except (TypeError, ValueError):
            continue
    return results


def fetch_reporting_country(
    country_code: str,
    *,
    year: int = DEFAULT_REFERENCE_YEAR,
    settings: Settings | None = None,
) -> dict[str, dict[str, object]]:
    settings = settings or get_settings()
    out: dict[str, dict[str, object]] = {}
    with build_client(settings) as client:
        for measure in (_MEASURE_DEPARTURES, _MEASURE_ARRIVALS):
            url = f"{BASE_URL}/avia_par_{country_code}"
            response = request_with_retry(
                client,
                "GET",
                url,
                service=_SERVICE,
                params={
                    "format": "JSON",
                    "time": str(year),
                    "unit": "PAS",
                    "tra_meas": measure,
                    "freq": "A",
                },
            )
            if response.status_code != 200:
                logger.warning(
                    "eurostat table unavailable",
                    extra={
                        "country": country_code,
                        "measure": measure,
                        "status": response.status_code,
                    },
                )
                continue
            out[measure] = response.json()
    return out


def download_all(
    *,
    year: int = DEFAULT_REFERENCE_YEAR,
    settings: Settings | None = None,
    countries: tuple[str, ...] = REPORTING_COUNTRIES,
) -> Path:
    settings = settings or get_settings()
    target = settings.raw_data_dir / "eurostat_avia_par.json.gz"
    target.parent.mkdir(parents=True, exist_ok=True)

    collected: dict[str, dict[str, dict[str, object]]] = {}
    for code in countries:
        payloads = fetch_reporting_country(code, year=year, settings=settings)
        if payloads:
            collected[code] = payloads
            logger.info("eurostat table downloaded", extra={"country": code})

    if not collected:
        msg = "no Eurostat tables could be downloaded"
        raise RuntimeError(msg)

    document = {"reference_year": year, "tables": collected}
    with gzip.open(target, "wt", encoding="utf-8") as handle:
        json.dump(document, handle)
    return target


def load_observed_flows(path: Path) -> dict[tuple[str, str], ObservedFlow]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        document = json.load(handle)

    year = int(document.get("reference_year", DEFAULT_REFERENCE_YEAR))
    totals: dict[tuple[str, str], float] = defaultdict(float)
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)

    for payloads in document.get("tables", {}).values():
        for measure, payload in payloads.items():
            for code, value in _iter_values(payload):
                parsed = _parse_airport_pair(code)
                if parsed is None:
                    continue
                reporting, partner = parsed
                # PAS_BRD_DEP counts people boarding in the reporting country,
                # so the flow runs reporting -> partner. PAS_BRD_ARR is the
                # reverse direction.
                key = (
                    (reporting, partner) if measure == _MEASURE_DEPARTURES else (partner, reporting)
                )
                totals[key] += value
                pair_counts[key] += 1

    return {
        key: ObservedFlow(
            origin_iso3=key[0],
            dest_iso3=key[1],
            passengers_per_year=total,
            reference_year=year,
            airport_pair_count=pair_counts[key],
        )
        for key, total in totals.items()
        if total > 0
    }
