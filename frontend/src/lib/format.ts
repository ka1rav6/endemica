import type { BandedQuantity, Quantity, ValueType } from '@/types/api';

export const UNAVAILABLE_REASON_TEXT: Record<string, string> = {
  no_local_case_data: 'no local case data',
  no_passenger_data: 'no passenger-flow data',
  no_population_data: 'no population data',
  no_prevalence_data: 'no usable origin prevalence',
  no_active_outbreak: 'no reported outbreak to import from',
  parameter_not_estimable: 'a required parameter is not estimable',
  model_not_applicable: 'this model does not apply to this pathogen',
  subthreshold_transmission: 'transmission is below the threshold for sustained spread',
  numerical_failure: 'the calculation did not converge',
  not_implemented: 'not implemented yet',
};

export const VALUE_TYPE_LABEL: Record<ValueType, string> = {
  observed: 'Observed',
  estimated: 'Estimated',
  modelled: 'Modelled',
  scenario: 'Scenario',
  unknown: 'Not estimable',
};

export const VALUE_TYPE_DESCRIPTION: Record<ValueType, string> = {
  observed: 'Reported directly by an identified source.',
  estimated: 'Derived from observations by a documented procedure that adds assumptions.',
  modelled: 'Produced by an explicit mathematical model from other inputs.',
  scenario: 'Produced under assumptions you or EpiRoute chose, not a measurement.',
  unknown: 'The inputs were insufficient, so no value is published.',
};

export function formatPercent(value: number | null, digits = 1): string {
  if (value === null || !Number.isFinite(value)) return '—';
  if (value > 0 && value < 0.001) return '< 0.1%';
  if (value > 0.9999) return '> 99.99%';
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatBand(band: BandedQuantity, digits = 1): string {
  if (band.low === null || band.high === null) return '—';
  return `${formatPercent(band.low, digits)} – ${formatPercent(band.high, digits)}`;
}

export function formatRate(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—';
  if (value === 0) return '0';
  if (value < 0.001) return value.toExponential(2);
  if (value < 1) return value.toFixed(4);
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return value.toLocaleString();
}

export function formatPassengers(value: number): string {
  if (value < 1) return `${value.toFixed(2)}/day`;
  if (value < 1000) return `${Math.round(value).toLocaleString()}/day`;
  return `${Math.round(value).toLocaleString()}/day`;
}

export function formatQuantity(quantity: Quantity | null): string {
  if (!quantity || quantity.value === null) return '—';
  return formatCount(quantity.value);
}

export function unavailableText(reason: string | null): string {
  if (!reason) return 'not estimable';
  return UNAVAILABLE_REASON_TEXT[reason] ?? reason.replaceAll('_', ' ');
}

export function formatDate(iso: string | null): string {
  if (!iso) return 'unknown date';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'unknown date';
  return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return 'unknown time';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return 'unknown time';
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function relativeAge(iso: string | null): string {
  if (!iso) return 'age unknown';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 'age unknown';
  const hours = (Date.now() - then) / 3_600_000;
  if (hours < 1) return 'less than an hour ago';
  if (hours < 48) return `${Math.round(hours)} h ago`;
  const days = Math.round(hours / 24);
  if (days < 60) return `${days} days ago`;
  return `${Math.round(days / 30)} months ago`;
}

export function isStale(iso: string | null, maxAgeDays: number): boolean {
  if (!iso) return true;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return true;
  return (Date.now() - then) / 86_400_000 > maxAgeDays;
}
