import type { ActiveCountry, CountrySpread } from '@/types/api';

export interface MapSpreadEntry {
  iso3: string;
  name: string;
  arrivalOrder: number;
  arrivalShare: number;
  firstYear: number | null;
  cases: number | null;
  deaths: number | null;
  reportCount: number;
  diseaseCount?: number;
  diseaseNames?: string[];
}

function firstYear(iso: string | null): number | null {
  if (!iso) return null;
  const year = Number(iso.slice(0, 4));
  return Number.isFinite(year) ? year : null;
}

/**
 * Countries a disease had reached by ``ceiling``, in arrival order.
 *
 * ``arrivalShare`` runs 0 to 1 across the visible set so the map can colour by
 * when a country was first reported rather than by how bad it got.
 */
export function spreadEntries(
  countries: CountrySpread[],
  ceiling: number | null,
): MapSpreadEntry[] {
  const within = countries.filter((entry) => {
    if (ceiling === null) return true;
    const year = firstYear(entry.first_published_at);
    return year === null || year <= ceiling;
  });
  const steps = Math.max(within.length - 1, 1);
  return within.map((entry, index) => ({
    iso3: entry.country_iso3,
    name: entry.country_name,
    arrivalOrder: index + 1,
    arrivalShare: within.length === 1 ? 0 : index / steps,
    firstYear: firstYear(entry.first_published_at),
    cases: entry.cases_confirmed,
    deaths: entry.deaths,
    reportCount: entry.report_count,
  }));
}

/**
 * Countries currently reporting something, coloured by how many diseases.
 *
 * The combined view has no arrival order to show, so `arrivalShare` carries
 * disease load instead and the map legend says so. It runs the same way round
 * as the arrival share above: 0 is the cool end of the ramp, 1 the hot one. A
 * set that all carry the same load has no gradient to draw, so it sits at the
 * hot end rather than the safe-looking one.
 */
export function activeCountryEntries(countries: ActiveCountry[]): MapSpreadEntry[] {
  const worst = Math.max(...countries.map((entry) => entry.disease_count), 1);
  return countries.map((entry, index) => ({
    iso3: entry.country_iso3,
    name: entry.country_name,
    arrivalOrder: index + 1,
    arrivalShare: entry.disease_count / worst,
    firstYear: entry.last_published_at ? Number(entry.last_published_at.slice(0, 4)) : null,
    cases: entry.cases_confirmed,
    deaths: entry.deaths,
    reportCount: entry.report_count,
    diseaseCount: entry.disease_count,
    diseaseNames: entry.disease_names,
  }));
}
