import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, request } from './client.js';

afterEach(() => vi.unstubAllGlobals());

describe('request', () => {
  it('returns parsed JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{"a":1}', { status: 200 })),
    );
    await expect(request('/api/x')).resolves.toEqual({ a: 1 });
  });

  it('sends a JSON body with the content type', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await request('/api/x', { method: 'POST', body: { b: 2 } });
    const init = fetchMock.mock.calls[0][1];
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{"b":2}');
    expect(init.headers['Content-Type']).toBe('application/json');
  });

  it('turns an error response into an ApiError with the server message', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{"error":"nope"}', { status: 403 })),
    );
    await expect(request('/api/x')).rejects.toMatchObject({ message: 'nope', status: 403 });
  });

  it('reports an unreachable service as status 0', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Promise.reject(new TypeError('failed'))),
    );
    const error = await request('/api/x').catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
  });
});
