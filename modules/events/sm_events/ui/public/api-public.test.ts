import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../utils/api';
import { publicFetcher, publicUrl } from './api-public';

const query = {
  start: '2026-07-01T00:00:00Z',
  end: '2026-08-01T00:00:00Z',
  calendars: ['c1', 'c2'],
  categories: ['k1'],
  types: [],
  sources: [],
  locale: 'de',
};

afterEach(() => vi.unstubAllGlobals());

describe('publicUrl', () => {
  it('names the range, the filters and the language', () => {
    const url = new URL(publicUrl('/events/api/occurrences', query), 'http://x');
    expect(url.pathname).toBe('/events/api/occurrences');
    expect(url.searchParams.get('start')).toBe('2026-07-01T00:00:00Z');
    expect(url.searchParams.getAll('calendar')).toEqual(['c1', 'c2']);
    expect(url.searchParams.getAll('category')).toEqual(['k1']);
    expect(url.searchParams.get('locale')).toBe('de');
  });
});

describe('publicFetcher', () => {
  it('reads with same-origin credentials and the abort signal', async () => {
    const fetchMock = vi.fn(async () => Response.json({ items: [], truncated: false }));
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();
    const page = await publicFetcher('/events/api/occurrences')(query, controller.signal);
    expect(page).toEqual({ items: [], truncated: false });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.credentials).toBe('same-origin');
    expect(init.signal).toBe(controller.signal);
    expect(init.method ?? 'GET').toBe('GET');
  });

  it('aborts with the signal', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            );
          }),
      ),
    );
    const controller = new AbortController();
    const pending = publicFetcher('/x')(query, controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('throws ApiError with the envelope code on a refusal', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json({ detail: 'too long', code: 'range_too_long' }, { status: 422 }),
      ),
    );
    const error = await publicFetcher('/x')(query, new AbortController().signal).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, code: 'range_too_long' });
  });

  it('keeps the status as the code when the body is not JSON', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('nope', { status: 502 })),
    );
    const error = await publicFetcher('/x')(query, new AbortController().signal).catch((e) => e);
    expect(error).toMatchObject({ status: 502, code: '502' });
  });
});
