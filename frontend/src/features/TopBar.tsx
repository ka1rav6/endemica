import type { Country, DiseaseOption, HealthResponse } from '@/types/api';

interface Props {
  countries: Country[];
  selectedIso3: string | null;
  onSelect: (iso3: string) => void;
  diseases: DiseaseOption[];
  selectedDisease: string | null;
  onDisease: (disease: DiseaseOption | null) => void;
  health: HealthResponse | null;
  onIngest: () => void;
  ingesting: boolean;
}

function hasDisease(country: Country, disease: string | null): boolean {
  if (!disease) return false;
  const needle = disease.toLowerCase();
  return (country.diseases ?? []).some((name) => name.toLowerCase() === needle);
}

export function TopBar({
  countries,
  selectedIso3,
  onSelect,
  diseases,
  selectedDisease,
  onDisease,
  health,
  onIngest,
  ingesting,
}: Props) {
  const tinyfish = health?.components.find((component) => component.name === 'tinyfish');
  const database = health?.components.find((component) => component.name === 'database');

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <span className="mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" width="22" height="22">
            <circle cx="16" cy="16" r="13" fill="none" stroke="currentColor" strokeWidth="1.4" />
            <path
              d="M5 19c4.2-7 7.2-1.5 11.2-8.2C19.6 6.2 23 8 27 13"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
            <circle cx="23.2" cy="10.2" r="2.1" fill="currentColor" />
          </svg>
        </span>
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
