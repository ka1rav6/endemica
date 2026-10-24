import type { ApiErrorBody } from '@/types/api';

const DEFAULT_TIMEOUT_MS = 30_000;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: { field: string | null; message: string }[];

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code;
    this.details = body.details;
  }
}

export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NetworkError';
  }
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.code === 'string' && typeof candidate.message === 'string';
}

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

function buildQuery(params: Record<string, unknown> | undefined): string {
  if (!params) return '';
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    if (typeof value === 'string') {
      search.set(key, value);
    } else if (typeof value === 'number' || typeof value === 'boolean') {
      search.set(key, value.toString());
    } else {
      search.set(key, JSON.stringify(value));
    }
  }
  const query = search.toString();
  return query ? `?${query}` : '';
}

export async function apiGet<T>(
  path: string,
  params?: Record<string, unknown>,
  options?: RequestOptions,
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => {
    controller.abort();
  }, options?.timeoutMs ?? DEFAULT_TIMEOUT_MS);

  if (options?.signal) {
    options.signal.addEventListener('abort', () => {
      controller.abort();
    });
  }

  let response: Response;
  try {
    response = await fetch(`${path}${buildQuery(params)}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
  } catch (cause) {
    if (controller.signal.aborted && !options?.signal?.aborted) {
      throw new NetworkError('The request timed out.');
    }
    throw new NetworkError(
      cause instanceof Error ? cause.message : 'The backend could not be reached.',
    );
  } finally {
    clearTimeout(timeout);
  }

  let payload: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      throw new NetworkError('The backend returned a response that was not valid JSON.');
    }
  }

  if (!response.ok) {
    if (isApiErrorBody(payload)) {
      throw new ApiError(response.status, payload);
    }
    throw new ApiError(response.status, {
      code: 'unexpected_error',
      message: `The backend returned HTTP ${response.status}.`,
      details: [],
    });
  }

  return payload as T;
}

export async function apiPost<T>(
  path: string,
  body?: unknown,
  options?: RequestOptions,
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => {
    controller.abort();
  }, options?.timeoutMs ?? 300_000);

  let response: Response;
  try {
    response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (cause) {
    if (controller.signal.aborted) throw new NetworkError('The request timed out.');
    throw new NetworkError(
      cause instanceof Error ? cause.message : 'The backend could not be reached.',
    );
  } finally {
    clearTimeout(timeout);
  }

  const text = await response.text();
  const payload: unknown = text ? JSON.parse(text) : null;

  if (!response.ok) {
    if (isApiErrorBody(payload)) throw new ApiError(response.status, payload);
    throw new ApiError(response.status, {
      code: 'unexpected_error',
      message: `The backend returned HTTP ${response.status}.`,
      details: [],
    });
  }
  return payload as T;
}
