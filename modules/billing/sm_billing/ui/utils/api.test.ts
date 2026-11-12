import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, describeError } from './api';

const ORIGIN = 'http://billing.test';

// `apiFetch` resolves a path against the page's location, which a node test lacks.
beforeEach(() => vi.stubGlobal('location', { href: `${ORIGIN}/billing/`, origin: ORIGIN }));
afterEach(() => vi.unstubAllGlobals());

describe('describeError', () => {
  it('explains the seat guard with numbers', () => {
    expect(describeError('too_many_members', { used: 5, limit: 2 })).toBe(
      'That plan allows 2 seats and you use 5 — remove 3 first.',
    );
  });
  it('says the return URL origin is missing (#355)', () => {
    expect(describeError('return_base_url_missing')).toBe(
      'Online payment is not fully set up: the site administrator has to set the return URL origin first.',
    );
  });
  it('falls back for unknown codes', () => {
    expect(describeError('weird')).toBe('Something went wrong. Please try again.');
  });
});

describe('api', () => {
  it('sends the CSRF header on writes only', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ url: 'x' })));
    vi.stubGlobal('fetch', fetchMock);
    await api('/a', 'tok', { body: { plan_id: 1 } });
    await api('/b', 'tok');
    // `apiFetch` hands `fetch` one `Request`.
    const [write] = fetchMock.mock.calls[0] as unknown as [Request];
    const [read] = fetchMock.mock.calls[1] as unknown as [Request];
    expect(write.headers.get('X-CSRF-Token')).toBe('tok');
    expect(write.method).toBe('POST');
    expect(write.headers.get('Content-Type')).toBe('application/json');
    expect(await write.json()).toEqual({ plan_id: 1 });
    expect(read.headers.get('X-CSRF-Token')).toBeNull();
    expect(read.url).toBe(`${ORIGIN}/b`);
  });

  it('throws ApiError with the server detail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'plan_is_free' }), { status: 400 })),
    );
    await expect(api('/a', 't', { body: {} })).rejects.toMatchObject({
      status: 400,
      detail: 'plan_is_free',
      message: 'The free plan needs no checkout.',
    });
    expect(ApiError).toBeDefined();
  });

  it('reads a FastAPI validation error list', async () => {
    const detail = [
      { loc: ['body', 'trial_days'], msg: 'Input should be less than or equal to 730' },
    ];
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail }), { status: 422 })),
    );
    await expect(api('/a', 't', { body: {} })).rejects.toMatchObject({
      status: 422,
      detail: 'validation_error',
      message: 'trial_days: Input should be less than or equal to 730.',
    });
  });

  it('reads an unreachable server as status 0', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    await expect(api('/a', 't')).rejects.toMatchObject({ status: 0, detail: 'http_0' });
  });
});
