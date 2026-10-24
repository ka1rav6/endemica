import { describe, expect, it } from 'vitest';
import { greatCircleKm, greatCircleLine, interpolateGreatCircle } from '@/lib/geo';

describe('greatCircleKm', () => {
  it('is zero for the same point', () => {
    expect(greatCircleKm({ lat: 10, lon: 20 }, { lat: 10, lon: 20 })).toBeCloseTo(0, 6);
  });

  it('matches a quarter of the circumference from equator to pole', () => {
    expect(greatCircleKm({ lat: 0, lon: 0 }, { lat: 90, lon: 0 })).toBeCloseTo(10007.5, 0);
  });

  it('matches a known city pair', () => {
    const km = greatCircleKm({ lat: 51.47, lon: -0.4543 }, { lat: 40.6413, lon: -73.7781 });
    expect(km).toBeGreaterThan(5450);
    expect(km).toBeLessThan(5630);
  });

  it('is symmetric', () => {
    const a = greatCircleKm({ lat: 12, lon: 34 }, { lat: -56, lon: 78 });
    const b = greatCircleKm({ lat: -56, lon: 78 }, { lat: 12, lon: 34 });
    expect(a).toBeCloseTo(b, 6);
  });
});

describe('interpolateGreatCircle', () => {
  it('returns the endpoints at the extremes', () => {
    const a = { lat: 10, lon: 20 };
    const b = { lat: 40, lon: 60 };
    expect(interpolateGreatCircle(a, b, 0).lat).toBeCloseTo(a.lat, 6);
    expect(interpolateGreatCircle(a, b, 1).lat).toBeCloseTo(b.lat, 6);
  });

  it('places the midpoint between the endpoints', () => {
    const mid = interpolateGreatCircle({ lat: 0, lon: 0 }, { lat: 0, lon: 90 }, 0.5);
    expect(mid.lon).toBeCloseTo(45, 4);
    expect(mid.lat).toBeCloseTo(0, 4);
  });

  it('handles identical endpoints without dividing by zero', () => {
    const point = interpolateGreatCircle({ lat: 5, lon: 5 }, { lat: 5, lon: 5 }, 0.5);
    expect(Number.isFinite(point.lat)).toBe(true);
    expect(Number.isFinite(point.lon)).toBe(true);
  });
});

describe('greatCircleLine', () => {
  it('returns one more point than the step count', () => {
    expect(greatCircleLine({ lat: 0, lon: 0 }, { lat: 10, lon: 10 }, 8)).toHaveLength(9);
  });

  it('keeps longitudes continuous across the antimeridian', () => {
    const line = greatCircleLine({ lat: 35, lon: 139 }, { lat: 34, lon: -118 }, 48);
    for (let i = 1; i < line.length; i += 1) {
      const step = Math.abs(line[i]![0] - line[i - 1]![0]);
      expect(step).toBeLessThan(180);
    }
  });

  it('produces finite coordinates throughout', () => {
    const line = greatCircleLine({ lat: -70, lon: -170 }, { lat: 70, lon: 170 }, 32);
    for (const [lon, lat] of line) {
      expect(Number.isFinite(lon)).toBe(true);
      expect(Number.isFinite(lat)).toBe(true);
      expect(lat).toBeGreaterThanOrEqual(-91);
      expect(lat).toBeLessThanOrEqual(91);
    }
  });
});
