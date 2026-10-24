import { useMemo, useState } from 'react';
import type { DiseaseHistory } from '@/types/api';
import { formatCount } from '@/lib/format';

type Scope = 'all' | 'active' | 'major';

const SCOPES: { id: Scope; label: string; title: string }[] = [
  { id: 'all', label: 'All', title: 'Every disease in the archive' },
  { id: 'active', label: 'Active', title: 'Reported in the last 180 days' },
  { id: 'major', label: 'Widest', title: 'Reached the most countries' },
];

interface Props {
  diseases: DiseaseHistory[];
  selectedKey: string | null;
  onSelect: (key: string) => void;
  loading: boolean;
  activeWindowDays: number;
}

function year(iso: string | null): string {
  return iso ? iso.slice(0, 4) : '—';
}

function isActive(disease: DiseaseHistory, windowDays: number): boolean {
  if (!disease.last_published_at) return false;
  const age = (Date.now() - new Date(disease.last_published_at).getTime()) / 86_400_000;
  return age <= windowDays;
}

/** The years this disease was reported, drawn inside the archive's full span. */
function SpanBar({ disease, from, to }: { disease: DiseaseHistory; from: number; to: number }) {
  const first = Number(year(disease.first_published_at));
  const last = Number(year(disease.last_published_at));
  if (!Number.isFinite(first) || !Number.isFinite(last)) return null;
  const total = Math.max(to - from, 1);
  const left = ((Math.max(first, from) - from) / total) * 100;
  const width = Math.max(((Math.min(last, to) - Math.max(first, from)) / total) * 100, 2.5);
  return (
    <span className="dcard__span" aria-hidden="true">
      <i style={{ left: `${left}%`, width: `${width}%` }} />
    </span>
  );
}

export function DiseaseRail({ diseases, selectedKey, onSelect, loading, activeWindowDays }: Props) {
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState<Scope>('all');

  const span = useMemo(() => {
    const years = diseases.flatMap((disease) =>
      [disease.first_published_at, disease.last_published_at]
        .map((iso) => Number(year(iso)))
        .filter((value) => Number.isFinite(value)),
    );
    return years.length > 0
      ? { from: Math.min(...years), to: Math.max(...years) }
      : { from: 1996, to: new Date().getFullYear() };
  }, [diseases]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    let list = diseases;
    if (needle) {
      list = list.filter(
        (disease) =>
          disease.disease_name.toLowerCase().includes(needle) ||
          (disease.disease_family ?? '').toLowerCase().includes(needle) ||
          disease.source_labels.some((label) => label.toLowerCase().includes(needle)),
      );
    }
    if (scope === 'active') {
      list = list.filter((disease) => isActive(disease, activeWindowDays));
    }
    if (scope === 'major') {
      list = [...list].sort((a, b) => b.country_count - a.country_count);
    }
    return list;
  }, [diseases, query, scope, activeWindowDays]);

  return (
    <aside className="rail" aria-label="Diseases">
      <div className="rail__head">
        <div className="rail__title">
          <h2>Diseases</h2>
          <span className="rail__count num">
            {loading ? '…' : `${visible.length} of ${diseases.length}`}
          </span>
        </div>
        <label className="field">
          <span className="field__icon" aria-hidden="true">
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
              <circle cx="6.8" cy="6.8" r="4.6" stroke="currentColor" strokeWidth="1.6" />
              <path d="M10.4 10.4 14 14" stroke="currentColor" strokeWidth="1.6" />
            </svg>
          </span>
          <input
            className="field__input"
            type="search"
            placeholder="Search diseases"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
            }}
            aria-label="Search diseases"
          />
        </label>
      </div>

      <div className="rail__filters" role="group" aria-label="Filter diseases">
        {SCOPES.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className="segment"
            aria-pressed={scope === entry.id}
            title={entry.title}
            onClick={() => {
              setScope(entry.id);
            }}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div className="rail__list">
        {visible.length === 0 && (
          <p className="rail__empty">
            {loading ? 'Loading the archive…' : 'No disease matches that search.'}
          </p>
        )}
        {visible.map((disease) => {
          const live = isActive(disease, activeWindowDays);
          return (
            <button
              key={disease.disease_key}
              type="button"
              className="dcard"
              aria-current={disease.disease_key === selectedKey}
              onClick={() => {
                onSelect(disease.disease_key);
              }}
            >
              <span className="dcard__top">
                <span
                  className={live ? 'dot dot--pulse' : 'dot'}
                  style={{ color: live ? 'var(--hot)' : 'var(--ink-4)' }}
                  aria-hidden="true"
                />
                <span className="dcard__name">{disease.disease_name}</span>
              </span>
              <SpanBar disease={disease} from={span.from} to={span.to} />
              <span className="dcard__meta num">
                <span>
                  <b>{disease.country_count}</b> countries
                </span>
                <span>
                  <b>{formatCount(disease.report_count)}</b> reports
                </span>
                <span style={{ marginLeft: 'auto' }}>
                  {year(disease.first_published_at)}–{year(disease.last_published_at)}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
