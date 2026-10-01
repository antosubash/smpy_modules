import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, describeError } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('describeError', () => {
  it('explains the seat guard with numbers', () => {
    expect(describeError('too_many_members', { used: 5, limit: 2 })).toBe(
      'That plan allows 2 seats and you use 5 — remove 3 first.',
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
    const [, write] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const [, read] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect((write.headers as Record<string, string>)['X-CSRF-Token']).toBe('tok');
    expect(write.method).toBe('POST');
    expect((read.headers as Record<string, string>)['X-CSRF-Token']).toBeUndefined();
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
});
