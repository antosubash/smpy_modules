// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { startHostAnalytics } from './hostTracker';
import { track } from './tracker';

afterEach(() => vi.unstubAllGlobals());
it('clears tracking during navigation and discards a stale tenant configuration', async () => {
  let navigate = (_url: string) => {};
  let resolveFirst = (_response: Response) => {};
  const first = new Promise<Response>((resolve) => {
    resolveFirst = resolve;
  });
  const config = {
    properties: [
      {
        id: 'tenant-a',
        kind: 'public',
        route_patterns: ['/p/:slug'],
        utm_parameters: [],
        event_allowlist: {},
      },
    ],
  };
  const fetcher = vi
    .fn()
    .mockReturnValueOnce(first)
    .mockResolvedValueOnce(Response.json({ properties: [] }));
  vi.stubGlobal('fetch', fetcher);
  const stop = startHostAnalytics((callback) => {
    navigate = callback;
    return () => {};
  }, 'http://localhost:3000/p/one');
  navigate('http://localhost:3000/p/two');
  await new Promise((resolve) => setTimeout(resolve, 0));
  resolveFirst(Response.json(config));
  await new Promise((resolve) => setTimeout(resolve, 0));
  await track('test', {});
  expect(fetcher).toHaveBeenCalledTimes(2);
  stop();
});
it('does not request config for a hash-only change and stops cleanly', async () => {
  let navigate = (_url: string) => {};
  const unsubscribe = vi.fn();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ properties: [] })));
  const stop = startHostAnalytics((callback) => {
    navigate = callback;
    return unsubscribe;
  }, 'http://localhost:3000/p/one');
  navigate('http://localhost:3000/p/one#anchor');
  expect(fetch).toHaveBeenCalledTimes(1);
  stop();
  expect(unsubscribe).toHaveBeenCalledOnce();
});

it('refreshes configuration when a tenant switch navigates to the same URL', async () => {
  let navigate = (_url: string) => {};
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ properties: [] })));
  const stop = startHostAnalytics((callback) => {
    navigate = callback;
    return () => {};
  }, 'http://localhost:3000/p/one');
  navigate('http://localhost:3000/p/one');
  expect(fetch).toHaveBeenCalledTimes(2);
  stop();
});
