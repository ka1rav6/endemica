import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MetricCard } from '@/components/MetricCard';
import type { BandedQuantity } from '@/types/api';

function band(overrides: Partial<BandedQuantity> = {}): BandedQuantity {
  return {
    low: 0.1,
    central: 0.25,
    high: 0.6,
    value_type: 'modelled',
    unit: 'probability',
    band_basis: 'scenario range: under-reporting 2x-10x. Not a confidence interval.',
    unavailable_reason: null,
    note: null,
    ...overrides,
  };
}

describe('MetricCard', () => {
  it('shows the central value and the range', () => {
    render(<MetricCard question="Will it arrive?" band={band()} />);
    expect(screen.getByText('25.0%')).toBeInTheDocument();
    expect(screen.getByText(/10\.0% – 60\.0%/)).toBeInTheDocument();
  });

  it('labels the value type', () => {
    render(<MetricCard question="Will it arrive?" band={band()} />);
    expect(screen.getByText('Modelled')).toBeInTheDocument();
  });

  it('states that the band is a scenario range, not a confidence interval', () => {
    render(<MetricCard question="Will it arrive?" band={band()} />);
    expect(screen.getByText(/Not a confidence interval/)).toBeInTheDocument();
  });

  it('renders "not estimable" with its reason instead of a number', () => {
    render(
      <MetricCard
        question="Will it arrive?"
        testId="metric"
        band={band({
          low: null,
          central: null,
          high: null,
          value_type: 'unknown',
          unavailable_reason: 'no_passenger_data',
          band_basis: null,
        })}
      />,
    );
    const value = screen.getByTestId('metric-unknown');
    expect(value).toHaveTextContent('Not estimable');
    expect(value).toHaveTextContent('no passenger-flow data');
  });

  it('never renders a missing value as a percentage', () => {
    const { container } = render(
      <MetricCard
        question="Will it arrive?"
        band={band({
          low: null,
          central: null,
          high: null,
          value_type: 'unknown',
          unavailable_reason: 'no_prevalence_data',
          band_basis: null,
        })}
      />,
    );
    expect(container.textContent).not.toMatch(/\d+\.\d%/);
  });

  it('renders zero as a real result, not as missing', () => {
    render(<MetricCard question="Will it establish?" band={band({ low: 0, central: 0, high: 0 })} />);
    expect(screen.getByText('0.0%')).toBeInTheDocument();
    expect(screen.queryByText(/Not estimable/)).not.toBeInTheDocument();
  });

  it('shows a saturation marker rather than an exact 100%', () => {
    render(
      <MetricCard
        question="Will it arrive?"
        band={band({ low: 0.99, central: 1, high: 1 })}
        saturated
      />,
    );
    expect(screen.getByText('> 99.99%')).toBeInTheDocument();
  });

  it('exposes the range to assistive technology', () => {
    render(<MetricCard question="Will it arrive?" band={band()} />);
    expect(screen.getByRole('img', { name: /Scenario range from 10\.0% to 60\.0%/ })).toBeInTheDocument();
  });

  it('renders the question as a heading', () => {
    render(<MetricCard question="Will it arrive?" band={band()} />);
    expect(screen.getByRole('heading', { name: 'Will it arrive?' })).toBeInTheDocument();
  });
});
