"""Eurostat passenger flows must not count the same route twice."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from endemica.datasets.eurostat import load_observed_flows


def _payload(pairs: dict[str, float]) -> dict[str, object]:
    index = {code: position for position, code in enumerate(pairs)}
    return {
        "id": ["airp_pr"],
        "size": [len(pairs)],
        "dimension": {"airp_pr": {"category": {"index": index}}},
        "value": {str(position): value for position, value in enumerate(pairs.values())},
    }


def test_departures_are_kept_when_the_partner_also_reports_arrivals(tmp_path: Path) -> None:
    document = {
        "reference_year": 2024,
        "tables": {
            "de": {"PAS_BRD_DEP": _payload({"DE_EDDF_FR_LFPG": 1000.0})},
            "fr": {
                "PAS_BRD_ARR": _payload({"FR_LFPG_DE_EDDF": 1000.0}),
                "PAS_BRD_DEP": _payload({"FR_LFPG_US_KJFK": 50.0}),
            },
        },
    }
    path = tmp_path / "eurostat.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(document, handle)

    flows = load_observed_flows(path)

    assert flows[("DEU", "FRA")].passengers_per_year == 1000.0
    assert flows[("FRA", "USA")].passengers_per_year == 50.0
