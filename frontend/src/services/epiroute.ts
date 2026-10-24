import { apiGet, apiPost } from '@/services/client';
import type {
  CountryListResponse,
  CountryProfile,
  DiseaseHistory,
  DiseaseSpread,
  GravityModel,
  HealthResponse,
  IngestionRun,
  DiseaseOption,
  OutbreakListResponse,
  OutbreakReportDetail,
  PathogenSummary,
  RiskParams,
  RiskResponse,
  RouteListResponse,
  SourceListResponse,
} from '@/types/api';

const V1 = '/api/v1';

export const getHealth = (signal?: AbortSignal): Promise<HealthResponse> =>
  apiGet<HealthResponse>('/health', undefined, signal ? { signal } : undefined);

export const getCountries = (signal?: AbortSignal): Promise<CountryListResponse> =>
  apiGet<CountryListResponse>(`${V1}/countries`, undefined, signal ? { signal } : undefined);

export const getOutbreaks = (
  params: { limit?: number; offset?: number; pathogen?: string; country?: string } = {},
  signal?: AbortSignal,
): Promise<OutbreakListResponse> =>
  apiGet<OutbreakListResponse>(`${V1}/outbreaks`, params, signal ? { signal } : undefined);

export const getOutbreak = (id: string, signal?: AbortSignal): Promise<OutbreakReportDetail> =>
  apiGet<OutbreakReportDetail>(
    `${V1}/outbreaks/${encodeURIComponent(id)}`,
    undefined,
    signal ? { signal } : undefined,
  );

export const getRoutes = (
  params: { origin?: string; dest?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<RouteListResponse> =>
  apiGet<RouteListResponse>(`${V1}/routes`, params, signal ? { signal } : undefined);

export const getRisk = (
  destinationIso3: string,
  params: RiskParams = {},
  signal?: AbortSignal,
): Promise<RiskResponse> =>
  apiGet<RiskResponse>(
    `${V1}/risk/${encodeURIComponent(destinationIso3)}`,
    params as Record<string, unknown>,
    signal ? { signal } : undefined,
  );

export const getSources = (signal?: AbortSignal): Promise<SourceListResponse> =>
  apiGet<SourceListResponse>(`${V1}/sources`, undefined, signal ? { signal } : undefined);

export const getDiseases = (signal?: AbortSignal): Promise<DiseaseOption[]> =>
  apiGet<DiseaseOption[]>(`${V1}/diseases`, undefined, signal ? { signal } : undefined);

export const getPathogens = (signal?: AbortSignal): Promise<PathogenSummary[]> =>
  apiGet<PathogenSummary[]>(`${V1}/pathogens`, undefined, signal ? { signal } : undefined);

export const getGravityModel = (signal?: AbortSignal): Promise<GravityModel> =>
  apiGet<GravityModel>(`${V1}/model/gravity`, undefined, signal ? { signal } : undefined);

export const getRuns = (limit = 10, signal?: AbortSignal): Promise<IngestionRun[]> =>
  apiGet<IngestionRun[]>(`${V1}/runs`, { limit }, signal ? { signal } : undefined);

export interface IngestResult {
  run_id: string;
  mode: string;
  status: string;
  records_seen: number;
  records_created: number;
  records_updated: number;
  records_skipped: number;
  observations_created: number;
  observations_unverified: number;
  warning_codes: Record<string, number>;
  errors: string[];
}

export const triggerIngest = (limit = 20, useAgent = false): Promise<IngestResult> =>
  apiPost<IngestResult>(`${V1}/admin/ingest`, { limit, use_agent: useAgent });

export const getDiseaseHistory = (signal?: AbortSignal): Promise<DiseaseHistory[]> =>
  apiGet<DiseaseHistory[]>(`${V1}/diseases/history`, undefined, signal ? { signal } : undefined);

export const getDiseaseSpread = (
  diseaseKey: string,
  signal?: AbortSignal,
): Promise<DiseaseSpread> =>
  apiGet<DiseaseSpread>(
    `${V1}/diseases/${encodeURIComponent(diseaseKey)}/spread`,
    undefined,
    signal ? { signal } : undefined,
  );

export const getCountryProfile = (iso3: string, signal?: AbortSignal): Promise<CountryProfile> =>
  apiGet<CountryProfile>(
    `${V1}/countries/${encodeURIComponent(iso3)}/profile`,
    undefined,
    signal ? { signal } : undefined,
  );
