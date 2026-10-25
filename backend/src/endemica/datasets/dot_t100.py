"""US Department of Transportation international passenger totals.

The table is ``xgub-n9bw`` ("International_Report_Passengers") on
data.transportation.gov. It is a public-domain bulk download, which replaces
the interactive BTS TranStats form.

Rows have no direction column. Each airport pair is treated as the sum of both
directions. Where Eurostat reports the same country pair, the total is split
in Eurostat's proportion. Otherwise it is split in half, and the flow is
labelled as that assumption.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from pathlib import Path

from endemica.core.config import Settings, get_settings
from endemica.core.http import build_client, request_with_retry
from endemica.datasets.eurostat import ObservedFlow
from endemica.datasets.openflights import Airport

logger = logging.getLogger(__name__)

DATASET_ID = "xgub-n9bw"
SOURCE_URL = f"https://data.transportation.gov/resource/{DATASET_ID}.csv"
AGREEMENT_LOW = 0.8
AGREEMENT_HIGH = 1.25


def download(year: int = 2024, *, settings: Settings | None = None) -> Path:
    """Download airport-pair totals for one calendar year."""
    settings = settings or get_settings()
    target = settings.raw_data_dir / f"dot_t100_{year}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    params = {
        "$select": "usg_apt,fg_apt,sum(total)",
        "$where": f"year={year}",
        "$group": "usg_apt,fg_apt",
        "$limit": "50000",
    }
    with build_client(settings) as client:
        response = request_with_retry(
            client, "GET", SOURCE_URL, service="US DOT T-100", params=params
        )
    response.raise_for_status()
    target.write_bytes(response.content)
    return target


def _column(row: dict[str, str], *names: str) -> str:
    folded = {key.casefold(): value for key, value in row.items()}
    for name in names:
        value = folded.get(name.casefold())
        if value:
            return value
    return ""


def undirected_country_totals(
    path: Path, airports: dict[str, Airport]
) -> dict[frozenset[str], float]:
    """Sum annual passengers by unordered country pair."""
    totals: dict[frozenset[str], float] = defaultdict(float)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            us_code = _column(row, "usg_apt").upper()
            foreign_code = _column(row, "fg_apt").upper()
            raw_total = _column(row, "sum_total", "sum(total)")
            us = airports.get(us_code)
            foreign = airports.get(foreign_code)
            if us is None or foreign is None or not raw_total:
                continue
            if us.country_iso3 == foreign.country_iso3:
                continue
            try:
                passengers = float(raw_total)
            except ValueError:
                continue
            if passengers <= 0:
                continue
            totals[frozenset((us.country_iso3, foreign.country_iso3))] += passengers
    return dict(totals)


def _eurostat_both(
    eurostat: dict[tuple[str, str], ObservedFlow], origin: str, dest: str
) -> tuple[float, float]:
    forward = eurostat.get((origin, dest))
    backward = eurostat.get((dest, origin))
    return (
        forward.passengers_per_year if forward else 0.0,
        backward.passengers_per_year if backward else 0.0,
    )


def direct_flows(
    undirected: dict[frozenset[str], float],
    eurostat: dict[tuple[str, str], ObservedFlow],
    *,
    year: int,
) -> tuple[dict[tuple[str, str], ObservedFlow], list[dict[str, object]]]:
    """Split undirected totals into directed flows and compare them with Eurostat."""
    directed: dict[tuple[str, str], ObservedFlow] = {}
    checks: list[dict[str, object]] = []
    for pair, total in undirected.items():
        origin, dest = tuple(pair)
        forward, backward = _eurostat_both(eurostat, origin, dest)
        euro_sum = forward + backward
        if euro_sum > 0:
            share = forward / euro_sum
            ratio = total / euro_sum
            agree = AGREEMENT_LOW <= ratio <= AGREEMENT_HIGH
            checks.append(
                {
                    "origin_iso3": origin,
                    "dest_iso3": dest,
                    "dot_passengers": total,
                    "eurostat_passengers": euro_sum,
                    "ratio": ratio,
                    "agree": agree,
                }
            )
            cross_source = "eurostat_avia_par"
            cross_ratio = ratio
        else:
            share = 0.5
            cross_source = None
            cross_ratio = None
        for start, end, portion in (
            (origin, dest, share),
            (dest, origin, 1.0 - share),
        ):
            if portion <= 0:
                continue
            directed[(start, end)] = ObservedFlow(
                origin_iso3=start,
                dest_iso3=end,
                passengers_per_year=total * portion,
                reference_year=year,
                airport_pair_count=0,
                source="dot_t100",
                cross_check_source=cross_source,
                cross_check_ratio=cross_ratio,
            )
    return directed, checks


def agreement_rate(checks: list[dict[str, object]]) -> float | None:
    """Share of overlapping pairs whose DOT/Eurostat ratio is inside the band."""
    if not checks:
        return None
    agreed = sum(1 for check in checks if check["agree"])
    return agreed / len(checks)
