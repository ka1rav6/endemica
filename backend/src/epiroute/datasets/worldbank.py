"""World Bank total population, used only as a check on the UN denominator."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from epiroute.core.config import Settings, get_settings
from epiroute.core.http import build_client, request_with_retry

logger = logging.getLogger(__name__)

SOURCE_URL = (
    "https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL"
    "?format=json&date=2024&per_page=400"
)
# A gap wider than this is flagged. It does not replace the UN figure.
MAX_RELATIVE_GAP = 0.05


def download(*, settings: Settings | None = None, year: int = 2024) -> Path:
    settings = settings or get_settings()
    target = settings.raw_data_dir / f"worldbank_population_{year}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    url = SOURCE_URL.replace("date=2024", f"date={year}")
    with build_client(settings) as client:
        response = request_with_retry(client, "GET", url, service="World Bank")
    response.raise_for_status()
    target.write_bytes(response.content)
    return target


def load_populations(path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
    populations: dict[str, int] = {}
    if not isinstance(rows, list):
        return populations
    for row in rows:
        if not isinstance(row, dict):
            continue
        iso3 = row.get("countryiso3code")
        value = row.get("value")
        if not isinstance(iso3, str) or len(iso3) != 3 or not isinstance(value, (int, float)):
            continue
        populations[iso3.upper()] = int(value)
    return populations


def compare(
    un_population: dict[str, int], world_bank: dict[str, int], *, limit: float = MAX_RELATIVE_GAP
) -> list[dict[str, object]]:
    """Countries where the two population sources differ by more than ``limit``."""
    flagged: list[dict[str, object]] = []
    for iso3, un_value in sorted(un_population.items()):
        other = world_bank.get(iso3)
        if other is None or un_value <= 0:
            continue
        gap = abs(un_value - other) / un_value
        if gap > limit:
            flagged.append(
                {
                    "iso3": iso3,
                    "un_wpp": un_value,
                    "world_bank": other,
                    "relative_gap": gap,
                }
            )
    return flagged
