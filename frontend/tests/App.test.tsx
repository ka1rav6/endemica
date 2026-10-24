import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as fixtures from './fixtures';

vi.mock('@/features/WorldMap', () => ({
  WorldMap: ({ selectedIso3 }: { selectedIso3: string | null }) => (
    <div data-testid="world-map">map: {selectedIso3 ?? 'none'}</div>
  ),
}));

const risk = vi.hoisted(() => ({ current: null as unknown }));

vi.mock('@/services/epiroute', () => ({
  getHealth: vi.fn(() => Promise.resolve(fixturesRef.health)),
  getCountries: vi.fn(() => Promise.resolve({ total: 2, items: fixturesRef.countries })),
  getDiseaseHistory: vi.fn(() => Promise.resolve(fixturesRef.diseaseHistory)),
  getDiseaseSpread: vi.fn(() => Promise.resolve(fixturesRef.diseaseSpread)),
  getCountryProfile: vi.fn((iso3: string) => Promise.resolve(fixturesRef.countryProfile(iso3))),
  getOutbreaks: vi.fn(() => Promise.resolve(fixturesRef.outbreaks)),
  getOutbreak: vi.fn(() =>
    Promise.resolve({
      ...fixturesRef.outbreaks.items[0]!,
      narrative_text: 'Narrative text.',
      validation_warnings: [],
      grounding_fields: [
        {
          field: 'cases_suspected',
          value: 9291,
          verdict: 'not_in_source',
          detail: 'the number does not appear anywhere in the retrieved source text',
          context: null,
        },
      ],
    }),
  ),
  getPathogens: vi.fn(() => Promise.resolve(fixturesRef.pathogens)),
  getGravityModel: vi.fn(() =>
    Promise.resolve({
      fitted_at: new Date().toISOString(),
      specification: 'log10(passengers_per_day) = b0 + ...',
      training_source: 'Eurostat',
      training_period: '2019',
      n_train: 1507,
      n_test: 377,
      random_seed: 1,
      intercept: 1.44,
      coefficients: {},
      metrics: {
        r2_log: 0.71,
        median_ratio_error: 1.67,
        within_factor_2: 0.679,
        within_factor_5: 0.968,
      },
      residual_sigma_log10: 0.344,
      uncertainty_factor: 4.9,
      notes: null,
      caveat: 'These metrics say nothing about how well EpiRoute predicts outbreaks.',
    }),
  ),
  getRuns: vi.fn(() => Promise.resolve([])),
  getSources: vi.fn(() =>
    Promise.resolve({
      items: [
        {
          key: 'who_don',
          name: 'WHO Disease Outbreak News API',
          kind: 'outbreak_reports',
          url: 'https://www.who.int/api/news/diseaseoutbreaknews',
          coverage: 'Global, 1996 to present.',
          licence: 'WHO terms of use.',
          limitations: ['Counts are cumulative, not current prevalence.'],
          fields_used: ['DonId'],
          retrieved_at: new Date().toISOString(),
          record_count: 20,
          notes: null,
        },
      ],
    }),
  ),
  getRoutes: vi.fn(() => Promise.resolve(fixturesRef.routes)),
  getRisk: vi.fn((iso3: string) =>
    Promise.resolve(
      risk.current && typeof risk.current === 'object'
        ? { ...risk.current, destination_iso3: iso3 }
        : risk.current,
    ),
  ),
  triggerIngest: vi.fn(() =>
    Promise.resolve({
      run_id: 'run-2',
      mode: 'direct_fetch',
      status: 'succeeded',
      records_seen: 20,
      records_created: 3,
      records_updated: 17,
      records_skipped: 0,
      observations_created: 16,
      observations_unverified: 0,
      warning_codes: {},
      errors: [],
    }),
  ),
}));

const fixturesRef = fixtures;

const { default: App } = await import('@/App');

/** Render and open the Risk tab, which is no longer the landing panel. */
async function renderOnRiskTab() {
  render(<App />);
  await waitFor(() => {
    expect(screen.getByRole('tab', { name: 'Risk' })).toBeInTheDocument();
  });
  await userEvent.click(screen.getByRole('tab', { name: 'Risk' }));
  await waitFor(() => {
    expect(screen.getByTestId('presence-card')).toBeInTheDocument();
  });
}

describe('App', () => {
  beforeEach(() => {
    risk.current = fixtures.riskResponse();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('selects a country with a reported outbreak by default', async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('world-map')).toHaveTextContent('ZZO');
    });
  });

  it('shows the three risk quantities separately', async () => {
    await renderOnRiskTab();
    expect(screen.getByTestId('importation-card')).toBeInTheDocument();
    expect(screen.getByTestId('establishment-card')).toBeInTheDocument();
  });

  it('states that flight connectivity is not evidence of presence', async () => {
    await renderOnRiskTab();
    expect(screen.getByTestId('presence-card')).toHaveTextContent(
      /never used as evidence of presence/,
    );
  });

  it('shows importation and establishment as different numbers', async () => {
    await renderOnRiskTab();
    expect(screen.getByTestId('importation-card')).toHaveTextContent('18.0%');
    expect(screen.getByTestId('establishment-card')).toHaveTextContent('2.3%');
  });

  it('renders the health status for the database and TinyFish', async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/database ok/)).toBeInTheDocument();
    });
    expect(screen.getByText(/TinyFish not configured/)).toBeInTheDocument();
  });

  it('shows "not estimable" with a reason when inputs are missing', async () => {
    risk.current = fixtures.unavailableRisk();
    await renderOnRiskTab();
    expect(screen.getByTestId('importation-card-unknown')).toHaveTextContent(
      /no passenger-flow data/,
    );
  });

  it('lists the origins that could not be used, with reasons', async () => {
    risk.current = fixtures.unavailableRisk();
    await renderOnRiskTab();
    expect(screen.getByText(/Origins that could not be used/)).toBeInTheDocument();
    expect(screen.getByText(/no passenger flow to this destination/)).toBeInTheDocument();
  });

  it('shows the assumptions tab with each value attributed to its source', async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: 'Assumptions' })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('tab', { name: 'Assumptions' }));
    expect(screen.getByText(/changes a/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Time horizon/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Screening and border effectiveness/)).toBeInTheDocument();
  });

  it('disables R and k when establishment is not estimable', async () => {
    risk.current = fixtures.riskResponse({ pathogen: fixtures.pathogens[1]! });
    await renderOnRiskTab();
    await userEvent.click(screen.getByRole('tab', { name: 'Assumptions' }));
    expect(screen.getByLabelText(/Reproduction number/)).toBeDisabled();
    expect(screen.getByLabelText(/Cluster dispersion/)).toBeDisabled();
    expect(screen.getByText(/not estimable for this pathogen class/)).toBeInTheDocument();
  });

  it('shows the source report with its evidence sentence', async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: 'Reports' })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('tab', { name: 'Reports' }));
    const report = screen.getByRole('button', { name: /Test respiratory outbreak/ });
    await userEvent.click(report);
    await waitFor(() => {
      expect(
        screen.getByText(/A cumulative total of 2400 confirmed cases and 110 deaths/),
      ).toBeInTheDocument();
    });
  });

  it('shows rejected extractions so the gate is visible', async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: 'Reports' })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('tab', { name: 'Reports' }));
    await userEvent.click(screen.getByRole('button', { name: /Test respiratory outbreak/ }));
    await waitFor(() => {
      expect(screen.getByText(/rejected by the validation gate/)).toBeInTheDocument();
    });
    expect(
      screen.getByText(/does not appear anywhere in the retrieved source text/),
    ).toBeInTheDocument();
  });

  it('shows the model report with its caveat on the sources tab', async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: 'Sources' })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('tab', { name: 'Sources' }));
    await waitFor(() => {
      expect(screen.getByText(/Passenger-flow model/)).toBeInTheDocument();
    });
    expect(
      screen.getByText(/say nothing about how well EpiRoute predicts outbreaks/),
    ).toBeInTheDocument();
  });

  it('lists every source with its licence and limitations', async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole('tab', { name: 'Sources' })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('tab', { name: 'Sources' }));
    await waitFor(() => {
      expect(screen.getByText(/WHO Disease Outbreak News API/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Counts are cumulative, not current prevalence/)).toBeInTheDocument();
  });

  it('reports the outcome of an ingestion run', async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Refresh reports/ })).toBeEnabled();
    });
    await userEvent.click(screen.getByRole('button', { name: /Refresh reports/ }));
    await waitFor(() => {
      expect(screen.getByText(/3 new and 17 updated report/)).toBeInTheDocument();
    });
  });

  it('shows the disclaimer', async () => {
    await renderOnRiskTab();
    expect(screen.getByText(/not an official forecast/i)).toBeInTheDocument();
  });

  it('lets a destination be found by name', async () => {
    render(<App />);
    await waitFor(() => {
      expect(screen.getByLabelText('Find a country')).toBeInTheDocument();
    });
    await userEvent.type(screen.getByLabelText('Find a country'), 'Destination');
    await userEvent.click(screen.getByRole('button', { name: /Destination Land/ }));
    await waitFor(() => {
      expect(screen.getByTestId('world-map')).toHaveTextContent('ZZD');
    });
  });

  it('marks which passenger volumes are observed and which are modelled', async () => {
    await renderOnRiskTab();
    expect(screen.getByText(/Where the risk comes from/)).toBeInTheDocument();
    const origins = screen.getByText(/Where the risk comes from/).closest('div');
    expect(origins).not.toBeNull();
    expect(within(origins!).getByText('obs')).toBeInTheDocument();
  });

  it('labels scenario markers as scenarios, not predictions', async () => {
    await renderOnRiskTab();
    expect(screen.getByText(/Scenario thresholds/)).toBeInTheDocument();
    expect(screen.getByText(/not a safety date/)).toBeInTheDocument();
  });
});
