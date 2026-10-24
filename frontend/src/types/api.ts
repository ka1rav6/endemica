export type ValueType = 'observed' | 'estimated' | 'modelled' | 'scenario' | 'unknown';

export type ExtractionStatus = 'verified' | 'unverified' | 'partial' | 'failed' | 'not_attempted';

export type ExtractionMethod =
  | 'who_api_field'
  | 'deterministic_parser'
  | 'tinyfish_agent'
  | 'tinyfish_fetch';

export type PresenceStatus = 'reported' | 'not_reported' | 'not_estimable';

export interface Quantity {
  value: number | null;
  value_type: ValueType;
  unit: string | null;
  unavailable_reason: string | null;
  note: string | null;
}

export interface BandedQuantity {
  low: number | null;
  central: number | null;
  high: number | null;
  value_type: ValueType;
  unit: string | null;
  band_basis: string | null;
  unavailable_reason: string | null;
  note: string | null;
}

export interface Assumption {
  key: string;
  label: string;
  value: number | string | boolean | null;
  unit: string | null;
  value_type: ValueType;
  source: string;
  note: string | null;
}

export interface ResponseWarning {
  code: string;
  message: string;
  severity: 'info' | 'caution' | 'important';
}

export interface DataFreshness {
  source: string;
  retrieved_at: string | null;
  record_count: number | null;
  is_stale: boolean;
  status: 'ok' | 'stale' | 'missing' | 'degraded';
  detail: string | null;
}

export interface Provenance {
  source_name: string;
  source_url: string | null;
  source_identifier: string | null;
  published_at: string | null;
  retrieved_at: string;
  extraction_method: ExtractionMethod | null;
  extraction_status: ExtractionStatus;
  extraction_run_id: string | null;
  license_note: string | null;
}

export interface Observation {
  id: string;
  country_iso3: string;
  country_name: string;
  country_name_as_reported: string | null;
  subnational_name: string | null;
  cases_confirmed: number | null;
  cases_probable: number | null;
  cases_suspected: number | null;
  deaths: number | null;
  period_start: string | null;
  period_end: string | null;
  period_text: string | null;
  evidence_text: string | null;
  grounding_status: ExtractionStatus;
  value_type: ValueType;
  usable_for_models: boolean;
}

export interface OutbreakReport {
  id: string;
  title: string;
  disease_label: string | null;
  pathogen_key: string | null;
  summary_text: string | null;
  provenance: Provenance;
  extraction_method: ExtractionMethod;
  extraction_status: ExtractionStatus;
  countries: string[];
  observations: Observation[];
  warning_count: number;
}

export interface GroundingField {
  field: string;
  value: number;
  verdict: string;
  detail: string;
  context: string | null;
}

export interface OutbreakReportDetail extends OutbreakReport {
  narrative_text: string | null;
  validation_warnings: Record<string, unknown>[];
  grounding_fields: GroundingField[];
}

export interface OutbreakListResponse {
  total: number;
  limit: number;
  offset: number;
  items: OutbreakReport[];
}

export interface Country {
  iso3: string;
  iso2: string | null;
  name: string;
  region: string | null;
  subregion: string | null;
  population: number | null;
  population_year: number | null;
  centroid_lat: number | null;
  centroid_lon: number | null;
  has_reported_outbreak: boolean;
  diseases?: string[];
  inbound_flow_count: number;
}

export interface CountryListResponse {
  total: number;
  items: Country[];
}

export interface Route {
  origin_iso3: string;
  origin_name: string;
  dest_iso3: string;
  dest_name: string;
  passengers_per_day: number;
  value_type: ValueType;
  source: string;
  reference_period: string | null;
  uncertainty_factor: number | null;
  direct_route_count: number | null;
  origin_lat: number | null;
  origin_lon: number | null;
  dest_lat: number | null;
  dest_lon: number | null;
}

export interface RouteListResponse {
  total: number;
  items: Route[];
}

export interface LocalPresence {
  status: PresenceStatus;
  value_type: ValueType;
  last_reported_at: string | null;
  cases_confirmed: Quantity | null;
  deaths: Quantity | null;
  report_count: number;
  source_urls: string[];
  detail: string;
  unavailable_reason: string | null;
}

export interface OriginContribution {
  origin_iso3: string;
  origin_name: string;
  arrival_rate_per_day: number;
  share_of_total: number;
  passengers_per_day: number;
  passengers_value_type: ValueType;
  passengers_source: string;
  prevalence_central: number;
  prevalence_per_100k: number;
  prevalence_value_type: ValueType;
  effective_distance: number | null;
  via_hubs: string[];
  reported_cases: number | null;
  report_url: string | null;
  report_published_at: string | null;
}

export interface ImportationRisk {
  probability: BandedQuantity;
  arrival_rate_per_day: BandedQuantity;
  horizon_days: number;
  is_saturated: boolean;
  origin_count_considered: number;
  origin_count_usable: number;
  top_origins: OriginContribution[];
  excluded_origins: Record<string, string>[];
}

export interface EstablishmentRisk {
  probability_per_introduction: BandedQuantity;
  probability_within_horizon: BandedQuantity;
  horizon_days: number;
  reproduction_number_used: BandedQuantity;
  dispersion_used: BandedQuantity;
  subcritical: boolean;
  detail: string;
}

export interface ScenarioMarker {
  key: string;
  label: string;
  day_offset: number | null;
  date: string | null;
  threshold: number;
  reached: boolean;
  detail: string;
}

export interface DiseaseOption {
  disease_label: string;
  pathogen_key: string | null;
  country_count: number;
  report_count: number;
  latest_published_at: string | null;
}

export interface PathogenSummary {
  key: string | null;
  label: string;
  disease_key?: string | null;
  disease_name?: string | null;
  disease_label?: string | null;
  disease_family?: string | null;
  disease_source?: string | null;
  confidence: string | null;
  establishment_estimable: boolean;
  establishment_note: string | null;
  references: string[];
}

export interface RiskResponse {
  destination_iso3: string;
  destination_name: string;
  pathogen: PathogenSummary;
  horizon_days: number;
  computed_at: string;
  model_version: string;
  presence: LocalPresence;
  importation: ImportationRisk;
  establishment: EstablishmentRisk;
  scenario_markers: ScenarioMarker[];
  assumptions: Assumption[];
  warnings: ResponseWarning[];
  data: DataFreshness[];
  disclaimer: string;
}

export interface DataSource {
  key: string;
  name: string;
  kind: string;
  url: string | null;
  coverage: string;
  licence: string;
  limitations: string[];
  fields_used: string[];
  retrieved_at: string | null;
  record_count: number | null;
  notes: string | null;
}

export interface SourceListResponse {
  items: DataSource[];
}

export interface GravityModel {
  fitted_at: string;
  specification: string;
  training_source: string;
  training_period: string | null;
  n_train: number;
  n_test: number;
  random_seed: number;
  intercept: number;
  coefficients: Record<string, number>;
  metrics: Record<string, number>;
  residual_sigma_log10: number;
  uncertainty_factor: number;
  notes: Record<string, unknown> | null;
  caveat: string;
}

export interface IngestionRun {
  id: string;
  source: string;
  mode: string;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  records_seen: number;
  records_created: number;
  records_updated: number;
  records_skipped: number;
  observations_created: number;
  observations_unverified: number;
  error_code: string | null;
  error_message: string | null;
  detail: Record<string, unknown> | null;
}

export interface ComponentHealth {
  name: string;
  status: 'ok' | 'degraded' | 'unavailable' | 'not_configured';
  detail: string | null;
}

export interface HealthResponse {
  status: 'ok' | 'degraded' | 'unavailable';
  version: string;
  environment: string;
  checked_at: string;
  components: ComponentHealth[];
  data: DataFreshness[];
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details: { field: string | null; message: string }[];
}

export interface RiskParams {
  pathogen?: string | undefined;
  disease?: string | undefined;
  disease_key?: string | undefined;
  horizon_days?: number;
  underreporting_low?: number;
  underreporting_central?: number;
  underreporting_high?: number;
  alpha?: number | undefined;
  sigma?: number;
  reproduction_number?: number | undefined;
  dispersion_k?: number | undefined;
  passenger_scale?: number;
  threshold?: number;
  max_origins?: number;
}

export interface DiseaseHistory {
  disease_key: string;
  disease_name: string;
  disease_family: string | null;
  pathogen_key: string | null;
  report_count: number;
  country_count: number;
  grounded_country_count: number;
  first_published_at: string | null;
  last_published_at: string | null;
  cases_confirmed: number | null;
  deaths: number | null;
  source_labels: string[];
}

export interface CountrySpread {
  country_iso3: string;
  country_name: string;
  centroid_lat: number | null;
  centroid_lon: number | null;
  report_count: number;
  first_published_at: string | null;
  last_published_at: string | null;
  cases_confirmed: number | null;
  deaths: number | null;
  grounded: boolean;
  report_url: string | null;
  report_title: string | null;
  arrival_order: number;
}

export interface DiseaseTimelinePoint {
  year: number;
  report_count: number;
  country_count: number;
  new_country_count: number;
  cumulative_country_count: number;
  new_countries: string[];
  cases_confirmed: number | null;
  deaths: number | null;
}

export interface DiseaseSpread {
  disease_key: string;
  disease_name: string;
  disease_family: string | null;
  pathogen_key: string | null;
  report_count: number;
  country_count: number;
  first_published_at: string | null;
  last_published_at: string | null;
  cases_confirmed: number | null;
  deaths: number | null;
  is_active: boolean;
  countries: CountrySpread[];
  timeline: DiseaseTimelinePoint[];
  note: string;
}

export interface CountryDisease {
  disease_key: string;
  disease_name: string;
  disease_family: string | null;
  pathogen_key: string | null;
  report_count: number;
  first_published_at: string | null;
  last_published_at: string | null;
  cases_confirmed: number | null;
  deaths: number | null;
  grounded: boolean;
  is_active: boolean;
  report_url: string | null;
}

export interface CountryProfile {
  iso3: string;
  name: string;
  region: string | null;
  subregion: string | null;
  population: number | null;
  centroid_lat: number | null;
  centroid_lon: number | null;
  inbound_flow_count: number;
  report_count: number;
  active_disease_count: number;
  diseases: CountryDisease[];
}
