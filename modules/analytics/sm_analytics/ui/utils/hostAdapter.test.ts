// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { startAnalytics } from '../../../../../host/client_app/analytics';

const callbacks = vi.hoisted(() => ({
  navigate: (_event: { detail: { type: string; page: { url: string } } }) => {},
}));
vi.mock('@inertiajs/react', () => ({
  router: {
    on: (_event: string, callback: typeof callbacks.navigate) => {
      callbacks.navigate = callback;
      return () => {};
    },
  },
}));
afterEach(() => vi.unstubAllGlobals());

it('records the initial page once even when Inertia emits its initial navigation after configuration', async () => {
  window.history.replaceState({}, '', 'http://localhost:3000/p/welcome');
  const config = {
    properties: [
      {
        id: 'one',
        kind: 'public',
        route_patterns: ['/p/:slug'],
        utm_parameters: [],
        event_allowlist: {},
      },
    ],
  };
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      Promise.resolve(
        url.endsWith('/config') ? Response.json(config) : new Response(null, { status: 204 }),
      ),
    ),
  );
  const stop = startAnalytics();
  try {
    await new Promise((resolve) => setTimeout(resolve, 0));
    callbacks.navigate({ detail: { type: 'initial', page: { url: '/p/welcome' } } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(
      vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/collect')),
    ).toHaveLength(1);
    callbacks.navigate({ detail: { type: 'visit', page: { url: '/p/welcome' } } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(
      vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith('/collect')),
    ).toHaveLength(2);
  } finally {
    stop();
  }
});
