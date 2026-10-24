import { describe, expect, it } from 'vitest';
import { MAX_DISEASE_LOAD, activeCountryEntries, spreadEntries } from '@/lib/spread';
import type { ActiveCountry, CountrySpread } from '@/types/api';

function active(iso3: string, disease_count: number): ActiveCountry {
  return {
    country_iso3: iso3,
    country_name: iso3,
    centroid_lat: null,
    centroid_lon: null,
    disease_count,
    report_count: 1,
    cases_confirmed: null,
    cases_reported: null,
    deaths: null,
    last_published_at: '2026-08-30T00:00:00Z',
    disease_keys: [],
    disease_names: [],
  };
}

function spread(iso3: string, year: number): CountrySpread {
  return {
    country_iso3: iso3,
    country_name: iso3,
    centroid_lat: null,
    centroid_lon: null,
    report_count: 1,
    first_published_at: `${year}-01-01T00:00:00Z`,
    last_published_at: `${year}-01-01T00:00:00Z`,
    cases_confirmed: null,
    cases_reported: null,
    deaths: null,
    counts_as_of: null,
    counts_reconciled: true,
    grounded: true,
    report_url: null,
    report_title: null,
  } as CountrySpread;
}

function shareOf(entries: ReturnType<typeof activeCountryEntries>, iso3: string): number {
  const found = entries.find((entry) => entry.iso3 === iso3);
  if (!found) throw new Error(`no entry for ${iso3}`);
  return found.arrivalShare;
}

describe('activeCountryEntries', () => {
  it('gives one disease the same shade whatever the worst country carries', () => {
    // The bug this pins: the scale used to be a ratio to the worst country, so
    // a single country with a long list pushed everywhere else to the green end
    // and the whole map read as uniform.
    const alone = activeCountryEntries([active('THA', 1), active('JPN', 1)]);
    const withOutlier = activeCountryEntries([
      active('THA', 1),
      active('JPN', 1),
      active('COD', 12),
    ]);
    expect(shareOf(withOutlier, 'THA')).toBe(shareOf(alone, 'THA'));
  });

  it('separates one disease from several', () => {
    const entries = activeCountryEntries([active('THA', 1), active('COD', 3)]);
    expect(shareOf(entries, 'COD')).toBeGreaterThan(shareOf(entries, 'THA'));
  });

  it('puts a heavy load at the top of the ramp and keeps it there', () => {
    const entries = activeCountryEntries([
      active('COD', MAX_DISEASE_LOAD),
      active('NGA', MAX_DISEASE_LOAD + 7),
    ]);
    expect(shareOf(entries, 'COD')).toBe(1);
    expect(shareOf(entries, 'NGA')).toBe(1);
  });

  it('keeps a reporting country off the very bottom of the ramp', () => {
    // Zero would paint it the same as a country reporting nothing at all.
    expect(shareOf(activeCountryEntries([active('THA', 1)]), 'THA')).toBeGreaterThan(0);
  });
});

describe('spreadEntries', () => {
  it('uses the whole ramp across the countries a disease reached', () => {
    const entries = spreadEntries(
      [spread('CHN', 2020), spread('THA', 2020), spread('ZAF', 2021)],
      null,
    );
    expect(entries[0]?.arrivalShare).toBe(0);
    expect(entries[entries.length - 1]?.arrivalShare).toBe(1);
  });

  it('re-spreads the ramp over the countries the timeline leaves visible', () => {
    const all = [spread('CHN', 2020), spread('THA', 2021), spread('ZAF', 2022)];
    const clipped = spreadEntries(all, 2021);
    expect(clipped.map((entry) => entry.iso3)).toEqual(['CHN', 'THA']);
    expect(clipped[clipped.length - 1]?.arrivalShare).toBe(1);
  });
});
