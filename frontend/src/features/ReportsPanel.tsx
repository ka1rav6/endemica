import { useEffect, useState } from 'react';
import type { Observation, OutbreakReport, OutbreakReportDetail } from '@/types/api';
import { getOutbreak } from '@/services/endemica';
import { formatCount, formatDate, relativeAge } from '@/lib/format';
import { ValueTypeBadge } from '@/components/ValueTypeBadge';
import { ErrorNotice } from '@/components/ErrorNotice';

const STATUS_LABEL: Record<string, string> = {
  verified: 'every number grounded in the source text',
  partial: 'some numbers grounded, others rejected',
  unverified: 'no number could be grounded',
  failed: 'extraction failed',
  not_attempted: 'from a structured source field',
};

/**
 * Only the figures this observation actually has.
 *
 * A report the validation gate could not ground has nothing in any of these
 * fields, and four columns of em dashes read as a broken layout rather than as
 * the honest "no number here" it is.
 */
function ObservationFigures({ observation }: { observation: Observation }) {
  const figures: [string, string][] = [
    ['Confirmed', formatCount(observation.cases_confirmed)],
    ['Suspected', formatCount(observation.cases_suspected)],
    ['Deaths', formatCount(observation.deaths)],
    ['Period', observation.period_text ?? '—'],
  ].filter((entry): entry is [string, string] => entry[1] !== '—');

  if (figures.length === 0) {
    return (
      <p className="metric__basis">No figure in this report could be matched to its source text.</p>
    );
  }
  return (
    <dl className="kv">
      {figures.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ReportDetail({ report }: { report: OutbreakReportDetail }) {
  const rejected = report.grounding_fields.filter((f) => f.verdict !== 'grounded');
  return (
    <div>
      {report.observations.length === 0 ? (
        <p className="empty">
          No grounded observation came out of this report. Its source link is kept so the report
          remains auditable, but it contributes nothing to any model.
        </p>
      ) : (
        report.observations.map((observation) => (
          <div key={observation.id} style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <strong style={{ fontSize: 12.5 }}>
                {observation.country_name}
                {observation.subnational_name ? ` · ${observation.subnational_name}` : ''}
              </strong>
              <ValueTypeBadge valueType={observation.value_type} />
              {!observation.usable_for_models && (
                <span style={{ fontSize: 11, color: 'var(--unknown)' }}>excluded from models</span>
              )}
            </div>
            <ObservationFigures observation={observation} />
            {observation.evidence_text && (
              <blockquote className="evidence">{observation.evidence_text}</blockquote>
            )}
          </div>
        ))
      )}

      {rejected.length > 0 && (
        <details className="fold" style={{ marginTop: 8 }}>
          <summary>
            {rejected.length} extracted value{rejected.length === 1 ? '' : 's'} rejected by the
            validation gate
          </summary>
          <table className="table" style={{ marginTop: 6 }}>
            <thead>
              <tr>
                <th>Field</th>
                <th>Value</th>
                <th>Why rejected</th>
              </tr>
            </thead>
            <tbody>
              {rejected.map((field, index) => (
                <tr key={`${field.field}-${field.value}-${index}`}>
                  <td>{field.field}</td>
                  <td>{formatCount(field.value)}</td>
                  <td style={{ color: 'var(--text-muted)' }}>{field.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <p className="metric__basis" style={{ marginTop: 8 }}>
        Retrieved {relativeAge(report.provenance.retrieved_at)} ·{' '}
        {report.provenance.extraction_method ?? 'unknown method'} ·{' '}
        {report.provenance.license_note ?? 'licence not recorded'}
      </p>
    </div>
  );
}

interface Props {
  reports: OutbreakReport[];
  onCountrySelect: (iso3: string) => void;
}

export function ReportsPanel({ reports, onCountrySelect }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<OutbreakReportDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!expandedId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setDetail(null);
    getOutbreak(expandedId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setDetail(value);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
    };
  }, [expandedId]);

  if (reports.length === 0) {
    return (
      <div className="sec">
        <p className="empty">
          No outbreak reports are loaded. Run <code>just data-ingest</code> to fetch WHO Disease
          Outbreak News, or press &ldquo;Run ingest&rdquo; above.
        </p>
      </div>
    );
  }

  return (
    <div className="sec">
      <h2 className="sec__title">Sourced outbreak reports ({reports.length})</h2>
      <ul className="list">
        {reports.map((report) => {
          const expanded = expandedId === report.id;
          const primaryCountry = report.countries[0];
          const primaryName =
            report.observations.find((observation) => observation.country_iso3 === primaryCountry)
              ?.country_name ?? primaryCountry;
          return (
            <li key={report.id}>
              <button
                type="button"
                className={`report ${expanded ? 'report--selected' : ''}`}
                aria-expanded={expanded}
                onClick={() => {
                  setExpandedId(expanded ? null : report.id);
                }}
              >
                <div className="report__title">{report.title}</div>
                <div className="report__meta">
                  <span>{formatDate(report.provenance.published_at)}</span>
                  <ValueTypeBadge
                    valueType={report.extraction_status === 'verified' ? 'observed' : 'unknown'}
                    label={report.extraction_status}
                  />
                  <span title={STATUS_LABEL[report.extraction_status] ?? ''}>
                    {report.observations.length} observation
                    {report.observations.length === 1 ? '' : 's'}
                  </span>
                  {report.countries.length > 0 && <span>{report.countries.join(', ')}</span>}
                </div>
              </button>

              {expanded && (
                <div className="report__body">
                  {loading && <div className="spinner" aria-label="Loading report detail" />}
                  {error !== null && <ErrorNotice error={error} context="Loading the report" />}
                  {detail && detail.id === report.id && <ReportDetail report={detail} />}
                  <div className="report__actions">
                    {report.provenance.source_url && (
                      <a
                        className="btn btn--sm"
                        href={report.provenance.source_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        style={{ textDecoration: 'none' }}
                      >
                        Open original source
                      </a>
                    )}
                    {primaryCountry !== undefined && (
                      <button
                        type="button"
                        className="btn btn--sm"
                        onClick={() => {
                          onCountrySelect(primaryCountry);
                        }}
                      >
                        Show {primaryName} on the map
                      </button>
                    )}
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
