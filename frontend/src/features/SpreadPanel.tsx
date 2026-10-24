import type { DiseaseSpread } from '@/types/api';
import { formatCount, formatDate } from '@/lib/format';

interface Props {
  spread: DiseaseSpread | null;
  loading: boolean;
  yearCeiling: number | null;
  selectedIso3: string | null;
  onSelectCountry: (iso3: string) => void;
}

export function SpreadPanel({
  spread,
  loading,
  yearCeiling,
  selectedIso3,
  onSelectCountry,
}: Props) {
  if (loading && !spread) {
    return (
      <div className="sec" style={{ display: 'flex', gap: 9, alignItems: 'center' }}>
        <span className="spinner" />
        <span style={{ color: 'var(--ink-3)' }}>Reading the archive…</span>
      </div>
    );
  }

  if (!spread) {
    return <p className="empty">Pick a disease to trace how it spread.</p>;
  }

  const visible = spread.countries.filter((country) => {
    if (yearCeiling === null) return true;
    const year = country.first_published_at ? Number(country.first_published_at.slice(0, 4)) : null;
    return year === null || year <= yearCeiling;
  });
  const worst = Math.max(...visible.map((country) => country.cases_confirmed ?? 0), 1);
  const hidden = spread.countries.length - visible.length;

  return (
    <>
      <div className="sec">
        <div className="stats">
          <div className="stat">
            <span className="stat__label">Countries reached</span>
            <span className="stat__value stat__value--accent num">{spread.country_count}</span>
            <span className="stat__note">across the whole archive</span>
          </div>
          <div className="stat">
            <span className="stat__label">Reports</span>
            <span className="stat__value num">{formatCount(spread.report_count)}</span>
            <span className="stat__note">
              {spread.first_published_at?.slice(0, 4)}–{spread.last_published_at?.slice(0, 4)}
            </span>
          </div>
          <div className="stat">
            <span className="stat__label">Cases</span>
            <span className="stat__value num">{formatCount(spread.cases_confirmed)}</span>
            <span className="stat__note">sum of per-country peaks</span>
          </div>
          <div className="stat">
            <span className="stat__label">Deaths</span>
            <span className="stat__value stat__value--hot num">{formatCount(spread.deaths)}</span>
            <span className="stat__note">as reported</span>
          </div>
        </div>
      </div>

      <div className="sec">
        <div className="sec__head">
          <h3 className="sec__title">Order of arrival</h3>
          {hidden > 0 && <span className="chip chip--past num">{hidden} later, hidden</span>}
        </div>
        {visible.length === 0 ? (
          <p className="empty" style={{ padding: '14px 0' }}>
            This disease had not been reported anywhere by {yearCeiling}.
          </p>
        ) : (
          <ul className="list">
            {visible.map((country) => (
              <li key={country.country_iso3}>
                <button
                  type="button"
                  className="row"
                  aria-current={country.country_iso3 === selectedIso3}
                  onClick={() => {
                    onSelectCountry(country.country_iso3);
                  }}
                >
                  <span className="row__top">
                    <span className="row__rank num">{country.arrival_order}</span>
                    <span className="row__name">{country.country_name}</span>
                    <span className="row__aside">
                      {country.first_published_at?.slice(0, 4) ?? '—'}
                    </span>
                  </span>
                  <span className="row__bar" aria-hidden="true">
                    <i
                      style={{
                        width: `${Math.max(((country.cases_confirmed ?? 0) / worst) * 100, country.cases_confirmed ? 2 : 0)}%`,
                      }}
                    />
                  </span>
                  <span className="row__aside" style={{ fontSize: 10.5, color: 'var(--ink-4)' }}>
                    {country.cases_confirmed === null
                      ? 'no grounded count'
                      : `${formatCount(country.cases_confirmed)} cases`}
                    {country.deaths === null ? '' : ` · ${formatCount(country.deaths)} deaths`}
                    {` · ${country.report_count} report${country.report_count === 1 ? '' : 's'}`}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {spread.timeline.length > 0 && (
        <div className="sec">
          <div className="sec__head">
            <h3 className="sec__title">Year by year</h3>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>Year</th>
                <th style={{ textAlign: 'right' }}>Reports</th>
                <th style={{ textAlign: 'right' }}>New</th>
                <th style={{ textAlign: 'right' }}>Total</th>
                <th style={{ textAlign: 'right' }}>Cases</th>
              </tr>
            </thead>
            <tbody>
              {[...spread.timeline].reverse().map((point) => (
                <tr
                  key={point.year}
                  style={
                    yearCeiling !== null && point.year === yearCeiling
                      ? { background: 'var(--surface-2)' }
                      : undefined
                  }
                >
                  <td className="num" style={{ fontWeight: 600 }}>
                    {point.year}
                  </td>
                  <td className="num" style={{ textAlign: 'right' }}>
                    {point.report_count}
                  </td>
                  <td
                    className="num"
                    style={{
                      textAlign: 'right',
                      color: point.new_country_count > 0 ? 'var(--hot)' : 'var(--ink-4)',
                    }}
                  >
                    {point.new_country_count || '—'}
                  </td>
                  <td className="num" style={{ textAlign: 'right', color: 'var(--ink-3)' }}>
                    {point.cumulative_country_count}
                  </td>
                  <td className="num" style={{ textAlign: 'right' }}>
                    {formatCount(point.cases_confirmed)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="sec">
        <div className="sec__head">
          <h3 className="sec__title">Most recent report</h3>
        </div>
        {spread.countries.length > 0 ? (
          <p className="metric__detail" style={{ marginTop: 0 }}>
            Last published {formatDate(spread.last_published_at)}
            {spread.is_active ? ', which is inside the active window.' : '.'}{' '}
            {spread.pathogen_key === null && (
              <>
                This disease has no mapped parameter profile, so importation and establishment
                estimates for it fall back to generic respiratory assumptions.
              </>
            )}
          </p>
        ) : (
          <p className="empty">No country could be attributed to this disease.</p>
        )}
      </div>

      <p className="footnote">{spread.note}</p>
    </>
  );
}
