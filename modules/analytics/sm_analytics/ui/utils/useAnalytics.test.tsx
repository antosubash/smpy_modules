// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { useAnalytics } from './useAnalytics';

vi.mock('@inertiajs/react', () => ({ router: { on: () => () => {} } }));
(globalThis as unknown as { React: unknown }).React = React;
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let select = (_id: string) => {};
function Probe() {
  const data = useAnalytics();
  select = data.setSelected;
  return <span>{data.report?.totals.pageviews ?? 'loading'}</span>;
}
it('does not paint a previous property report after selection changes', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  let resolveOld = (_value: Response) => {};
  const old = new Promise<Response>((resolve) => {
    resolveOld = resolve;
  });
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.endsWith('/properties'))
        return Promise.resolve(Response.json([{ id: 'a' }, { id: 'b' }]));
      if (url.endsWith('/status'))
        return Promise.resolve(Response.json({ geo: { enabled: false } }));
      if (url.includes('/a/report')) return old;
      return Promise.resolve(Response.json({ totals: { pageviews: 2 } }));
    }),
  );
  try {
    await act(async () => {
      root.render(<Probe />);
    });
    await act(async () => {
      select('b');
    });
    expect(container.textContent).toBe('2');
    await act(async () => {
      resolveOld(Response.json({ totals: { pageviews: 99 } }));
    });
    expect(container.textContent).toBe('2');
  } finally {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  }
});

it('lets a report finish when it takes longer than the polling interval', async () => {
  vi.useFakeTimers();
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  let resolveReport = (_value: Response) => {};
  const pending = new Promise<Response>((resolve) => {
    resolveReport = resolve;
  });
  let reportSignal: AbortSignal | undefined;
  const fetcher = vi.fn((url: string, options: RequestInit) => {
    if (url.endsWith('/properties')) return Promise.resolve(Response.json([{ id: 'a' }]));
    if (url.endsWith('/status')) return Promise.resolve(Response.json({ geo: { enabled: false } }));
    reportSignal = options.signal as AbortSignal;
    return pending;
  });
  vi.stubGlobal('fetch', fetcher);
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  try {
    await act(async () => {
      root.render(<Probe />);
    });
    await act(async () => {
      vi.advanceTimersByTime(120000);
    });
    expect(fetcher.mock.calls.filter(([url]) => url.includes('/report'))).toHaveLength(1);
    expect(reportSignal?.aborted).toBe(false);
    await act(async () => {
      resolveReport(Response.json({ totals: { pageviews: 7 } }));
    });
    expect(container.textContent).toBe('7');
    await act(async () => {
      vi.advanceTimersByTime(30000);
    });
    expect(fetcher.mock.calls.filter(([url]) => url.includes('/report'))).toHaveLength(2);
  } finally {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  }
});
