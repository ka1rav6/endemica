import { describe, expect, it } from 'vitest';
import { arrivalColor } from '@/lib/riskColor';
import { clipLine, spreadArcs, type LocatedCountry } from '@/lib/spreadFlow';
import type { MapSpreadEntry } from '@/lib/spread';

function entry(iso3: string, year: number, order: number): MapSpreadEntry {
  return {
    iso3,
    name: iso3,
    arrivalOrder: order,
    arrivalShare: 0,
    firstYear: year,
    cases: 1,
    deaths: 0,
    reportCount: 1,
  };
}

function country(iso3: string, lat: number | null, lon: number | null): LocatedCountry {
  return { iso3, name: iso3, centroid_lat: lat, centroid_lon: lon };
}

describe('clipLine', () => {
  const line: [number, number][] = [
    [0, 0],
    [10, 0],
    [20, 0],
  ];

  it('keeps the start at zero and the whole line at one', () => {
    expect(clipLine(line, 0)).toEqual([[0, 0]]);
    expect(clipLine(line, 1)).toEqual(line);
  });

  it('stops halfway along the vertices', () => {
    expect(clipLine(line, 0.5)).toEqual([
      [0, 0],
      [10, 0],
    ]);
  });
});

describe('spreadArcs', () => {
  const countries = [
    country('AAA', 0, 0),
    country('BBB', 10, 10),
    country('CCC', 40, 20),
    country('DDD', null, null),
  ];

  it('joins spread rows to country centroids and colours by how late the year is', () => {
    const arcs = spreadArcs(
      countries,
      [entry('AAA', 2019, 1), entry('BBB', 2020, 2), entry('CCC', 2020, 3), entry('DDD', 2020, 4)],
      2020,
      { first: 2019, last: 2022 },
    );
    expect(arcs).toHaveLength(2);
    expect(arcs.map((arc) => arc.toName).sort()).toEqual(['BBB', 'CCC']);
    expect(arcs.every((arc) => arc.fromName === 'AAA')).toBe(true);
    expect(arcs[0]?.coordinates.length).toBeGreaterThan(2);
    // (2020 - 2019) / (2022 - 2019) = 1/3 of the way along the arrival ramp.
    expect(arcs[0]?.color).toBe(arrivalColor(10 / 3));
  });

  it('uses the earlier footprint when the previous calendar year added nobody', () => {
    const arcs = spreadArcs(countries, [entry('AAA', 2018, 1), entry('BBB', 2020, 2)], 2020, {
      first: 2018,
      last: 2020,
    });
    expect(arcs).toHaveLength(1);
    expect(arcs[0]?.fromName).toBe('AAA');
    expect(arcs[0]?.toName).toBe('BBB');
  });

  it('draws nothing for a year that reached no new country', () => {
    expect(
      spreadArcs(countries, [entry('AAA', 2019, 1)], 2020, { first: 2019, last: 2020 }),
    ).toEqual([]);
  });

  it('keeps one arc per new country when the full grid would be huge', () => {
    const many: LocatedCountry[] = [];
    const spread: MapSpreadEntry[] = [];
    for (let index = 0; index < 10; index += 1) {
      many.push(country(`S${index}`, index, 0));
      spread.push(entry(`S${index}`, 2019, index + 1));
    }
    for (let index = 0; index < 10; index += 1) {
      many.push(country(`T${index}`, index, 30 + index));
      spread.push(entry(`T${index}`, 2020, index + 11));
    }
    const arcs = spreadArcs(many, spread, 2020, { first: 2019, last: 2020 });
    expect(arcs).toHaveLength(10);
    expect(new Set(arcs.map((arc) => arc.toName)).size).toBe(10);
  });
});
