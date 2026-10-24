import type { Country, HealthResponse } from '@/types/api';

interface Props {
  countries: Country[];
  selectedIso3: string | null;
  onSelect: (iso3: string) => void;
  health: HealthResponse | null;
  onIngest: () => void;
  ingesting: boolean;
}

export function TopBar({ countries, selectedIso3, onSelect, health, onIngest, ingesting }: Props) {
  const tinyfish = health?.components.find((component) => component.name === 'tinyfish');
  const database = health?.components.find((component) => component.name === 'database');

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <h1 className="topbar__title">EpiRoute</h1>
        <span className="topbar__tagline">
          sourced outbreaks · air-travel connectivity · separated risks
        </span>
      </div>

      <div className="topbar__spacer" />

      <div className="topbar__controls">
        <div className="field">
          <label className="field__label" htmlFor="destination-select">
            Destination
          </label>
          <select
            id="destination-select"
            value={selectedIso3 ?? ''}
            onChange={(event) => {
              onSelect(event.target.value);
            }}
          >
            <option value="" disabled>
              Choose a destination
            </option>
            {countries.map((country) => (
              <option key={country.iso3} value={country.iso3}>
                {country.name}
                {country.has_reported_outbreak ? ' — cases reported' : ''}
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          className="button button--primary"
          onClick={onIngest}
          disabled={ingesting}
          title="Fetch the latest WHO Disease Outbreak News and run the validation gate"
        >
          {ingesting ? 'Ingesting…' : 'Run ingest'}
        </button>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 11 }}>
          <span style={{ color: database?.status === 'ok' ? 'var(--ok)' : 'var(--outbreak)' }}>
            ● database {database?.status ?? 'unknown'}
          </span>
          <span
            style={{ color: tinyfish?.status === 'ok' ? 'var(--ok)' : 'var(--text-faint)' }}
            title={tinyfish?.detail ?? undefined}
          >
            ● TinyFish {tinyfish?.status === 'ok' ? 'configured' : 'not configured'}
          </span>
        </div>
      </div>
    </header>
  );
}
