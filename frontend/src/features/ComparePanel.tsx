import { useMemo, useState } from 'react';
import type { Country, CountryProfile, RiskResponse } from '@/types/api';
import { formatCount, formatPercent, unavailableText } from '@/lib/format';

interface Side {
  profile: CountryProfile | null;
  risk: RiskResponse | null;
}

interface Props {
  a: Side;
  b: Side;
  countries: Country[];
  onPick: (iso3: string) => void;
  onClear: () => void;
}

/** Search-and-pick for the second country, so comparing needs no shortcut. */
function CountryPicker({
  countries,
  exclude,
  onPick,
}: {
  countries: Country[];
  exclude: string | null;
  onPick: (iso3: string) => void;
}) {
  const [query, setQuery] = useState('');
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const pool = countries.filter((country) => country.iso3 !== exclude);
    if (!needle) {
      // Suggest the countries with the richest record first, but never show an
      // empty picker just because none of them has a report yet.
      const ranked = [...pool].sort(
        (x, y) => (y.diseases?.length ?? 0) - (x.diseases?.length ?? 0),
      );
      return ranked.slice(0, 6);
    }
    return pool
      .filter(
        (country) =>
          country.name.toLowerCase().includes(needle) ||
          country.iso3.toLowerCase().startsWith(needle),
      )
      .slice(0, 6);
  }, [countries, exclude, query]);

  return (
    <div className="cmp__slot">
      <label className="field" style={{ width: '100%' }}>
        <span className="field__icon" aria-hidden="true">
          <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
            <circle cx="6.8" cy="6.8" r="4.6" stroke="currentColor" strokeWidth="1.6" />
            <path d="M10.4 10.4 14 14" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </span>
        <input
          className="field__input"
          type="search"
          placeholder="Compare with…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
          aria-label="Choose a second country to compare"
        />
      </label>
      <ul className="cmp__options">
        {matches.map((country) => (
          <li key={country.iso3}>
            <button
              type="button"
              onClick={() => {
                onPick(country.iso3);
                setQuery('');
              }}
            >
              <span>{country.name}</span>
              <span className="typeahead__meta num">{country.diseases?.length ?? 0}</span>
            </button>
          </li>
        ))}
        {matches.length === 0 && <li className="cmp__none">No country matches.</li>}
      </ul>
    </div>
  );
}

function Column({ side, variant }: { side: Side; variant: 'a' | 'b' }) {
  const { profile, risk } = side;
  if (!profile) return null;
  const importation = risk?.importation.probability;
  const establishment = risk?.establishment.probability_within_horizon;
  const presence = risk?.presence;

  return (
    <div className={variant === 'b' ? 'cmp__col cmp__col--b' : 'cmp__col'}>
      <span className="cmp__name">
        <span
          className="dot"
          style={{ color: variant === 'a' ? 'var(--accent)' : 'var(--modelled)' }}
          aria-hidden="true"
        />
        {profile.name}
      </span>
      <span className="cmp__disease">
        {risk?.pathogen.disease_name ?? risk?.pathogen.label ?? 'no disease resolved'}
      </span>

      <div className="cmp__metric">
        <dt>Already here</dt>
        <dd>
          {presence?.status === 'reported' ? (
            <>
              Yes
              <small>
                latest reports: {formatCount(presence.cases_confirmed?.value ?? null)} cases ·{' '}
                {formatCount(presence.deaths?.value ?? null)} deaths
              </small>
            </>
          ) : (
            <>
              No
              <small>no grounded report for this disease</small>
            </>
          )}
        </dd>
      </div>

      <div className="cmp__metric">
        <dt>Arrival within {risk?.horizon_days ?? '—'} d</dt>
        <dd>
          {importation?.central == null ? (
            <>
              —<small>{unavailableText(importation?.unavailable_reason ?? null)}</small>
            </>
          ) : (
            <>
              {formatPercent(importation.central)}
              <small>
                range {formatPercent(importation.low)} – {formatPercent(importation.high)}
              </small>
            </>
          )}
        </dd>
      </div>

      <div className="cmp__metric">
        <dt>Local transmission</dt>
        <dd>
          {establishment?.central == null ? (
            <>
              —<small>{unavailableText(establishment?.unavailable_reason ?? null)}</small>
            </>
          ) : (
            <>
              {formatPercent(establishment.central)}
              <small>
                range {formatPercent(establishment.low)} – {formatPercent(establishment.high)}
              </small>
            </>
          )}
        </dd>
      </div>

      <div className="cmp__metric">
        <dt>Diseases on record</dt>
        <dd>
          {profile.diseases.length}
          <small>
            {profile.active_disease_count} active · {formatCount(profile.report_count)} reports
            since 1996
          </small>
        </dd>
      </div>
    </div>
  );
}

export function ComparePanel({ a, b, countries, onPick, onClear }: Props) {
  if (!a.profile) {
    return <p className="empty">Select a country first, then add a second one to compare.</p>;
  }

  const sameDisease =
    a.risk?.pathogen.disease_key != null &&
    a.risk.pathogen.disease_key === b.risk?.pathogen.disease_key;

  return (
    <>
      <div className="sec">
        <div className="sec__head">
          <h3 className="sec__title">Side by side</h3>
          {b.profile && (
            <button type="button" className="btn btn--sm btn--ghost" onClick={onClear}>
              Clear
            </button>
          )}
        </div>

        {b.profile ? (
          <div className="cmp">
            <Column side={a} variant="a" />
            <Column side={b} variant="b" />
          </div>
        ) : (
          <div className="cmp">
            <Column side={a} variant="a" />
            <CountryPicker countries={countries} exclude={a.profile.iso3} onPick={onPick} />
          </div>
        )}
      </div>

      {b.profile && (
        <div className="sec">
          <div className="warn warn--info">
            {sameDisease ? (
              <span>
                Both columns answer about <strong>{a.risk?.pathogen.disease_name}</strong>, so the
                probabilities are directly comparable.
              </span>
            ) : (
              <span>
                Each column answers about the disease that country actually reports
                {a.risk?.pathogen.disease_name && b.risk?.pathogen.disease_name ? (
                  <>
                    {' '}
                    — <strong>{a.risk.pathogen.disease_name}</strong> versus{' '}
                    <strong>{b.risk.pathogen.disease_name}</strong>
                  </>
                ) : null}
                . Different diseases have different parameters, so treat the numbers as two separate
                answers rather than a ranking. Pick one disease in the left rail to put both
                countries on the same question.
              </span>
            )}
          </div>
        </div>
      )}
    </>
  );
}
