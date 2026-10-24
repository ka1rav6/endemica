import { Fragment, useMemo, useState, type ReactElement } from 'react';
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
      <p className="cmp__hint">Or shift-click a second country on the map.</p>
    </div>
  );
}

function Cell({ value, note }: { value: string; note: string }) {
  return (
    <dd className="cmp__cell">
      {value}
      <small>{note}</small>
    </dd>
  );
}

function Head({ side, variant }: { side: Side; variant: 'a' | 'b' }) {
  const { profile, risk } = side;
  return (
    <div className="cmp__head">
      <span className="cmp__name">
        <span
          className="dot"
          style={{ color: variant === 'a' ? 'var(--accent)' : 'var(--modelled)' }}
          aria-hidden="true"
        />
        {profile?.name ?? '—'}
      </span>
      <span className="cmp__disease">
        {risk?.pathogen.disease_name ?? risk?.pathogen.label ?? 'no disease resolved'}
      </span>
    </div>
  );
}

/**
 * One row per question, both countries on it.
 *
 * Each side used to be its own stack of boxes, so the rows only lined up when
 * the two notes happened to wrap the same way. A shared grid keeps every
 * answer on the line of the question it answers.
 */
const ROWS: { key: string; label: (side: Side) => string; cell: (side: Side) => ReactElement }[] = [
  {
    key: 'presence',
    label: () => 'Already here',
    cell: (side) => {
      const presence = side.risk?.presence;
      if (presence?.status === 'reported') {
        return (
          <Cell
            value="Yes"
            note={`${formatCount(presence.cases_confirmed?.value ?? null)} cases · ${formatCount(
              presence.deaths?.value ?? null,
            )} deaths`}
          />
        );
      }
      return <Cell value="No" note="no grounded report for this disease" />;
    },
  },
  {
    key: 'importation',
    label: (side) => `Arrival within ${side.risk?.horizon_days ?? 28} days`,
    cell: (side) => {
      const band = side.risk?.importation.probability;
      if (band?.central == null) {
        return <Cell value="—" note={unavailableText(band?.unavailable_reason ?? null)} />;
      }
      return (
        <Cell
          value={formatPercent(band.central)}
          note={`range ${formatPercent(band.low)} – ${formatPercent(band.high)}`}
        />
      );
    },
  },
  {
    key: 'establishment',
    label: () => 'Local transmission',
    cell: (side) => {
      const band = side.risk?.establishment.probability_within_horizon;
      if (band?.central == null) {
        return <Cell value="—" note={unavailableText(band?.unavailable_reason ?? null)} />;
      }
      return (
        <Cell
          value={formatPercent(band.central)}
          note={`range ${formatPercent(band.low)} – ${formatPercent(band.high)}`}
        />
      );
    },
  },
  {
    key: 'record',
    label: () => 'Diseases on record',
    cell: (side) => {
      const profile = side.profile;
      if (!profile) return <Cell value="—" note="no record loaded" />;
      return (
        <Cell
          value={String(profile.diseases.length)}
          note={`${profile.active_disease_count} active · ${formatCount(profile.report_count)} reports`}
        />
      );
    },
  },
];

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
          <dl className="cmp">
            <Head side={a} variant="a" />
            <Head side={b} variant="b" />
            {ROWS.map((row) => (
              <Fragment key={row.key}>
                <dt className="cmp__label">{row.label(a)}</dt>
                {row.cell(a)}
                {row.cell(b)}
              </Fragment>
            ))}
          </dl>
        ) : (
          <>
            <dl className="cmp cmp--single">
              <Head side={a} variant="a" />
              {ROWS.map((row) => (
                <Fragment key={row.key}>
                  <dt className="cmp__label">{row.label(a)}</dt>
                  {row.cell(a)}
                </Fragment>
              ))}
            </dl>
            <CountryPicker countries={countries} exclude={a.profile.iso3} onPick={onPick} />
          </>
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
