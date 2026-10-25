import type { Point } from '@/lib/geo';

/**
 * Where to put a country on the map.
 *
 * The stored centroid is an area-weighted mean over every part of a country's
 * boundary, so a country with distant territory does not get a point anywhere
 * near the land people picture. France averages the mainland with French
 * Guiana and the Caribbean départements and lands in the Bay of Biscay; Norway
 * averages the mainland with Svalbard and lands in the Norwegian Sea; the
 * United States averages the lower 48 with Alaska and lands in Montana. That
 * point is fine as a distance anchor between countries, which is what the
 * passenger-flow model uses it for, but on a map it reads as a mistake.
 *
 * This module answers the map's question instead: a point on the country's
 * main landmass, which is where its marker belongs and what its airports
 * should be measured against.
 */

type Ring = number[][];

/** Grid resolution for the interior-point search, per refinement pass. */
const COARSE_STEPS = 40;
const FINE_STEPS = 8;
const REFINEMENTS = 2;

function outerRings(geometry: unknown): Ring[] {
  if (typeof geometry !== 'object' || geometry === null) return [];
  const { type, coordinates } = geometry as { type?: unknown; coordinates?: unknown };
  if (!Array.isArray(coordinates)) return [];
  if (type === 'Polygon') {
    const outer: unknown = coordinates[0];
    return Array.isArray(outer) ? [outer as Ring] : [];
  }
  if (type === 'MultiPolygon') {
    return coordinates
      .map((part: unknown) => (Array.isArray(part) ? (part[0] as Ring | undefined) : undefined))
      .filter((ring): ring is Ring => Array.isArray(ring));
  }
  return [];
}

/**
 * Keep longitudes continuous across the antimeridian, so Fiji is one small
 * ring rather than one that appears to wrap the globe.
 */
function unwrap(ring: Ring): Ring {
  const first = ring[0];
  if (!first) return [];
  const out: Ring = [[first[0] ?? 0, first[1] ?? 0]];
  let previous = first[0] ?? 0;
  for (let i = 1; i < ring.length; i += 1) {
    const point = ring[i];
    if (!point) continue;
    let lon = point[0] ?? 0;
    while (lon - previous > 180) lon -= 360;
    while (lon - previous < -180) lon += 360;
    out.push([lon, point[1] ?? 0]);
    previous = lon;
  }
  return out;
}

function wrapLon(lon: number): number {
  return ((((lon + 180) % 360) + 360) % 360) - 180;
}

interface RingCentroid {
  lon: number;
  lat: number;
  area: number;
}

/** Centroid and absolute area of a closed ring, by the shoelace formula. */
function ringCentroid(ring: Ring): RingCentroid {
  let area = 0;
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const a = ring[i];
    const b = ring[i + 1];
    if (!a || !b) continue;
    const [x0 = 0, y0 = 0] = a;
    const [x1 = 0, y1 = 0] = b;
    const cross = x0 * y1 - x1 * y0;
    area += cross;
    cx += (x0 + x1) * cross;
    cy += (y0 + y1) * cross;
  }
  if (area === 0) {
    const lon = ring.reduce((sum, p) => sum + (p[0] ?? 0), 0) / Math.max(ring.length, 1);
    const lat = ring.reduce((sum, p) => sum + (p[1] ?? 0), 0) / Math.max(ring.length, 1);
    return { lon, lat, area: 0 };
  }
  area *= 0.5;
  return { lon: cx / (6 * area), lat: cy / (6 * area), area: Math.abs(area) };
}

/** Even-odd ray cast. The ring is assumed closed. */
function contains(ring: Ring, lon: number, lat: number): boolean {
  let hit = false;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const a = ring[i];
    const b = ring[i + 1];
    if (!a || !b) continue;
    const [x0 = 0, y0 = 0] = a;
    const [x1 = 0, y1 = 0] = b;
    if (y0 > lat !== y1 > lat && lon < x0 + ((lat - y0) * (x1 - x0)) / (y1 - y0)) hit = !hit;
  }
  return hit;
}

/**
 * Distance from a point to the ring, with longitudes scaled by `lonScale` so
 * the comparison is in roughly even ground distance rather than raw degrees.
 */
function distanceToEdge(ring: Ring, lon: number, lat: number, lonScale: number): number {
  let best = Infinity;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const a = ring[i];
    const b = ring[i + 1];
    if (!a || !b) continue;
    const [x0 = 0, y0 = 0] = a;
    const [x1 = 0, y1 = 0] = b;
    const dx = (x1 - x0) * lonScale;
    const dy = y1 - y0;
    const px = (lon - x0) * lonScale;
    const py = lat - y0;
    const length = dx * dx + dy * dy;
    const t = length === 0 ? 0 : Math.max(0, Math.min(1, (px * dx + py * dy) / length));
    const ex = px - t * dx;
    const ey = py - t * dy;
    best = Math.min(best, ex * ex + ey * ey);
  }
  return Math.sqrt(best);
}

/**
 * The point inside `ring` that is farthest from its edge, found by a grid
 * search that refines around its own best answer. A concave country - Norway,
 * Croatia - has a centroid that falls outside itself, and this is the point
 * that reads as "the middle" instead.
 */
function interiorPoint(ring: Ring): Point | null {
  let minLon = Infinity;
  let maxLon = -Infinity;
  let minLat = Infinity;
  let maxLat = -Infinity;
  for (const point of ring) {
    const lon = point[0] ?? 0;
    const lat = point[1] ?? 0;
    minLon = Math.min(minLon, lon);
    maxLon = Math.max(maxLon, lon);
    minLat = Math.min(minLat, lat);
    maxLat = Math.max(maxLat, lat);
  }
  if (!Number.isFinite(minLon) || !Number.isFinite(minLat)) return null;

  let best: { lon: number; lat: number; clearance: number } | null = null;
  let steps = COARSE_STEPS;
  for (let pass = 0; pass <= REFINEMENTS; pass += 1) {
    const lonScale = Math.cos(((minLat + maxLat) / 2) * (Math.PI / 180));
    for (let i = 0; i <= steps; i += 1) {
      for (let j = 0; j <= steps; j += 1) {
        const lon = minLon + ((maxLon - minLon) * i) / steps;
        const lat = minLat + ((maxLat - minLat) * j) / steps;
        if (!contains(ring, lon, lat)) continue;
        const clearance = distanceToEdge(ring, lon, lat, lonScale);
        if (!best || clearance > best.clearance) best = { lon, lat, clearance };
      }
    }
    if (!best) return null;
    const lonStep = (maxLon - minLon) / steps;
    const latStep = (maxLat - minLat) / steps;
    minLon = best.lon - lonStep;
    maxLon = best.lon + lonStep;
    minLat = best.lat - latStep;
    maxLat = best.lat + latStep;
    steps = FINE_STEPS;
  }
  return best ? { lat: best.lat, lon: wrapLon(best.lon) } : null;
}

/**
 * A point on the country's largest landmass, or `fallback` when the geometry
 * cannot supply one.
 */
export function landAnchor(geometry: unknown, fallback: Point): Point {
  const rings = outerRings(geometry)
    .map(unwrap)
    .filter((ring) => ring.length >= 4);
  if (rings.length === 0) return fallback;

  let largest: Ring | null = null;
  let largestCentroid: RingCentroid | null = null;
  for (const ring of rings) {
    const centroid = ringCentroid(ring);
    if (!largestCentroid || centroid.area > largestCentroid.area) {
      largest = ring;
      largestCentroid = centroid;
    }
  }
  if (!largest || !largestCentroid) return fallback;

  if (contains(largest, largestCentroid.lon, largestCentroid.lat)) {
    return { lat: largestCentroid.lat, lon: wrapLon(largestCentroid.lon) };
  }
  return interiorPoint(largest) ?? fallback;
}
