import { describe, expect, it } from 'vitest';
import { selectAirports, type AirportCollection } from '@/lib/airports';

function airport(iata: string, iso3: string, lon: number, lat: number, routes: number) {
  return {
    type: 'Feature' as const,
    properties: { iata, name: `${iata} Airport`, iso3, routes },
    geometry: { type: 'Point' as const, coordinates: [lon, lat] },
  };
}

function collection(features: ReturnType<typeof airport>[]): AirportCollection {
  return { type: 'FeatureCollection', features };
}

const CENTRE = { lat: 46.6, lon: 2.3 };

function codes(result: { features: { properties: unknown }[] }): string[] {
  return result.features.map((feature) => (feature.properties as { iata: string }).iata);
}

describe('selectAirports', () => {
  it('returns nothing without a collection, a country or a centre', () => {
    const data = collection([airport('CDG', 'FRA', 2.5, 49, 1000)]);
    expect(selectAirports(null, 'FRA', CENTRE, 4).features).toHaveLength(0);
    expect(selectAirports(data, null, CENTRE, 4).features).toHaveLength(0);
    expect(selectAirports(data, 'FRA', null, 4).features).toHaveLength(0);
    expect(selectAirports(data, 'DEU', CENTRE, 4).features).toHaveLength(0);
  });

  it('drops airports with only a handful of scheduled routes', () => {
    const data = collection([
      airport('CDG', 'FRA', 2.5, 49.0, 1000),
      airport('AGF', 'FRA', 0.6, 44.2, 4),
    ]);
    expect(codes(selectAirports(data, 'FRA', CENTRE, 6))).toEqual(['CDG']);
  });

  it('keeps a country whose whole network is below the floor', () => {
    const data = collection([airport('XXX', 'FJI', 178, -18, 3)]);
    expect(codes(selectAirports(data, 'FJI', { lat: -18, lon: 178 }, 6))).toEqual(['XXX']);
  });

  it('drops the quieter of two airports that would overlap, keeping the busier', () => {
    const data = collection([
      airport('CDG', 'FRA', 2.55, 49.01, 1000),
      airport('ORY', 'FRA', 2.36, 48.73, 400),
    ]);
    // Paris at a world-ish zoom: the two are a pixel or so apart.
    expect(codes(selectAirports(data, 'FRA', CENTRE, 3))).toEqual(['CDG']);
    // Zoomed in, there is room for both.
    expect(codes(selectAirports(data, 'FRA', CENTRE, 9)).sort()).toEqual(['CDG', 'ORY']);
  });

  it('spreads the colour ramp across the mainland despite a distant outlier', () => {
    const data = collection([
      airport('CDG', 'FRA', 2.5, 49.0, 1000),
      airport('NCE', 'FRA', 7.2, 43.7, 260),
      airport('BIA', 'FRA', 9.5, 42.6, 70),
      airport('BOD', 'FRA', -0.7, 44.8, 130),
      airport('LIL', 'FRA', 3.1, 50.6, 80),
      airport('MRS', 'FRA', 5.2, 43.4, 260),
      airport('SBH', 'FRA', -62.8, 17.9, 19),
    ]);
    const scored = selectAirports(data, 'FRA', CENTRE, 9).features.map(
      (feature) => feature.properties as { iata: string; distance: number },
    );
    const byCode = new Map(scored.map((entry) => [entry.iata, entry.distance]));

    // The Caribbean airport is far beyond the rest and sits at the red end.
    expect(byCode.get('SBH')).toBe(10);
    // The mainland still uses most of the ramp rather than bunching at zero,
    // which is what scoring against the outlier itself used to do.
    const mainland = scored.filter((entry) => entry.iata !== 'SBH').map((e) => e.distance);
    expect(Math.max(...mainland)).toBeGreaterThan(7);
    expect(Math.max(...mainland) - Math.min(...mainland)).toBeGreaterThan(5);
  });

  it('scores dot size by the square root of an airport’s share of the routes', () => {
    const data = collection([
      airport('BIG', 'USA', -84.4, 33.6, 400),
      airport('SML', 'USA', -118.4, 33.9, 100),
    ]);
    const weights = new Map(
      selectAirports(data, 'USA', { lat: 39.5, lon: -99.1 }, 9).features.map((feature) => {
        const properties = feature.properties as { iata: string; weight: number };
        return [properties.iata, properties.weight];
      }),
    );
    expect(weights.get('BIG')).toBeCloseTo(1, 6);
    expect(weights.get('SML')).toBeCloseTo(0.5, 6);
  });

  it('reveals more airports as the map zooms in', () => {
    const features = Array.from({ length: 30 }, (_, index) =>
      airport(`A${index}`, 'FRA', 0 + index * 0.3, 44 + index * 0.2, 500 - index * 10),
    );
    const wide = selectAirports(collection(features), 'FRA', CENTRE, 3).features.length;
    const close = selectAirports(collection(features), 'FRA', CENTRE, 8).features.length;
    expect(close).toBeGreaterThan(wide);
    expect(close).toBeLessThanOrEqual(30);
  });
});
