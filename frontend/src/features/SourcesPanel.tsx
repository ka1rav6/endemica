import type { DataSource, GravityModel, IngestionRun } from '@/types/api';
import { formatCount, formatDateTime, relativeAge } from '@/lib/format';
import { ValueTypeLegend } from '@/components/ValueTypeBadge';

interface Props {
  sources: DataSource[];
  gravity: GravityModel | null;
  runs: IngestionRun[];
}

export function SourcesPanel({ sources, gravity, runs }: Props) {
  return (
    <>
      <div className="sec">
        <h2 className="sec__title">What each label means</h2>
        <ValueTypeLegend />
        <p className="metric__basis" style={{ marginTop: 8 }}>
          Labels are also distinguished by shape, not colour alone.
        </p>
      </div>

      {gravity && (
        <div className="sec">
          <h2 className="sec__title">Passenger-flow model</h2>
          <p style={{ margin: '0 0 8px', fontSize: 12, color: 'var(--text-muted)' }}>
            Fitted {relativeAge(gravity.fitted_at)} on {gravity.training_source}
            {gravity.training_period ? ` (${gravity.training_period})` : ''}.
          </p>
          <code
            style={{
              display: 'block',
              fontSize: 11,
              color: 'var(--text-faint)',
              background: 'var(--bg-sunken)',
              padding: '6px 8px',
              borderRadius: 5,
              overflowWrap: 'anywhere',
              marginBottom: 8,
            }}
          >
            {gravity.specification}
          </code>
          <table className="table">
            <tbody>
              <tr>
                <th>Training / held-out rows</th>
                <td>
                  {formatCount(gravity.n_train)} / {formatCount(gravity.n_test)}
                </td>
              </tr>
              <tr>
                <th>R² on log scale (held out)</th>
                <td>{(gravity.metrics['r2_log'] ?? 0).toFixed(3)}</td>
              </tr>
              <tr>
                <th>Median ratio error</th>
                <td>×{(gravity.metrics['median_ratio_error'] ?? 0).toFixed(2)}</td>
              </tr>
              <tr>
                <th>Within a factor of 2</th>
                <td>{((gravity.metrics['within_factor_2'] ?? 0) * 100).toFixed(0)}%</td>
              </tr>
              <tr>
                <th>Within a factor of 5</th>
                <td>{((gravity.metrics['within_factor_5'] ?? 0) * 100).toFixed(0)}%</td>
              </tr>
              <tr>
                <th>Band factor from residuals</th>
                <td>×{gravity.uncertainty_factor.toFixed(1)}</td>
              </tr>
            </tbody>
          </table>
          <p className="metric__basis" style={{ marginTop: 8 }}>
            {gravity.caveat}
          </p>
        </div>
      )}

      <div className="sec">
        <h2 className="sec__title">Data sources</h2>
        {sources.map((source) => (
          <details key={source.key} style={{ marginBottom: 8 }}>
            <summary style={{ cursor: 'pointer', fontSize: 12.5 }}>
              {source.name}
              {source.retrieved_at && (
                <span style={{ color: 'var(--text-faint)' }}>
                  {' '}
                  · {relativeAge(source.retrieved_at)}
                </span>
              )}
            </summary>
            <div style={{ fontSize: 11.5, color: 'var(--text-muted)', padding: '6px 0 0 10px' }}>
              <p style={{ margin: '0 0 4px' }}>{source.coverage}</p>
              <p style={{ margin: '0 0 4px' }}>
                <strong>Licence:</strong> {source.licence}
              </p>
              {source.url && (
                <p style={{ margin: '0 0 4px' }}>
                  <a href={source.url} target="_blank" rel="noreferrer noopener">
                    {source.url}
                  </a>
                </p>
              )}
              <p style={{ margin: '4px 0 2px', color: 'var(--text-faint)' }}>Known limitations</p>
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {source.limitations.map((limitation) => (
                  <li key={limitation} style={{ marginBottom: 3 }}>
                    {limitation}
                  </li>
                ))}
              </ul>
              {source.notes && <p style={{ marginTop: 5 }}>{source.notes}</p>}
            </div>
          </details>
        ))}
      </div>

      {runs.length > 0 && (
        <div className="sec">
          <h2 className="sec__title">Ingestion history</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Started</th>
                <th>Mode</th>
                <th>Status</th>
                <th>Records</th>
                <th>Obs.</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>{formatDateTime(run.started_at)}</td>
                  <td>{run.mode}</td>
                  <td
                    style={{
                      color: run.status === 'succeeded' ? 'var(--ok)' : 'var(--important)',
                    }}
                  >
                    {run.status}
                  </td>
                  <td>
                    {run.records_created}+{run.records_updated}
                  </td>
                  <td>{run.observations_created}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
