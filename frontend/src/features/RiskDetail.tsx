import type { RiskResponse } from '@/types/api';
import { ValueTypeBadge } from '@/components/ValueTypeBadge';

/**
 * The audit trail behind the risk numbers.
 *
 * It sits under the scenario controls rather than in the risk panel: the risk
 * panel answers the three questions, and anyone who wants to know which
 * origins were dropped, what the thresholds were or where a parameter came
 * from is already looking at the assumptions.
 */
export function RiskDetail({ risk }: { risk: RiskResponse | null }) {
  if (!risk) return null;
  const { importation, pathogen } = risk;

  return (
    <>
      {risk.scenario_markers.length > 0 && (
        <div className="sec">
          <div className="sec__head">
            <h2 className="sec__title">Scenario thresholds</h2>
            <ValueTypeBadge valueType="scenario" />
          </div>
          {risk.scenario_markers.map((marker) => (
            <div key={marker.key} style={{ marginBottom: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontSize: 12.5 }}>{marker.label}</span>
                <strong style={{ color: 'var(--scenario)', fontVariantNumeric: 'tabular-nums' }}>
                  {marker.day_offset === null
                    ? 'not reached within a year'
                    : `day +${marker.day_offset}`}
                </strong>
              </div>
              <p className="metric__basis" style={{ marginTop: 2 }}>
                {marker.detail}
              </p>
            </div>
          ))}
        </div>
      )}

      <div className="sec">
        <h2 className="sec__title">Assumptions behind these numbers</h2>
        <div>
          {risk.assumptions.map((assumption) => (
            <div className="assumption" key={assumption.key}>
              <span>{assumption.label}</span>
              <span className="assumption__value">
                {String(assumption.value)}
                {assumption.unit ? ` ${assumption.unit}` : ''}
              </span>
              <span className="assumption__source">
                from {assumption.source}
                {assumption.note ? ` — ${assumption.note}` : ''}
              </span>
            </div>
          ))}
        </div>
      </div>

      {importation.excluded_origins.length > 0 && (
        <div className="sec">
          <h2 className="sec__title">Origins that could not be used</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Origin</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {importation.excluded_origins.map((entry, index) => (
                <tr key={`${entry['origin_iso3'] ?? index}`}>
                  <td>{entry['origin_iso3'] ?? '—'}</td>
                  <td style={{ color: 'var(--text-muted)' }}>{entry['reason'] ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pathogen.references.length > 0 && (
        <div className="sec">
          <h2 className="sec__title">Parameter references</h2>
          <ul className="list" style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>
            {pathogen.references.map((reference) => (
              <li key={reference} style={{ marginBottom: 5 }}>
                {reference}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="footnote">
        Computed with {risk.model_version} over a {risk.horizon_days}-day horizon. {risk.disclaimer}
      </p>
    </>
  );
}
