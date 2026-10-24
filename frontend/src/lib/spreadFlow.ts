import type { FeatureCollection, LineString } from 'geojson';
import { greatCircleKm, greatCircleLine } from '@/lib/geo';
import { riskColor } from '@/lib/riskColor';
import type { MapSpreadEntry } from '@/lib/spread';

/** Draw every pair when the outbreak step is small. Larger steps use one arc each. */
const PAIR_LIMIT = 48;

export interface OutbreakSpan {
  first: number;
  last: number;
}

export interface LocatedCountry {
  iso3: string;
  name: string;
  centroid_lat: number | null;
  centroid_lon: number | null;
}

export interface SpreadArc {
  color: string;
  fromName: string;
  toName: string;
  year: number;
  coordinates: [number, number][];
}

/** Reveal a great-circle polyline from its start. `fraction` is 0–1. */
export function clipLine(coordinates: [number, number][], fraction: number): [number, number][] {
  const first = coordinates[0];
  if (!first) return [];
  if (fraction >= 1) return coordinates;
  if (fraction <= 0) return [first];
  const lastIndex = coordinates.length - 1;
  const distance = fraction * lastIndex;
  const index = Math.min(lastIndex - 1, Math.floor(distance));
  const start = coordinates[index];
  const end = coordinates[index + 1];
  if (!start || !end) return coordinates.slice(0, index + 1);
  const part = distance - index;
  if (part === 0) return coordinates.slice(0, index + 1);
  return [
    ...coordinates.slice(0, index + 1),
    [start[0] + (end[0] - start[0]) * part, start[1] + (end[1] - start[1]) * part],
  ];
}

export function arcsToCollection(arcs: SpreadArc[], fraction = 1): FeatureCollection<LineString> {
  return {
    type: 'FeatureCollection',
    features: arcs.map((arc) => ({
      type: 'Feature',
      properties: {
        color: arc.color,
        fromName: arc.fromName,
        toName: arc.toName,
        year: arc.year,
      },
      geometry: {
        type: 'LineString',
        coordinates: fraction >= 1 ? arc.coordinates : clipLine(arc.coordinates, fraction),
      },
    })),
  };
}

function pointOf(country: LocatedCountry | undefined): { lat: number; lon: number } | null {
  if (!country || country.centroid_lat === null || country.centroid_lon === null) return null;
  return { lat: country.centroid_lat, lon: country.centroid_lon };
}

/**
 * Great-circle arcs from countries reached in the previous year to countries
 * newly reached in `year`.
 *
 * Coordinates come from the country list, because the spread rows do not carry
 * them. Early years are greener and later years are redder along the outbreak
 * span. A small step draws every pair. A large step draws one arc per new
 * country, from the nearest country already reached, so the map stays readable.
 */
export function spreadArcs(
  countries: LocatedCountry[],
  spread: MapSpreadEntry[],
  year: number,
  span: OutbreakSpan | null,
): SpreadArc[] {
  const byIso = new Map(countries.map((country) => [country.iso3, country]));
  const located = (entry: MapSpreadEntry) => pointOf(byIso.get(entry.iso3));
  const known = spread.filter((entry) => entry.firstYear !== null && located(entry) !== null);
  const targets = known.filter((entry) => entry.firstYear === year);
  const previousYear = known.filter((entry) => entry.firstYear === year - 1);
  const earlier = known.filter((entry) => (entry.firstYear ?? year) < year);
  const sources = previousYear.length > 0 ? previousYear : earlier;
  if (targets.length === 0 || sources.length === 0) return [];

  const years = known
    .map((entry) => entry.firstYear)
    .filter((value): value is number => value !== null);
  const first = span?.first ?? Math.min(...years);
  const last = span?.last ?? Math.max(...years);
  const lateness = last === first ? 0 : Math.min(1, Math.max(0, (year - first) / (last - first)));
  const color = riskColor(lateness * 10);

  const pairs: [MapSpreadEntry, MapSpreadEntry][] = [];
  if (sources.length * targets.length <= PAIR_LIMIT) {
    for (const target of targets) {
      for (const source of sources) {
        if (source.iso3 !== target.iso3) pairs.push([source, target]);
      }
    }
  } else {
    for (const target of targets) {
      const targetPoint = located(target);
      if (!targetPoint) continue;
      let best: MapSpreadEntry | null = null;
      let bestKm = Number.POSITIVE_INFINITY;
      for (const source of sources) {
        if (source.iso3 === target.iso3) continue;
        const sourcePoint = located(source);
        if (!sourcePoint) continue;
        const km = greatCircleKm(sourcePoint, targetPoint);
        if (km < bestKm) {
          bestKm = km;
          best = source;
        }
      }
      if (best) pairs.push([best, target]);
    }
  }

  const arcs: SpreadArc[] = [];
  for (const [source, target] of pairs) {
    const from = located(source);
    const to = located(target);
    if (!from || !to) continue;
    if (from.lat === to.lat && from.lon === to.lon) continue;
    arcs.push({
      color,
      fromName: source.name,
      toName: target.name,
      year,
      coordinates: greatCircleLine(from, to),
    });
  }
  return arcs;
}
