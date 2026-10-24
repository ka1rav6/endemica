import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, NetworkError, apiGet } from '@/services/client';
import { describeError } from '@/lib/errors';

describe('apiGet', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function mockFetch(response: Response | Error) {
    const calls: string[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      calls.push(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url);
      return response instanceof Error ? Promise.reject(response) : Promise.resolve(response);
    });
    vi.stubGlobal('fetch', fetchMock);
    return { fetchMock, calls };
  }

  it('returns parsed JSON on success', async () => {
    mockFetch(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    await expect(apiGet<{ ok: boolean }>('/x')).resolves.toEqual({ ok: true });
  });

  it('serialises query parameters and omits empty ones', async () => {
    const { calls } = mockFetch(new Response('{}', { status: 200 }));
    await apiGet('/x', { a: 1, b: 'two', c: undefined, d: null, e: '' });
    const url = calls[0] ?? '';
    expect(url).toContain('a=1');
    expect(url).toContain('b=two');
    expect(url).not.toContain('c=');
    expect(url).not.toContain('d=');
    expect(url).not.toContain('e=');
  });

  it('raises ApiError carrying the structured error body', async () => {
    mockFetch(
      new Response(JSON.stringify({ code: 'not_found', message: 'nope', details: [] }), {
        status: 404,
      }),
    );
    await expect(apiGet('/x')).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      code: 'not_found',
    });
  });

  it('raises ApiError even when the body is not the expected envelope', async () => {
    mockFetch(new Response('<html>502</html>', { status: 502 }));
    await expect(apiGet('/x')).rejects.toBeInstanceOf(NetworkError);
  });

  it('raises NetworkError when the backend is unreachable', async () => {
    mockFetch(new TypeError('Failed to fetch'));
    await expect(apiGet('/x')).rejects.toBeInstanceOf(NetworkError);
  });

  it('raises NetworkError on a non-JSON success body', async () => {
    mockFetch(new Response('not json', { status: 200 }));
    await expect(apiGet('/x')).rejects.toBeInstanceOf(NetworkError);
  });

  it('tolerates an empty success body', async () => {
    mockFetch(new Response('', { status: 200 }));
    await expect(apiGet('/x')).resolves.toBeNull();
  });
});

describe('describeError', () => {
  it('tells the operator how to start the backend', () => {
    const message = describeError(new NetworkError('connection refused'));
    expect(message).toContain('just dev-backend');
    expect(message).toContain('snapshot-load');
  });

  it('tells the operator how to prepare datasets on a 409', () => {
    const message = describeError(
      new ApiError(409, { code: 'data_unavailable', message: 'missing table', details: [] }),
    );
    expect(message).toContain('just data-fetch');
  });

  it('reassures that cached data survives an upstream failure', () => {
    const message = describeError(
      new ApiError(502, { code: 'upstream_unavailable', message: 'WHO down', details: [] }),
    );
    expect(message).toContain('cached data is unaffected');
  });

  it('includes field-level validation detail', () => {
    const message = describeError(
      new ApiError(422, {
        code: 'invalid_request',
        message: 'bad input',
        details: [{ field: 'horizon_days', message: 'must be <= 365' }],
      }),
    );
    expect(message).toContain('must be <= 365');
  });
});
