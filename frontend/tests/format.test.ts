import { describe, expect, it } from 'vitest';
import {
  formatBand,
  formatCount,
  formatPercent,
  formatRate,
  isStale,
  relativeAge,
  unavailableText,
} from '@/lib/format';
import type { BandedQuantity } from '@/types/api';

describe('formatPercent', () => {
  it('renders a dash for a missing value rather than zero', () => {
    expect(formatPercent(null)).toBe('—');
  });

  it('never renders a missing value as 0%', () => {
    expect(formatPercent(null)).not.toContain('0');
  });

  it('renders zero as 0.0%, because zero is a real result', () => {
    expect(formatPercent(0)).toBe('0.0%');
  });

  it('avoids false precision for very small probabilities', () => {
    expect(formatPercent(0.0000004)).toBe('< 0.1%');
  });

  it('avoids claiming exactly 100%', () => {
    expect(formatPercent(1)).toBe('> 99.99%');
    expect(formatPercent(0.99999)).toBe('> 99.99%');
  });

  it('rounds to the requested precision', () => {
    expect(formatPercent(0.12345, 1)).toBe('12.3%');
    expect(formatPercent(0.12345, 2)).toBe('12.35%');
  });

  it('handles non-finite input', () => {
    expect(formatPercent(Number.NaN)).toBe('—');
    expect(formatPercent(Number.POSITIVE_INFINITY)).toBe('—');
  });
});

describe('formatBand', () => {
  const band = (low: number | null, high: number | null): BandedQuantity => ({
    low,
    central: null,
    high,
    value_type: 'modelled',
    unit: null,
    band_basis: null,
    unavailable_reason: null,
    note: null,
  });

  it('renders a range', () => {
    expect(formatBand(band(0.1, 0.4))).toBe('10.0% – 40.0%');
  });

  it('renders a dash when either end is missing', () => {
    expect(formatBand(band(null, 0.4))).toBe('—');
    expect(formatBand(band(0.1, null))).toBe('—');
  });
});

describe('formatRate', () => {
  it('uses scientific notation for very small rates', () => {
    expect(formatRate(0.0000123)).toContain('e-');
  });

  it('renders zero plainly', () => {
    expect(formatRate(0)).toBe('0');
  });

  it('renders a dash for a missing rate', () => {
    expect(formatRate(null)).toBe('—');
  });
});

describe('formatCount', () => {
  it('distinguishes zero from missing', () => {
    expect(formatCount(0)).toBe('0');
    expect(formatCount(null)).toBe('—');
    expect(formatCount(undefined)).toBe('—');
  });

  it('groups thousands', () => {
    expect(formatCount(1234567)).toMatch(/1.234.567/);
  });
});

describe('unavailableText', () => {
  it('maps known reasons to plain language', () => {
    expect(unavailableText('no_passenger_data')).toBe('no passenger-flow data');
    expect(unavailableText('model_not_applicable')).toContain('does not apply');
  });

  it('falls back readably for an unknown reason', () => {
    expect(unavailableText('some_new_reason')).toBe('some new reason');
  });

  it('handles a null reason', () => {
    expect(unavailableText(null)).toBe('not estimable');
  });
});

describe('relativeAge and isStale', () => {
  it('describes a recent timestamp', () => {
    expect(relativeAge(new Date().toISOString())).toContain('less than an hour');
  });

  it('describes days for older timestamps', () => {
    const old = new Date(Date.now() - 5 * 86_400_000).toISOString();
    expect(relativeAge(old)).toBe('5 days ago');
  });

  it('treats a missing timestamp as stale', () => {
    expect(isStale(null, 7)).toBe(true);
    expect(relativeAge(null)).toBe('age unknown');
  });

  it('detects staleness against the threshold', () => {
    const recent = new Date(Date.now() - 2 * 86_400_000).toISOString();
    const old = new Date(Date.now() - 30 * 86_400_000).toISOString();
    expect(isStale(recent, 7)).toBe(false);
    expect(isStale(old, 7)).toBe(true);
  });

  it('treats an unparseable timestamp as stale rather than throwing', () => {
    expect(isStale('not a date', 7)).toBe(true);
  });
});
