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
          <dt>Infected arrivals</dt>
          <dd>{formatRate(origin.arrival_rate_per_day)} /day</dd>
        </div>
        <div>
          <dt>Reported cases</dt>
          <dd>{formatCount(origin.reported_cases)}</dd>
        </div>
      </dl>
      {origin.report_url && (
        <p className="metric__basis">
          <a href={origin.report_url} target="_blank" rel="noreferrer noopener">
            Source report
          </a>{' '}
          · {formatDate(origin.report_published_at)}
        </p>
      )}
    </li>
  );
}

// The panel answers three questions and names who feeds them. Everything that
// was below - excluded origins, scenario thresholds, the assumption table and
// the parameter references - lives on the Assumptions and Sources tabs, which
// is where someone auditing the numbers goes anyway.
const TOP_ORIGINS = 3;

// Three states, because the evidence has three. The ordering held up on both
// held-out outbreaks and the absolute level did not, so saying only
// "calibrated or not" would either overclaim the percentage or throw away a
// ranking that beats the arithmetic it replaces.
const CALIBRATION_NOTE: Record<string, string> = {
  calibrated: 'Ordering and level both validated on a held-out outbreak.',
  ranking_validated:
    'The ordering is validated on held-out outbreaks; the percentage is indicative, not calibrated.',
  not_validated: 'Not validated — these are uncalibrated scenario numbers.',
};
const TOP_NEXT = 5;

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
          Three questions behind the index above, over a {risk.horizon_days}-day horizon. Computed{' '}
          {relativeAge(risk.computed_at)}. Every input, threshold and reference is on the
          Assumptions tab.
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
          <div className="sec__head">
            <h2 className="sec__title">Where the risk comes from</h2>
            {importation.top_origins.length > TOP_ORIGINS && (
              <span className="chip chip--past num">
                top {TOP_ORIGINS} of {importation.top_origins.length}
              </span>
            )}
          </div>
          <ul className="list">
            {importation.top_origins.slice(0, TOP_ORIGINS).map((origin) => (
              <OriginRow key={origin.origin_iso3} origin={origin} />
            ))}
          </ul>
        </div>
      )}

      {nextCountries && nextCountries.countries.length > 0 && (
        <div className="sec">
          <h2 className="sec__title">Most likely to report next</h2>
          <ol className="ranked">
            {nextCountries.countries.slice(0, TOP_NEXT).map((country) => (
              <li key={country.iso3}>
                <span>{country.name}</span>
                <strong className="num">
                  {country.probability === null ? 'no answer' : formatPercent(country.probability)}
                </strong>
              </li>
            ))}
          </ol>
          <p className="metric__basis" data-testid="calibration-status">
            {CALIBRATION_NOTE[nextCountries.calibration_status] ??
              CALIBRATION_NOTE['not_validated']}
          </p>
        </div>
      )}

      {risk.warnings.length > 0 && (
        <details className="sec fold">
          <summary>Caveats on this estimate ({risk.warnings.length})</summary>
          <Warnings warnings={risk.warnings} />
        </details>
      )}

      <p className="footnote">{risk.disclaimer}</p>
    </>
  );
}
