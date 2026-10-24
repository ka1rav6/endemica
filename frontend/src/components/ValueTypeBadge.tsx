import type { ValueType } from '@/types/api';
import { VALUE_TYPE_DESCRIPTION, VALUE_TYPE_LABEL } from '@/lib/format';

const SHAPE: Record<ValueType, string> = {
  observed: 'badge--square',
  estimated: 'badge--diamond',
  modelled: 'badge--triangle',
  scenario: 'badge--bar',
  unknown: 'badge',
};

interface Props {
  valueType: ValueType;
  label?: string;
}

export function ValueTypeBadge({ valueType, label }: Props) {
  return (
    <span
      className={`badge badge--${valueType} ${SHAPE[valueType]}`}
      title={VALUE_TYPE_DESCRIPTION[valueType]}
    >
      <span className="badge__dot" aria-hidden="true" />
      {label ?? VALUE_TYPE_LABEL[valueType]}
    </span>
  );
}

export function ValueTypeLegend() {
  const types: ValueType[] = ['observed', 'estimated', 'modelled', 'scenario', 'unknown'];
  return (
    <div className="legend">
      {types.map((type) => (
        <span key={type} className="legend__item">
          <ValueTypeBadge valueType={type} />
        </span>
      ))}
    </div>
  );
}
