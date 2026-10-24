import type { RiskParams } from '@/types/api';

export interface ScenarioState {
  pathogen: string | null;
  horizonDays: number;
  sigma: number;
  passengerScale: number;
  underreportingLow: number;
  underreportingCentral: number;
  underreportingHigh: number;
  alpha: number | null;
  reproductionNumber: number | null;
  dispersionK: number | null;
  threshold: number;
}

export const DEFAULT_SCENARIO: ScenarioState = {
  pathogen: null,
  horizonDays: 14,
  sigma: 0,
  passengerScale: 1,
  underreportingLow: 2,
  underreportingCentral: 4,
  underreportingHigh: 10,
  alpha: null,
  reproductionNumber: null,
  dispersionK: null,
  threshold: 0.5,
};

export function toRiskParams(state: ScenarioState): RiskParams {
  return {
    pathogen: state.pathogen ?? undefined,
    horizon_days: state.horizonDays,
    sigma: state.sigma,
    passenger_scale: state.passengerScale,
    underreporting_low: state.underreportingLow,
    underreporting_central: state.underreportingCentral,
    underreporting_high: state.underreportingHigh,
    alpha: state.alpha ?? undefined,
    reproduction_number: state.reproductionNumber ?? undefined,
    dispersion_k: state.dispersionK ?? undefined,
    threshold: state.threshold,
    max_origins: 10,
  };
}
