interface Props {
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  format?: (value: number) => string;
  hint?: string;
  disabled?: boolean;
}

export function Slider({
  id,
  label,
  value,
  min,
  max,
  step,
  onChange,
  format,
  hint,
  disabled,
}: Props) {
  const display = format ? format(value) : String(value);
  return (
    <div className="slider">
      <div className="slider__head">
        <label className="slider__label" htmlFor={id}>
          {label}
        </label>
        <output className="slider__value" htmlFor={id}>
          {display}
        </output>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(event) => {
          onChange(Number(event.target.value));
        }}
        aria-describedby={hint ? `${id}-hint` : undefined}
      />
      {hint && (
        <p className="slider__hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
    </div>
  );
}
