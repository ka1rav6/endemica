import { describe, expect, it } from 'vitest';
import { landAnchor } from '@/lib/landmass';

/** A square from (lon0, lat0) to (lon1, lat1), closed. */
function box(lon0: number, lat0: number, lon1: number, lat1: number): number[][] {
  return [
    [lon0, lat0],
    [lon1, lat0],
    [lon1, lat1],
    [lon0, lat1],
    [lon0, lat0],
  ];
}

const FALLBACK = { lat: 99, lon: 99 };

describe('landAnchor', () => {
  it('returns the centroid of a simple polygon', () => {
    const anchor = landAnchor({ type: 'Polygon', coordinates: [box(0, 0, 10, 10)] }, FALLBACK);
    expect(anchor.lon).toBeCloseTo(5, 6);
    expect(anchor.lat).toBeCloseTo(5, 6);
  });

  it('ignores distant territory and anchors on the largest landmass', () => {
    // A big mainland plus a small island far to the west. Averaging the two
    // would land in open water between them.
    const anchor = landAnchor(
      {
        type: 'MultiPolygon',
        coordinates: [[box(0, 40, 10, 50)], [box(-62, 17, -61, 18)]],
      },
      FALLBACK,
    );
    expect(anchor.lon).toBeCloseTo(5, 6);
    expect(anchor.lat).toBeCloseTo(45, 6);
  });

  it('keeps the anchor inside a shape whose centroid falls outside it', () => {
    // A C-shape: the centroid sits in the notch, outside the polygon.
    const ring = [
      [0, 0],
      [10, 0],
      [10, 3],
      [3, 3],
      [3, 7],
      [10, 7],
      [10, 10],
      [0, 10],
      [0, 0],
    ];
    const anchor = landAnchor({ type: 'Polygon', coordinates: [ring] }, FALLBACK);
    expect(anchor.lon).toBeLessThan(3);
    expect(anchor.lat).toBeGreaterThan(0);
    expect(anchor.lat).toBeLessThan(10);
  });

  it('does not wrap a polygon that straddles the antimeridian around the globe', () => {
    const anchor = landAnchor(
      {
        type: 'Polygon',
        coordinates: [
          [
            [179, -18],
            [-179, -18],
            [-179, -17],
            [179, -17],
            [179, -18],
          ],
        ],
      },
      FALLBACK,
    );
    expect(Math.abs(anchor.lon)).toBeGreaterThan(179);
    expect(anchor.lat).toBeCloseTo(-17.5, 1);
  });

  it('falls back when the geometry carries no usable ring', () => {
    expect(landAnchor(null, FALLBACK)).toEqual(FALLBACK);
    expect(landAnchor({ type: 'Point', coordinates: [1, 2] }, FALLBACK)).toEqual(FALLBACK);
  });
});
