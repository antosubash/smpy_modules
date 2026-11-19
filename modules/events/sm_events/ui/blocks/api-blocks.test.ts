// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { stubFetch } from '../page-tests/support';
import { ApiError } from '../utils/api';
import { fetchBlockCalendars, fetchUpcoming } from './api-blocks';

afterEach(() => vi.unstubAllGlobals());

describe('fetchBlockCalendars', () => {
  it('asks the anonymous route for the slugs and the page language', async () => {
    const calls = stubFetch({
      'GET /api/events/public/calendars': {
        calendars: [],
        categories: [],
        default_timezone: 'UTC',
      },
    });
    const got = await fetchBlockCalendars(['a', 'b'], 'de', new AbortController().signal);
    expect(got.default_timezone).toBe('UTC');
    expect(calls[0].url).toBe('/api/events/public/calendars?calendar=a&calendar=b&locale=de');
  });

  it('sends no calendar parameter for no selection', async () => {
    const calls = stubFetch({
      'GET /api/events/public/calendars': {
        calendars: [],
        categories: [],
        default_timezone: 'UTC',
      },
    });
    await fetchBlockCalendars([], 'en', new AbortController().signal);
    expect(calls[0].url).toBe('/api/events/public/calendars?locale=en');
  });
});

describe('fetchUpcoming', () => {
  it('names the slugs, the category, the count and the language', async () => {
    const calls = stubFetch({ 'GET /api/events/public/upcoming': { items: [] } });
    await fetchUpcoming(
      { slugs: ['a'], category: 'talks', count: 5, locale: 'de' },
      new AbortController().signal,
    );
    expect(calls[0].url).toBe(
      '/api/events/public/upcoming?calendar=a&category=talks&count=5&locale=de',
    );
  });

  it('reads with same-origin credentials, and aborts with the signal', async () => {
    const seen: RequestInit[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init: RequestInit) => {
        seen.push(init);
        return new Promise((_resolve, reject) => {
          init.signal?.addEventListener('abort', () =>
            reject(new DOMException('aborted', 'AbortError')),
          );
        });
      }),
    );
    const controller = new AbortController();
    const pending = fetchUpcoming(
      { slugs: [], category: '', count: 3, locale: 'en' },
      controller.signal,
    );
    controller.abort();
    await expect(pending).rejects.toThrow(/abort/i);
    expect(seen[0].credentials).toBe('same-origin');
    expect(seen[0].signal).toBe(controller.signal);
  });

  it('throws ApiError on a refusal, with the module code', async () => {
    stubFetch({
      'GET /api/events/public/upcoming': () =>
        Response.json({ detail: 'x', code: 'invalid_query' }, { status: 422 }),
    });
    const error = await fetchUpcoming(
      { slugs: [], category: '', count: 3, locale: 'en' },
      new AbortController().signal,
    ).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, code: 'invalid_query' });
    stubFetch({ 'GET /api/events/public/upcoming': () => new Response('nope', { status: 404 }) });
    const gone = await fetchUpcoming(
      { slugs: [], category: '', count: 3, locale: 'en' },
      new AbortController().signal,
    ).catch((e) => e);
    expect(gone).toMatchObject({ status: 404, code: '404' });
  });
});
