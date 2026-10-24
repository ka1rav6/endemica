import type { PathogenSummary } from '@/types/api';
import { DEFAULT_SCENARIO, type ScenarioState } from '@/lib/scenario';
import { Slider } from '@/components/Slider';
import { ValueTypeBadge } from '@/components/ValueTypeBadge';

interface Props {
  state: ScenarioState;
  onChange: (state: ScenarioState) => void;
  pathogens: PathogenSummary[];
  establishmentEstimable: boolean;
}

export function ScenarioControls({ state, onChange, pathogens, establishmentEstimable }: Props) {
  const set = <K extends keyof ScenarioState>(key: K, value: ScenarioState[K]) => {
    onChange({ ...state, [key]: value });
  };

  return (
    <div className="panel__section">
      <h2 className="panel__heading">
        Model assumptions
        <ValueTypeBadge valueType="scenario" />
      </h2>
      <p style={{ margin: '0 0 14px', fontSize: 11.5, color: 'var(--text-faint)' }}>
        Every control below changes a <strong>model assumption</strong>, not an observation. Moving
        them cannot change whether cases have been reported.
      </p>

      <div className="field" style={{ marginBottom: 14 }}>
        <label className="field__label" htmlFor="pathogen-select">
          Pathogen profile
        </label>
        <select
          id="pathogen-select"
          value={state.pathogen ?? ''}
          onChange={(event) => {
            const value = event.target.value;
            onChange({
              ...state,
              pathogen: value === '' ? null : value,
              alpha: null,
              reproductionNumber: null,
              dispersionK: null,
            });
          }}
        >
          <option value="">Infer from the latest report</option>
          {pathogens.map((pathogen) => (
            <option key={pathogen.key ?? ''} value={pathogen.key ?? ''}>
              {pathogen.label}
            </option>
          ))}
        </select>
      </div>

      <Slider
        id="horizon"
        label="Time horizon"
        value={state.horizonDays}
        min={1}
        max={180}
        step={1}
        onChange={(value) => {
          set('horizonDays', value);
        }}
        format={(value) => `${value} days`}
        hint="The window over which at least one arrival is counted."
      />

      <Slider
        id="sigma"
        label="Screening and border effectiveness (σ)"
        value={state.sigma}
        min={0}
        max={0.9}
        step={0.05}
        onChange={(value) => {
          set('sigma', value);
        }}
        format={(value) => (value === 0 ? 'none confirmed' : `${(value * 100).toFixed(0)}%`)}
        hint="0 is the default: no confirmed measure. Capped at 90% — no border measure is perfect."
      />

      <Slider
        id="passenger-scale"
        label="Passenger volume scale"
        value={state.passengerScale}
        min={0.1}
        max={5}
        step={0.1}
        onChange={(value) => {
          set('passengerScale', value);
        }}
        format={(value) => `${value.toFixed(1)}×`}
        hint="Scales every flow. Use it to explore a schedule change, not to correct the data."
      />

      <Slider
        id="underreporting-high"
        label="Under-reporting multiplier, high end"
        value={state.underreportingHigh}
        min={1}
        max={50}
        step={1}
        onChange={(value) => {
          onChange({
            ...state,
            underreportingHigh: value,
            underreportingCentral: Math.min(state.underreportingCentral, value),
            underreportingLow: Math.min(state.underreportingLow, value),
          });
        }}
        format={(value) => `${value}×`}
        hint="Widens the upper bound of the band. No measured value exists for a live outbreak."
      />

      <Slider
        id="underreporting-central"
        label="Under-reporting multiplier, central"
        value={state.underreportingCentral}
        min={1}
        max={state.underreportingHigh}
        step={1}
        onChange={(value) => {
          onChange({
            ...state,
            underreportingCentral: value,
            underreportingLow: Math.min(state.underreportingLow, value),
          });
        }}
        format={(value) => `${value}×`}
      />

      <Slider
        id="alpha"
        label="Boarding while infectious (α)"
        value={state.alpha ?? 0}
        min={0}
        max={1}
        step={0.02}
        onChange={(value) => {
          set('alpha', value === 0 ? null : value);
        }}
        format={(value) =>
          state.alpha === null ? 'profile default' : `${(value * 100).toFixed(0)}%`
        }
        hint="Relative to a randomly chosen traveller. Set to 0 to return to the profile default."
      />

      <Slider
        id="reproduction-number"
        label="Reproduction number (R)"
        value={state.reproductionNumber ?? 0}
        min={0}
        max={6}
        step={0.1}
        onChange={(value) => {
          set('reproductionNumber', value === 0 ? null : value);
        }}
        format={(value) =>
          state.reproductionNumber === null ? 'profile default' : value.toFixed(1)
        }
        hint="At or below 1, establishment is exactly zero. Importation is unaffected."
        disabled={!establishmentEstimable}
      />

      <Slider
        id="dispersion-k"
        label="Cluster dispersion (k)"
        value={state.dispersionK ?? 0}
        min={0}
        max={5}
        step={0.05}
        onChange={(value) => {
          set('dispersionK', value === 0 ? null : value);
        }}
        format={(value) => (state.dispersionK === null ? 'profile default' : value.toFixed(2))}
        hint="Low k means most chains die out even when R is high."
        disabled={!establishmentEstimable}
      />

      <Slider
        id="threshold"
        label="Scenario marker threshold"
        value={state.threshold}
        min={0.05}
        max={0.95}
        step={0.05}
        onChange={(value) => {
          set('threshold', value);
        }}
        format={(value) => `${(value * 100).toFixed(0)}%`}
        hint="The probability a scenario marker reports the first day of."
      />

      {!establishmentEstimable && (
        <p className="metric__basis">
          R and k are disabled because establishment is not estimable for this pathogen class.
        </p>
      )}

      <button
        type="button"
        className="button"
        onClick={() => {
          onChange({ ...DEFAULT_SCENARIO, pathogen: state.pathogen });
        }}
      >
        Reset assumptions
      </button>
    </div>
  );
}
