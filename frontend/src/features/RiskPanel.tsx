import type { NextCountriesResponse, OriginContribution, RiskResponse } from '@/types/api';
import {
  formatCount,
  formatDate,
  formatPassengers,
  formatPercent,
  formatRate,
  relativeAge,
  unavailableText,
} from '@/lib/format';
import { MetricCard } from '@/components/MetricCard';
import { ValueTypeBadge } from '@/components/ValueTypeBadge';
import { Warnings } from '@/components/Warnings';
import { riskColor } from '@/lib/riskColor';

function PresenceCard({ risk }: { risk: RiskResponse }) {
  const { presence, travel_index: travel } = risk;
  const reported = presence.status === 'reported';
  const presenceScore = travel?.components.find((component) => component.key === 'presence')?.score;
  return (
    <section className="metric" data-testid="presence-card">
      <div className="metric__head">
        <h3 className="metric__question">Is it already here?</h3>
        <ValueTypeBadge valueType={presence.value_type} />
      </div>
      <div
        className={reported ? 'metric__value' : 'metric__value metric__value--unknown'}
        style={
          reported
            ? {
                color:
                  presenceScore === null || presenceScore === undefined
                    ? 'var(--outbreak)'
                    : riskColor(presenceScore),
                fontSize: 22,
              }
            : undefined
        }
        data-testid="presence-status"
      >
        {reported
          ? 'Cases reported'
          : presence.status === 'not_reported'
            ? 'No report on file'
            : `Not estimable — ${unavailableText(presence.unavailable_reason)}`}
      </div>
      {reported && (
        <dl className="kv" style={{ marginTop: 8 }}>
          <div>
            <dt>Confirmed cases</dt>
            <dd>{formatCount(presence.cases_confirmed?.value ?? null)}</dd>
          </div>
          <div>
            <dt>Deaths</dt>
            <dd>{formatCount(presence.deaths?.value ?? null)}</dd>
          </div>
          <div>
            <dt>Last reported</dt>
            <dd>{formatDate(presence.last_reported_at)}</dd>
          </div>
          <div>
            <dt>Reports</dt>
            <dd>{presence.report_count}</dd>
          </div>
        </dl>
      )}
      <p className="metric__detail">{presence.detail}</p>
      {presence.source_urls.length > 0 && (
        <p className="metric__basis">
          Sources:{' '}
          {presence.source_urls.map((url, index) => (
            <span key={url}>
              {index > 0 && ', '}
              <a href={url} target="_blank" rel="noreferrer noopener">
                report {index + 1}
              </a>
            </span>
          ))}
        </p>
      )}
    </section>
  );
}

function OriginRow({ origin }: { origin: OriginContribution }) {
  return (
    <li className="row">
      <div className="row__top">
        <span className="row__name">{origin.origin_name}</span>
        <span className="row__aside">{formatPercent(origin.share_of_total, 0)} of rate</span>
      </div>
      <dl className="kv">
        <div>
          <dt>Passengers</dt>
          <dd>
            {formatPassengers(origin.passengers_per_day)}{' '}
            <ValueTypeBadge
              valueType={origin.passengers_value_type}
              label={origin.passengers_value_type === 'observed' ? 'obs' : 'model'}
            />
          </dd>
        </div>
        <div>
          <dt>Origin prevalence</dt>
          <dd>{origin.prevalence_per_100k.toFixed(2)} / 100k</dd>
        </div>
        <div>
          <dt>Arrival rate</dt>
          <dd>{formatRate(origin.arrival_rate_per_day)} /day</dd>
        </div>
        <div>
          <dt>Effective distance</dt>
          <dd>{origin.effective_distance === null ? '—' : origin.effective_distance.toFixed(2)}</dd>
        </div>
        <div>
          <dt>Reported cases</dt>
          <dd>{formatCount(origin.reported_cases)}</dd>
        </div>
        <div>
          <dt>Report date</dt>
          <dd>{formatDate(origin.report_published_at)}</dd>
        </div>
      </dl>
      {origin.via_hubs.length > 0 && (
        <p className="metric__basis">Shortest flow path runs via {origin.via_hubs.join(' → ')}</p>
      )}
      {origin.report_url && (
        <p className="metric__basis">
          <a href={origin.report_url} target="_blank" rel="noreferrer noopener">
            Open the source report
          </a>{' '}
          · passenger source: {origin.passengers_source}
        </p>
      )}
    </li>
  );
}

export function RiskPanel({
  risk,
  nextCountries,
}: {
  risk: RiskResponse;
  nextCountries?: NextCountriesResponse | null;
}) {
  const { importation, establishment, pathogen } = risk;
  const aggregate = pathogen.scope === 'active';

  return (
    <>
      <div className="sec">
        <h2 className="sec__title">
          {risk.destination_name}
          <span style={{ color: 'var(--text-faint)', fontWeight: 400, textTransform: 'none' }}>
            {pathogen.label}
            {pathogen.confidence ? ` · parameter confidence: ${pathogen.confidence}` : ''}
          </span>
        </h2>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--text-faint)' }}>
          The index above is a scenario summary. These three questions keep the separate inputs.
          Computed {relativeAge(risk.computed_at)} with {risk.model_version} over a{' '}
          {risk.horizon_days}-day horizon.
        </p>
      </div>

      <div className="sec">
        <PresenceCard risk={risk} />

        <MetricCard
          question={
            aggregate
              ? `Will a traveller infected with any active disease arrive within ${risk.horizon_days} days?`
              : `Will an infected traveller arrive within ${risk.horizon_days} days?`
          }
          band={importation.probability}
          saturated={importation.is_saturated}
          testId="importation-card"
          detail={
            importation.probability.central === null
              ? undefined
              : `Expected ${formatRate(importation.arrival_rate_per_day.central)} infected arrivals per day from ${importation.origin_count_usable} usable origin${importation.origin_count_usable === 1 ? '' : 's'} of ${importation.origin_count_considered} considered.`
          }
        />

        <MetricCard
          question={`Will sustained local transmission begin within ${risk.horizon_days} days?`}
          band={establishment.probability_within_horizon}
          {...(aggregate
            ? { unavailableText: 'not reported across several diseases at once' }
            : {})}
          detail={establishment.detail}
          testId="establishment-card"
        >
          {establishment.probability_per_introduction.central !== null && (
            <p className="metric__detail">
              Per single introduction:{' '}
              <strong>{formatPercent(establishment.probability_per_introduction.central)}</strong>{' '}
              (range {formatPercent(establishment.probability_per_introduction.low)} –{' '}
              {formatPercent(establishment.probability_per_introduction.high)}), at R{' '}
              {establishment.reproduction_number_used.central}, k{' '}
              {establishment.dispersion_used.central}.
            </p>
          )}
        </MetricCard>
      </div>

      {importation.top_origins.length > 0 && (
        <div className="sec">
          <h2 className="sec__title">Where the risk comes from</h2>
          <ul className="list">
            {importation.top_origins.map((origin) => (
              <OriginRow key={origin.origin_iso3} origin={origin} />
            ))}
          </ul>
        </div>
      )}

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

      <p className="metric__basis" data-testid="calibration-status">
        Next-country model:{' '}
        {risk.calibration_status === 'calibrated'
          ? 'calibrated on held-out outbreaks'
          : 'not validated — the number below is the uncalibrated scenario'}
      </p>
      {nextCountries && nextCountries.countries.length > 0 && (
        <div className="sec">
          <h2 className="sec__title">Most likely to report next</h2>
          <ol>
            {nextCountries.countries.map((country) => (
              <li key={country.iso3}>
                {country.name} — {formatPercent(country.probability)}
              </li>
            ))}
          </ol>
        </div>
      )}

      {risk.scenario_markers.length > 0 && (
        <div className="sec">
          <h2 className="sec__title">
            Scenario thresholds
            <ValueTypeBadge valueType="scenario" />
          </h2>
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

      {risk.warnings.length > 0 && (
        <div className="sec">
          <h2 className="sec__title">Caveats</h2>
          <Warnings warnings={risk.warnings} />
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

      <p className="footnote">{risk.disclaimer}</p>
    </>
  );
}
