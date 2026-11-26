// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { useAnalytics } from './useAnalytics';

vi.mock('@inertiajs/react', () => ({ router: { on: () => () => {} } }));
(globalThis as unknown as { React: unknown }).React = React;
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

let reload = () => {};
function Probe() {
  const data = useAnalytics();
  reload = data.reload;
  return (
    <div>
      {data.error}
      {data.report?.totals.pageviews}
      {!data.loading && !data.properties.length ? 'empty' : ''}
    </div>
  );
}
it.each(['list', 'report'])(
  'forgets a stale dashboard and stops polling after a %s 401',
  async (source) => {
    vi.useFakeTimers();
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    vi.spyOn(window.location, 'assign').mockImplementation(() => {});
    let expired = false;
    const fetcher = vi.fn((url: string) => {
      const unauthorized =
        expired && (source === 'list' ? url.endsWith('/properties') : url.includes('/report'));
      return Promise.resolve(
        unauthorized
          ? Response.json({ detail: 'Not authenticated' }, { status: 401 })
          : Response.json(
              url.endsWith('/properties')
                ? [{ id: 'a' }]
                : url.endsWith('/status')
                  ? { geo: { enabled: false } }
                  : { totals: { pageviews: 9 } },
            ),
      );
    });
    vi.stubGlobal('fetch', fetcher);
    const container = document.createElement('div');
    const root = createRoot(container);
    try {
      await act(async () => root.render(<Probe />));
      expect(container.textContent).toBe('9');
      expired = true;
      await act(async () => reload());
      expect(window.location.assign).toHaveBeenCalled();
      expect(container.textContent).toBe('');
      const requests = fetcher.mock.calls.length;
      await act(async () => vi.advanceTimersByTime(90000));
      expect(fetcher.mock.calls).toHaveLength(requests);
    } finally {
      await act(async () => root.unmount());
    }
  },
);
