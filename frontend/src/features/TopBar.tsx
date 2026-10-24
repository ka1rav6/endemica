import { useMemo, useState } from 'react';
import type { Country, HealthResponse } from '@/types/api';

interface Props {
  countries: Country[];
  selectedIso3: string | null;
  onSelect: (iso3: string) => void;
  health: HealthResponse | null;
  showFlows: boolean;
  onToggleFlows: () => void;
  onIngest: () => void;
  ingesting: boolean;
}

export function TopBar({
  countries,
  selectedIso3,
  onSelect,
  health,
  showFlows,
  onToggleFlows,
  onIngest,
  ingesting,
}: Props) {
  const [query, setQuery] = useState('');
  const database = health?.components.find((component) => component.name === 'database');
  const tinyfish = health?.components.find((component) => component.name === 'tinyfish');

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return [];
    return countries
      .filter(
        (country) =>
          country.name.toLowerCase().includes(needle) ||
          country.iso3.toLowerCase().startsWith(needle),
      )
      .slice(0, 8);
  }, [countries, query]);

  const selectedName = countries.find((country) => country.iso3 === selectedIso3)?.name ?? '';

  return (
    <header className="head">
      <button
        type="button"
        className="brand"
        title="Reload Endemica"
        onClick={() => {
          window.location.reload();
        }}
      >
        <span className="brand__mark" aria-hidden="true">
          E
        </span>
        <span className="brand__name">Endemica</span>
        <span className="brand__tag">Outbreak atlas</span>
      </button>

      <div className="head__group">
        <div style={{ position: 'relative' }}>
          <label className="field" style={{ width: 188 }}>
            <span className="field__icon" aria-hidden="true">
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                <circle cx="6.8" cy="6.8" r="4.6" stroke="currentColor" strokeWidth="1.6" />
                <path d="M10.4 10.4 14 14" stroke="currentColor" strokeWidth="1.6" />
              </svg>
            </span>
            <input
              className="field__input"
              type="search"
              placeholder={selectedName || 'Find a country'}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
              }}
              aria-label="Find a country"
            />
          </label>
          {matches.length > 0 && (
            <ul className="typeahead">
              {matches.map((country) => (
                <li key={country.iso3}>
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(country.iso3);
                      setQuery('');
                    }}
                  >
                    <span>{country.name}</span>
                    {(country.diseases?.length ?? 0) > 0 && (
                      <span className="typeahead__meta num">
                        {country.diseases?.length} on record
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <span className="head__spacer" />

      <button
        type="button"
        className="btn"
        aria-pressed={showFlows}
        onClick={onToggleFlows}
        title="Draw the passenger-flow corridors that feed the importation estimate"
        style={showFlows ? { borderColor: 'var(--accent-dim)', color: 'var(--accent)' } : undefined}
      >
        Flight corridors
      </button>

      {health && (
        <div className="health">
          <span className="health__item" title={database?.detail ?? ''}>
            <span className={`health__led health__led--${database?.status ?? 'unavailable'}`} />
            database {database?.status ?? 'unknown'}
          </span>
          <span className="health__item" title={tinyfish?.detail ?? ''}>
            <span className={`health__led health__led--${tinyfish?.status ?? 'unavailable'}`} />
            TinyFish {tinyfish?.status === 'ok' ? 'configured' : 'not configured'}
          </span>
        </div>
      )}

      <button type="button" className="btn" onClick={onIngest} disabled={ingesting}>
        {ingesting ? <span className="spinner" /> : null}
        {ingesting ? 'Refreshing…' : 'Refresh reports'}
      </button>
    </header>
  );
}
