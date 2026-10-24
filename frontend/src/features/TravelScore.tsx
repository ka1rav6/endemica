import { RISK_COLOR_STOPS, riskColor } from '@/lib/riskColor';
import type { TravelIndex, TravelIndexComponent } from '@/types/api';

const LABELS: Record<TravelIndexComponent['key'], string> = {
  presence: 'Presence',
  importation: 'Importation',
  establishment: 'Establishment',
  connectivity: 'Connectivity',
};

const HINTS: Record<TravelIndexComponent['key'], string> = {
  presence: 'Is it already there?',
  importation: 'Could an infectious traveller arrive in the horizon?',
  establishment: 'Could local spread take off in the horizon?',
  connectivity: 'How strong are the modelled arrival flows?',
};

const METER = `linear-gradient(90deg, ${RISK_COLOR_STOPS.map(
  ([stop, color]) => `${color} ${stop * 10}%`,
).join(', ')})`;

export function TravelScore({ index, replayKey }: { index: TravelIndex; replayKey?: string }) {
  const color = index.score === null ? 'var(--ink-3)' : riskColor(index.score);

  return (
    <section className="travel" data-testid="travel-index" aria-label="Travel-risk index">
      <p className="travel__kicker">
        Travel-risk index
        <span className="travel__kind">Scenario summary</span>
      </p>
      {index.score === null ? (
        <p className="travel__empty">Not estimable</p>
      ) : (
        <div className="travel__hero">
          <span
            key={`${replayKey ?? 'score'}-${index.score}`}
            className="travel__score num"
            style={{ color }}
          >
            {index.score.toFixed(1)}
          </span>
          <span className="travel__scale">/ 10</span>
          {index.band && (
            <span className="travel__band" style={{ color }}>
              {index.band}
            </span>
          )}
        </div>
      )}
      {index.score !== null && (
        <span className="travel__meter" style={{ background: METER }} aria-hidden="true">
          <i style={{ left: `${(index.score / 10) * 100}%`, background: color }} />
        </span>
      )}
      <p className="travel__hint">
        {index.score === null
          ? 'There is not enough grounded input to score this destination.'
          : 'Higher means more reason to check official guidance before travel.'}
      </p>
      <ul className="travel__parts">
        {index.components.map((component) => {
          const partColor = component.score === null ? 'var(--ink-4)' : riskColor(component.score);
          return (
            <li
              key={component.key}
              className={component.available ? 'travel__part' : 'travel__part travel__part--off'}
              title={HINTS[component.key]}
            >
              <span className="travel__part-top">
                <span>{LABELS[component.key]}</span>
                <span className="num">
                  {component.available && component.score !== null
                    ? component.score.toFixed(1)
                    : '—'}
                </span>
              </span>
              <span className="travel__bar" aria-hidden="true">
                <i
                  style={{
                    width: `${component.score === null ? 0 : (component.score / 10) * 100}%`,
                    background: partColor,
                  }}
                />
              </span>
              <span className="travel__weight">
                {component.available
                  ? `${Math.round(component.weight * 100)}% of the index`
                  : 'Left out'}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="travel__note">{index.note}</p>
    </section>
  );
}
