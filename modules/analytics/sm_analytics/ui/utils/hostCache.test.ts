// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { CONFIG_TTL_MS, FAILURE_BACKOFF_MS, startHostAnalytics } from './hostTracker';
import { track } from './tracker';

const config = {
  properties: [
    {
      id: 'one',
      kind: 'public',
      route_patterns: ['/p/:slug'],
      utm_parameters: [],
      event_allowlist: { download: [] },
    },
  ],
};
let navigate: (page: string | { url: string; component?: string; tenantId?: string }) => void;
let stop: () => void;
const flush = () => vi.advanceTimersByTimeAsync(0);
beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-11-26T12:00:00Z'));
});
afterEach(() => {
  stop?.();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
function start(
  initial: string | { url: string; component?: string; tenantId?: string } = '/p/one',
  options = {},
) {
  stop = startHostAnalytics(
    (callback) => {
      navigate = callback;
      return () => {};
    },
    initial,
    options,
  );
}
function mockConfig(value: unknown = { properties: [] }) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      Promise.resolve(
        url.endsWith('/config') ? Response.json(value) : new Response(null, { status: 204 }),
      ),
    ),
  );
}
const configs = () =>
  vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/config'));
const collected = () =>
  vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/collect'));

it.each([{ properties: [] }, config])(
  'reuses enabled or empty config across completed navigations: %j',
  async (value) => {
    mockConfig(value);
    start();
    await flush();
    for (const url of ['/p/two', '/p/three', '/p/three']) {
      navigate(url);
      await flush();
    }
    expect(configs()).toHaveLength(1);
    expect(collected()).toHaveLength(value.properties.length ? 4 : 0);
  },
);
it('refreshes expired config and picks up a newly enabled property', async () => {
  mockConfig();
  start();
  await flush();
  vi.mocked(fetch).mockImplementation((url) =>
    Promise.resolve(
      String(url).endsWith('/config') ? Response.json(config) : new Response(null, { status: 204 }),
    ),
  );
  await vi.advanceTimersByTimeAsync(CONFIG_TTL_MS - 1);
  navigate('/p/before-expiry');
  await flush();
  expect(configs()).toHaveLength(1);
  expect(collected()).toHaveLength(0);
  await vi.advanceTimersByTimeAsync(1);
  navigate('/p/two');
  await flush();
  expect(configs()).toHaveLength(2);
  expect(JSON.parse(String(collected()[0][1]?.body)).path).toBe('/p/two');
});
it.each(['network', 'http', 'malformed', 'timeout'])(
  'backs off after a %s failure then recovers',
  async (failure) => {
    const failed =
      failure === 'network'
        ? () => Promise.reject(new Error('offline'))
        : failure === 'timeout'
          ? (_url: unknown, init?: RequestInit) =>
              new Promise<Response>((_, reject) => {
                init?.signal?.addEventListener('abort', () =>
                  reject(new DOMException('Aborted', 'AbortError')),
                );
              })
          : () =>
              Promise.resolve(
                failure === 'http'
                  ? new Response(null, { status: 503 })
                  : Response.json({ properties: null }),
              );
    vi.stubGlobal('fetch', vi.fn(failed));
    start();
    await vi.advanceTimersByTimeAsync(failure === 'timeout' ? 3000 : 0);
    navigate('/p/two');
    navigate('/p/three');
    await flush();
    expect(configs()).toHaveLength(1);
    mockConfig(config);
    await vi.advanceTimersByTimeAsync(FAILURE_BACKOFF_MS - 1);
    navigate('/p/before-retry');
    await flush();
    expect(fetch).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    navigate('/p/four');
    await flush();
    expect(configs()).toHaveLength(1);
    expect(collected()).toHaveLength(1);
  },
);
it('shares an in-flight config and only tracks the latest navigation', async () => {
  let finish = (_response: Response) => {};
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValue(new Response(null, { status: 204 })),
  );
  start();
  navigate('/p/two');
  navigate('/p/three');
  expect(configs()).toHaveLength(1);
  finish(Response.json(config));
  await flush();
  expect(collected()).toHaveLength(1);
  expect(JSON.parse(String(collected()[0][1]?.body)).path).toBe('/p/three');
});
it('never uses a config for a different tenant or host origin', async () => {
  mockConfig(config);
  start({ url: '/p/one', tenantId: 'a' });
  await flush();
  navigate({ url: '/p/two', tenantId: 'b' });
  await flush();
  expect(configs()).toHaveLength(2);
  navigate('https://other.example/p/three');
  await flush();
  expect(configs()).toHaveLength(2);
  expect(collected()).toHaveLength(2);
});
it('applies shouldTrack on first load and navigation, clearing custom events on skipped pages', async () => {
  mockConfig(config);
  const shouldTrack = vi.fn((page: { component?: string }) => page.component !== 'Errors/NotFound');
  start({ url: '/p/missing', component: 'Errors/NotFound' }, { shouldTrack });
  await flush();
  expect(fetch).not.toHaveBeenCalled();
  navigate({ url: '/p/found', component: 'Public/Page' });
  await flush();
  expect(collected()).toHaveLength(1);
  navigate({ url: '/p/missing', component: 'Errors/NotFound' });
  await track('download');
  expect(collected()).toHaveLength(1);
  expect(shouldTrack).toHaveBeenCalledTimes(3);
  expect(shouldTrack.mock.calls[0][0]).toMatchObject({
    path: '/p/missing',
    component: 'Errors/NotFound',
  });
});
it('discards a pending response after a skipped navigation or teardown', async () => {
  let finish = (_response: Response) => {};
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    ),
  );
  start('/p/one', { shouldTrack: (page: { path: string }) => page.path !== '/p/missing' });
  navigate('/p/missing');
  finish(Response.json(config));
  await flush();
  await track('download');
  expect(collected()).toHaveLength(0);
  stop();
});

it('ignores a config response that finishes after teardown', async () => {
  let finish = (_response: Response) => {};
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    ),
  );
  start();
  stop();
  finish(Response.json(config));
  await flush();
  await track('download');
  expect(collected()).toHaveLength(0);
});
it('passes a supplied status and normalized path to shouldTrack', async () => {
  mockConfig(config);
  const shouldTrack = vi.fn((page: { status?: number }) => page.status !== 404);
  stop = startHostAnalytics(
    () => () => {},
    { url: '/p/missing?secret=x', status: 404 },
    { shouldTrack },
  );
  await flush();
  expect(shouldTrack.mock.calls[0][0]).toMatchObject({
    url: 'http://localhost:3000/p/missing?secret=x',
    path: '/p/missing',
    status: 404,
  });
  expect(fetch).not.toHaveBeenCalled();
});
it('applies the page policy when a component changes with only the fragment', async () => {
  mockConfig(config);
  start(
    { url: '/p/one', component: 'Public/Page' },
    {
      shouldTrack: (page: { component?: string }) => page.component !== 'Errors/NotFound',
    },
  );
  await flush();
  navigate({ url: '/p/one#missing', component: 'Errors/NotFound' });
  await track('download');
  expect(collected()).toHaveLength(1);
  navigate({ url: '/p/one#found', component: 'Public/Page' });
  await flush();
  expect(collected()).toHaveLength(2);
});
