import type { CountryDisease, CountryProfile } from '@/types/api';
import { formatCount, formatDate } from '@/lib/format';

interface Props {
  profile: CountryProfile | null;
  loading: boolean;
  focusDiseaseKey: string | null;
  onSelectDisease: (key: string) => void;
}

function span(disease: CountryDisease): string {
  const first = disease.first_published_at?.slice(0, 4);
  const last = disease.last_published_at?.slice(0, 4);
  if (!first) return 'undated';
  return first === last ? first : `${first}–${last ?? 'now'}`;
}

function DiseaseRow({
  disease,
  focused,
  onSelect,
}: {
  disease: CountryDisease;
  focused: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        className="row"
        aria-current={focused}
        onClick={onSelect}
        title={`Show how ${disease.disease_name} spread`}
      >
        <span className="row__top">
          <span
            className={disease.is_active ? 'dot dot--pulse' : 'dot'}
            style={{ color: disease.is_active ? 'var(--hot)' : 'var(--ink-4)' }}
            aria-hidden="true"
          />
          <span className="row__name">{disease.disease_name}</span>
          <span className={disease.is_active ? 'chip chip--live' : 'chip chip--past'}>
            {disease.is_active ? 'Active' : span(disease)}
          </span>
        </span>
        <dl className="kv">
          <div>
            <dt>Peak cases</dt>
            <dd className="num">{formatCount(disease.cases_confirmed)}</dd>
          </div>
          <div>
            <dt>Peak deaths</dt>
            <dd className="num">{formatCount(disease.deaths)}</dd>
          </div>
          <div>
            <dt>Reports</dt>
            <dd className="num">{disease.report_count}</dd>
          </div>
          <div>
            <dt>Last report</dt>
            <dd style={{ fontSize: 11.5 }}>{formatDate(disease.last_published_at)}</dd>
          </div>
        </dl>
        {!disease.grounded && (
          <span className="metric__basis">
            No case count in this country&apos;s reports could be matched to the source text, so
            only the dates and the location are shown.
          </span>
        )}
      </button>
    </li>
  );
}

export function CountryPanel({ profile, loading, focusDiseaseKey, onSelectDisease }: Props) {
  if (loading && !profile) {
    return (
      <div className="sec" style={{ display: 'flex', gap: 9, alignItems: 'center' }}>
        <span className="spinner" />
        <span style={{ color: 'var(--ink-3)' }}>Loading this country&apos;s record…</span>
      </div>
    );
  }

  if (!profile) {
    return <p className="empty">Click a country on the map to see its outbreak record.</p>;
  }

  const active = profile.diseases.filter((disease) => disease.is_active);
  const past = profile.diseases.filter((disease) => !disease.is_active);

  return (
    <>
      <div className="sec">
        <div className="stats">
          <div className="stat">
            <span className="stat__label">Diseases on record</span>
            <span className="stat__value num">{profile.diseases.length}</span>
          </div>
          <div className="stat">
            <span className="stat__label">Active now</span>
            <span
              className={active.length > 0 ? 'stat__value stat__value--hot num' : 'stat__value num'}
            >
              {active.length}
            </span>
          </div>
          <div className="stat">
            <span className="stat__label">Reports</span>
            <span className="stat__value num">{formatCount(profile.report_count)}</span>
          </div>
          <div className="stat">
            <span className="stat__label">Population</span>
            <span className="stat__value num" style={{ fontSize: 15 }}>
              {profile.population === null
                ? '—'
                : `${(profile.population / 1_000_000).toFixed(1)}M`}
            </span>
          </div>
        </div>
      </div>

      <p className="footnote" style={{ borderTop: 0, paddingTop: 0 }}>
        Peak figures are the highest cumulative count any single report grounded for this country,
        not a running total across reports.
      </p>

      {profile.diseases.length === 0 && (
        <p className="empty">
          No WHO Disease Outbreak News report in the archive names this country. Absence of a report
          is not evidence of absence of disease.
        </p>
      )}

      {active.length > 0 && (
        <div className="sec">
          <div className="sec__head">
            <h3 className="sec__title">Currently reported</h3>
            <span className="chip chip--live">
              <span className="dot dot--pulse" aria-hidden="true" />
              {active.length}
            </span>
          </div>
          <ul className="list">
            {active.map((disease) => (
              <DiseaseRow
                key={disease.disease_key}
                disease={disease}
                focused={disease.disease_key === focusDiseaseKey}
                onSelect={() => {
                  onSelectDisease(disease.disease_key);
                }}
              />
            ))}
          </ul>
        </div>
      )}

      {past.length > 0 && (
        <div className="sec">
          <div className="sec__head">
            <h3 className="sec__title">Earlier outbreaks</h3>
            <span className="chip chip--past num">{past.length}</span>
          </div>
          <ul className="list">
            {past.map((disease) => (
              <DiseaseRow
                key={disease.disease_key}
                disease={disease}
                focused={disease.disease_key === focusDiseaseKey}
                onSelect={() => {
                  onSelectDisease(disease.disease_key);
                }}
              />
            ))}
          </ul>
        </div>
      )}
    </>
  );
}
