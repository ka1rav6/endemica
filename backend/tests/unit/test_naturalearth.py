from __future__ import annotations

import pytest

from epiroute.datasets.naturalearth import geometry_centroid


def _square(lon: float, lat: float, size: float = 4.0) -> list[list[float]]:
    half = size / 2
    return [
        [lon - half, lat - half],
        [lon + half, lat - half],
        [lon + half, lat + half],
        [lon - half, lat + half],
        [lon - half, lat - half],
    ]


def test_axis_aligned_square_centroid_is_its_centre() -> None:
    lat, lon = geometry_centroid({"type": "Polygon", "coordinates": [_square(10, 20)]})
    assert lat == pytest.approx(20, abs=0.01)
    assert lon == pytest.approx(10, abs=0.01)


def test_ring_that_crosses_the_antimeridian_stays_in_the_pacific() -> None:
    ring = [
        [179.0, 0.0],
        [-179.0, 0.0],
        [-179.0, 4.0],
        [179.0, 4.0],
        [179.0, 0.0],
    ]
    lat, lon = geometry_centroid({"type": "Polygon", "coordinates": [ring]})
    assert lat == pytest.approx(2, abs=0.05)
    assert abs(lon) > 170


def test_split_pacific_parts_average_across_the_date_line() -> None:
    geometry: dict[str, object] = {
        "type": "MultiPolygon",
        "coordinates": [[_square(170, 0, 2)], [_square(-170, 0, 2)]],
    }
    lat, lon = geometry_centroid(geometry)
    assert lat == pytest.approx(0, abs=0.05)
    assert abs(lon) > 170
