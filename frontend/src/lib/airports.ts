import type { Feature, FeatureCollection, Point as GeoPoint } from 'geojson';
import { greatCircleKm, type Point } from '@/lib/geo';

export interface AirportProperties {
  iata: string;
  name: string;
  iso3: string;
  routes: number;
}

export type AirportCollection = FeatureCollection<GeoPoint, AirportProperties>;

/**
 * An airport on fewer scheduled routes than this moves nobody at the scale
 * this map works at. OpenFlights lists thousands of them - an airstrip with
 * two weekly flights counts the same as a hub - and drawing them buries the
 * airports that actually carry an importation risk.
 */
const MIN_ROUTES = 8;

/**
 * The gap to leave between two dots, in screen pixels at the map's current
 * zoom. A dot is at most 18px across including its stroke, so anything
 * tighter than this overlaps into a blob and the map stops saying anything.
 */
const SEPARATION_PX = 24;

/** A ceiling for the largest countries, reached only when zoomed well in. */
const MAX_DOTS = 40;

/**
 * One airport thousands of kilometres offshore - Saint-Barthélemy for France,
 * Hawaii for the United States - would otherwise set the far end of the
 * colour ramp on its own and squash every mainland airport into the first
 * tenth of it, which is why every French dot came out the same green. Scoring
 * against the 90th percentile instead spreads the mainland across the whole
 * ramp and leaves the genuine outlier clamped at the red end, where it
 * belongs.
 */
const RAMP_PERCENTILE = 0.9;

/** MapLibre's tile size: the unit its zoom levels are defined against. */
const TILE_SIZE = 512;

const MAX_MERCATOR_LAT = 85.051129;

function mercatorX(lon: number, worldSize: number): number {
  return ((lon + 180) / 360) * worldSize;
}

function mercatorY(lat: number, worldSize: number): number {
  const clamped = Math.max(-MAX_MERCATOR_LAT, Math.min(MAX_MERCATOR_LAT, lat));
  const phi = (clamped * Math.PI) / 180;
  const merc = Math.log(Math.tan(Math.PI / 4 + phi / 2));
  return ((1 - merc / Math.PI) / 2) * worldSize;
}

function percentile(sorted: number[], fraction: number): number {
  if (sorted.length === 0) return 0;
  const index = Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * fraction));
  return sorted[index] ?? 0;
}

const EMPTY: FeatureCollection<GeoPoint> = { type: 'FeatureCollection', features: [] };

/**
 * The airports to draw for one country, scored by how far each one is from
 * the outbreak centre.
 *
 * WHO Disease Outbreak News is reported at country level, so the honest
 * epicentre is the point the pin marks, and the score is relative to this
 * country's own airports rather than the globe.
 *
 * Which airports are drawn depends on the zoom, because that is what decides
 * whether there is room for them: busiest first, each one kept only when it
 * clears the dots already placed. Zooming in makes room and reveals more,
 * rather than the map showing forty overlapping dots at every scale.
 */
export function selectAirports(
  collection: AirportCollection | null,
  iso3: string | null | undefined,
  centre: Point | null,
  zoom: number,
): FeatureCollection<GeoPoint> {
  if (!collection || !iso3 || !centre) return EMPTY;

  const own = collection.features.filter((feature) => feature.properties.iso3 === iso3);
  if (own.length === 0) return EMPTY;
  // A country whose whole network is below the floor still gets its airports:
  // the floor is there to thin a crowd, not to empty a map.
  const served = own.filter((feature) => feature.properties.routes >= MIN_ROUTES);
  const candidates = served.length > 0 ? served : own;

  const measured = candidates.map((feature) => {
    const [lon, lat] = feature.geometry.coordinates;
    return {
      feature,
      km: greatCircleKm(centre, { lat: lat ?? centre.lat, lon: lon ?? centre.lon }),
    };
  });

  const reference = Math.max(
    percentile(
      measured.map((entry) => entry.km).sort((a, b) => a - b),
      RAMP_PERCENTILE,
    ),
    1,
  );
  const busiest = Math.max(...measured.map((entry) => entry.feature.properties.routes), 1);

  const worldSize = TILE_SIZE * 2 ** zoom;
  const placed: { x: number; y: number }[] = [];
  const features: Feature<GeoPoint>[] = [];

  for (const { feature, km } of measured.sort(
    (x, y) => y.feature.properties.routes - x.feature.properties.routes,
  )) {
    if (features.length >= MAX_DOTS) break;
    const [lon, lat] = feature.geometry.coordinates;
    const x = mercatorX(lon ?? 0, worldSize);
    const y = mercatorY(lat ?? 0, worldSize);
    const crowded = placed.some((other) => {
      // Two dots either side of the antimeridian are neighbours on screen.
      let dx = Math.abs(other.x - x);
      if (dx > worldSize / 2) dx = worldSize - dx;
      const dy = other.y - y;
      return dx * dx + dy * dy < SEPARATION_PX * SEPARATION_PX;
    });
    if (crowded) continue;
    placed.push({ x, y });
    features.push({
      type: 'Feature',
      properties: {
        ...feature.properties,
        km: Math.round(km),
        distance: Math.min(10, (km / reference) * 10),
        // The eye reads a dot by its area, so the radius goes as the square
        // root of the share: twice the routes, twice the ink.
        weight: Math.sqrt(feature.properties.routes / busiest),
      },
      geometry: feature.geometry,
    });
  }

  return { type: 'FeatureCollection', features };
}
