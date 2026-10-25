from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import pycountry

from endemica.datasets.iso import UNASSIGNED_ISO_PLACEHOLDERS, resolve


def _iso2_from_iso3(iso3: str) -> str | None:
    record = pycountry.countries.get(alpha_3=iso3.upper())
    return str(record.alpha_2) if record is not None else None


_WHO_REGION_BY_ISO3: dict[str, str] = {}


@dataclass(frozen=True, slots=True)
class CountryGeometry:
    iso3: str
    iso2: str | None
    name: str
    official_name: str | None
    region: str | None
    subregion: str | None
    centroid_lat: float
    centroid_lon: float
    geometry: dict[str, object]


def _ring_centroid(ring: list[list[float]]) -> tuple[float, float, float]:
    area = cx = cy = 0.0
    n = len(ring)
    for i in range(n - 1):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[i + 1][0], ring[i + 1][1]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if area == 0.0:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return sum(xs) / len(xs), sum(ys) / len(ys), 0.0
    area *= 0.5
    return cx / (6.0 * area), cy / (6.0 * area), abs(area)


def _polygons(geometry: dict[str, object]) -> list[list[list[float]]]:
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or not coords:
        return []
    if kind == "Polygon":
        outer = coords[0]
        return [outer] if isinstance(outer, list) else []
    if kind == "MultiPolygon":
        return [part[0] for part in coords if isinstance(part, list) and part]
    return []


def _unwrap_ring(ring: list[list[float]]) -> list[list[float]]:
    """Keep longitudes continuous so a date-line ring is not treated as a world-spanning one."""
    if not ring:
        return []
    unwrapped: list[list[float]] = [[ring[0][0], ring[0][1]]]
    offset = 0.0
    previous = ring[0][0]
    for point in ring[1:]:
        lon = point[0] + offset
        while lon - previous > 180:
            lon -= 360
            offset -= 360
        while lon - previous < -180:
            lon += 360
            offset += 360
        unwrapped.append([lon, point[1]])
        previous = lon
    return unwrapped


def _wrap_lon(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0


def geometry_centroid(geometry: dict[str, object]) -> tuple[float, float]:
    sin_sum = cos_sum = lat_sum = total_area = 0.0
    fallback_lat = fallback_lon = 0.0
    for ring in _polygons(geometry):
        if len(ring) < 4:
            continue
        lon, lat, area = _ring_centroid(_unwrap_ring(ring))
        if area <= 0:
            fallback_lat, fallback_lon = lat, _wrap_lon(lon)
            continue
        phi = math.radians(lon)
        sin_sum += math.sin(phi) * area
        cos_sum += math.cos(phi) * area
        lat_sum += lat * area
        total_area += area
    if total_area > 0:
        return lat_sum / total_area, _wrap_lon(math.degrees(math.atan2(sin_sum, cos_sum)))
    return fallback_lat, fallback_lon


def load_country_geometries(path: Path) -> list[CountryGeometry]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    results: list[CountryGeometry] = []
    seen: set[str] = set()

    for feature in payload.get("features", []):
        props = feature.get("properties", {})
        geometry = feature.get("geometry")
        if not geometry:
            continue

        raw_iso3 = str(props.get("ISO_A3") or props.get("ISO_A3_EH") or "").strip()
        admin = str(props.get("ADMIN") or props.get("NAME") or "").strip()
        iso3 = None if raw_iso3.upper() in UNASSIGNED_ISO_PLACEHOLDERS else resolve(raw_iso3)
        if iso3 is None:
            iso3 = resolve(admin)
        if iso3 is None or iso3 in seen:
            continue
        seen.add(iso3)

        raw_iso2 = str(props.get("ISO_A2") or props.get("ISO_A2_EH") or "").strip().upper()
        iso2 = (
            raw_iso2 if len(raw_iso2) == 2 and raw_iso2 not in UNASSIGNED_ISO_PLACEHOLDERS else None
        )
        if iso2 is None:
            iso2 = _iso2_from_iso3(iso3)
        lat, lon = geometry_centroid(geometry)

        results.append(
            CountryGeometry(
                iso3=iso3,
                iso2=iso2,
                name=admin or iso3,
                official_name=str(props.get("NAME_LONG") or "") or None,
                region=str(props.get("CONTINENT") or "") or None,
                subregion=str(props.get("SUBREGION") or "") or None,
                centroid_lat=round(lat, 5),
                centroid_lon=round(lon, 5),
                geometry=geometry,
            )
        )
    return results


def who_region(iso3: str) -> str | None:
    return _WHO_REGION_BY_ISO3.get(iso3.upper())
