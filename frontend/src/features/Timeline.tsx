import { useEffect } from 'react';
import type { DiseaseTimelinePoint } from '@/types/api';
import { formatCount } from '@/lib/format';

interface Props {
  points: DiseaseTimelinePoint[];
  year: number | null;
  onYearChange: (year: number | null) => void;
  playing: boolean;
  onPlayingChange: (playing: boolean) => void;
  diseaseName: string | null;
}

const STEP_MS = 620;

export function Timeline({
  points,
  year,
  onYearChange,
  playing,
  onPlayingChange,
  diseaseName,
}: Props) {
  const years = points.map((point) => point.year);
  const first = years[0] ?? null;
  const last = years.at(-1) ?? null;
  const current = year ?? last;
  // One tick at a time, so the parent stays the single source of truth for the year.
  useEffect(() => {
    if (!playing || first === null || last === null) return;
    const id = window.setInterval(() => {
      const next = (year ?? first) + 1;
      if (next > last) {
        onPlayingChange(false);
        onYearChange(last);
      } else {
        onYearChange(next);
      }
    }, STEP_MS);
    return () => {
      window.clearInterval(id);
    };
  }, [playing, year, first, last, onYearChange, onPlayingChange]);

  if (points.length === 0 || first === null || last === null || current === null) {
    return (
      <div className="timeline">
        <div className="timeline__head">
          <span className="timeline__label">Timeline</span>
          <span className="timeline__summary">
            {diseaseName
              ? `No dated report for ${diseaseName}.`
              : 'Pick a disease to see how it spread over time.'}
          </span>
        </div>
      </div>
    );
  }

  const maxReports = Math.max(...points.map((point) => point.report_count), 1);
  const active = points.find((point) => point.year === current);
  const reached = points
    .filter((point) => point.year <= current)
    .reduce((total, point) => total + point.new_country_count, 0);
  const progress = ((current - first) / Math.max(last - first, 1)) * 100;
  const atEnd = current >= last;

  return (
    <div className="timeline">
      <div className="timeline__head">
        <button
          type="button"
          className="btn btn--icon"
          onClick={() => {
            if (atEnd && !playing) onYearChange(first);
            onPlayingChange(!playing);
          }}
          aria-label={playing ? 'Pause the spread playback' : 'Play the spread over time'}
          title={playing ? 'Pause' : 'Play the spread year by year'}
        >
          {playing ? (
            <svg width="11" height="11" viewBox="0 0 12 12" fill="currentColor">
              <rect x="2" y="1.5" width="3" height="9" rx="1" />
              <rect x="7" y="1.5" width="3" height="9" rx="1" />
            </svg>
          ) : (
            <svg width="11" height="11" viewBox="0 0 12 12" fill="currentColor">
              <path d="M3 1.6 10.2 6 3 10.4Z" />
            </svg>
          )}
        </button>
        <span className="timeline__year num">{current}</span>
        <span className="timeline__summary">
          {active
            ? `${formatCount(active.report_count)} report${active.report_count === 1 ? '' : 's'}` +
              (active.new_country_count > 0
                ? ` · reached ${active.new_country_count} new ${active.new_country_count === 1 ? 'country' : 'countries'}`
                : '') +
              ` · ${reached} ${reached === 1 ? 'country' : 'countries'} affected by then`
            : `${reached} ${reached === 1 ? 'country' : 'countries'} affected by ${current}`}
        </span>
        {!atEnd && (
          <button
            type="button"
            className="btn btn--sm btn--ghost"
            onClick={() => {
              onPlayingChange(false);
              onYearChange(last);
            }}
          >
            Show all years
          </button>
        )}
      </div>

      <div className="timeline__chart" role="group" aria-label="Reports per year">
        {points.map((point) => (
          <button
            key={point.year}
            type="button"
            className={[
              'tlbar',
              point.year <= current ? 'tlbar--within' : '',
              point.year === current ? 'tlbar--current' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            title={
              `${point.year}: ${point.report_count} report(s), ` +
              `${point.new_country_count} new country(ies), ` +
              `${point.cumulative_country_count} affected in total`
            }
            onClick={() => {
              onPlayingChange(false);
              onYearChange(point.year);
            }}
          >
            <span
              className="tlbar__fill"
              style={{ height: `${(point.report_count / maxReports) * 100}%` }}
            />
            {point.new_country_count > 0 && <span className="tlbar__new" />}
            <span className="visually-hidden">
              {point.year}: {point.report_count} reports
            </span>
          </button>
        ))}
      </div>

      <div className="timeline__track">
        <div className="timeline__range" style={{ ['--w' as string]: `${progress}%` }} />
        <input
          className="timeline__slider"
          type="range"
          min={first}
          max={last}
          step={1}
          value={current}
          onChange={(event) => {
            onPlayingChange(false);
            onYearChange(Number(event.target.value));
          }}
          aria-label="Year"
        />
      </div>

      <div className="timeline__axis num">
        <span>{first}</span>
        <span>{last}</span>
      </div>
    </div>
  );
}
