import type { CountrySpread } from '@/types/api';

export interface MapSpreadEntry {
  iso3: string;
  name: string;
  arrivalOrder: number;
  arrivalShare: number;
  firstYear: number | null;
  cases: number | null;
  deaths: number | null;
  reportCount: number;
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
