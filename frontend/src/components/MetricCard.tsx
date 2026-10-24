import type { ReactNode } from 'react';
import type { BandedQuantity } from '@/types/api';
import { formatPercent, unavailableText } from '@/lib/format';
import { ValueTypeBadge } from '@/components/ValueTypeBadge';

interface Props {
  question: string;
  band: BandedQuantity;
  /** Replaces the generic reason when a specific one reads better. */
  unavailableText?: string;
  detail?: string;
  saturated?: boolean;
  children?: ReactNode;
  testId?: string;
}

function BandBar({ band }: { band: BandedQuantity }) {
  if (band.low === null || band.high === null) return null;
  const start = Math.max(0, Math.min(Math.min(band.low, band.high), 1));
  const end = Math.max(0, Math.min(Math.max(band.low, band.high), 1));
  const left = start * 100;
  const width = Math.max((end - start) * 100, 0.8);
  const central = band.central === null ? null : Math.min(band.central, 1) * 100;
  return (
    <div
      className="bandbar"
      role="img"
      aria-label={`Scenario range from ${formatPercent(band.low)} to ${formatPercent(band.high)}`}
    >
      <div className="bandbar__range" style={{ left: `${left}%`, width: `${width}%` }} />
      {central !== null && <div className="bandbar__central" style={{ left: `${central}%` }} />}
    </div>
  );
}

export function MetricCard({
  question,
  band,
  unavailableText: unavailableOverride,
  detail,
  saturated,
  children,
  testId,
}: Props) {
  const unavailable = band.central === null;
  return (
    <section className="metric" data-testid={testId}>
      <div className="metric__head">
        <h3 className="metric__question">{question}</h3>
        <ValueTypeBadge valueType={band.value_type} />
      </div>

      {unavailable ? (
        <p className="metric__value metric__value--unknown" data-testid={`${testId ?? ''}-unknown`}>
          Not estimable — {unavailableOverride ?? unavailableText(band.unavailable_reason)}
        </p>
      ) : (
        <>
          <div className="metric__value">
            {saturated ? '> 99.99%' : formatPercent(band.central)}
          </div>
          <div className="metric__band">
            range {formatPercent(band.low)} – {formatPercent(band.high)}
          </div>
          <BandBar band={band} />
        </>
      )}

      {band.note && <p className="metric__detail">{band.note}</p>}
      {detail && <p className="metric__detail">{detail}</p>}
      {!unavailable && band.band_basis && <p className="metric__basis">{band.band_basis}</p>}
      {children}
    </section>
  );
}
