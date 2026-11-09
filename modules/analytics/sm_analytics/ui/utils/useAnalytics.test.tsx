// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import type { Filters } from './types';
import { useAnalytics } from './useAnalytics';

const navigation = vi.hoisted(() => ({ handler: () => {} }));
vi.mock('@inertiajs/react', () => ({
  router: {
    on: (_name: string, handler: () => void) => {
      navigation.handler = handler;
      return () => {};
    },
  },
}));
(globalThis as unknown as { React: unknown }).React = React;
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let select = (_id: string) => {};
let reload = () => {};
let filter = (_filters: (current: Filters) => Filters) => {};
const renders: { selected: string; path: string; pages: number | null }[] = [];
function Probe() {
  const data = useAnalytics();
  select = data.setSelected;
  reload = data.reload;
  filter = data.setFilters;
  renders.push({
    selected: data.selected,
    path: data.filters.path,
    pages: data.report?.totals.pageviews ?? null,
  });
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

it('keeps a successful same-scope report mounted during manual and polling refreshes', async () => {
  vi.useFakeTimers();
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  let calls = 0;
  let finish = (_response: Response) => {};
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.endsWith('/properties')) return Promise.resolve(Response.json([{ id: 'a' }]));
      if (url.endsWith('/status'))
        return Promise.resolve(Response.json({ geo: { enabled: false } }));
      calls++;
      if (calls === 1) return Promise.resolve(Response.json({ totals: { pageviews: 3 } }));
      return new Promise<Response>((resolve) => {
        finish = resolve;
      });
    }),
  );
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  try {
    await act(async () => root.render(<Probe />));
    expect(container.textContent).toBe('3');
    await act(async () => reload());
    expect(calls).toBe(2);
    expect(container.textContent).toBe('3');
    await act(async () => finish(Response.json({ totals: { pageviews: 4 } })));
    expect(container.textContent).toBe('4');
    await act(async () => vi.advanceTimersByTime(30000));
    expect(calls).toBe(3);
    expect(container.textContent).toBe('4');
  } finally {
    await act(async () => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  }
});

it.each(['property', 'filter'])(
  'hides a loaded report synchronously when the %s scope changes',
  async (kind) => {
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/properties'))
          return Promise.resolve(Response.json([{ id: 'a' }, { id: 'b' }]));
        if (url.endsWith('/status'))
          return Promise.resolve(Response.json({ geo: { enabled: false } }));
        if (url.includes('/a/report') && !url.includes('path='))
          return Promise.resolve(Response.json({ totals: { pageviews: 5 } }));
        return new Promise<Response>(() => {});
      }),
    );
    try {
      await act(async () => root.render(<Probe />));
      expect(container.textContent).toBe('5');
      renders.length = 0;
      await act(async () => {
        if (kind === 'property') select('b');
        else filter((current) => ({ ...current, path: '/new' }));
      });
      expect(renders[0]?.pages).toBeNull();
      expect(container.textContent).toBe('loading');
    } finally {
      await act(async () => root.unmount());
      container.remove();
      vi.unstubAllGlobals();
    }
  },
);

it('forgets the previous tenant snapshot on navigation even when the same property id returns', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  let reports = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.endsWith('/properties')) return Promise.resolve(Response.json([{ id: 'a' }]));
      if (url.endsWith('/status'))
        return Promise.resolve(Response.json({ geo: { enabled: false } }));
      reports++;
      return reports === 1
        ? Promise.resolve(Response.json({ totals: { pageviews: 6 } }))
        : new Promise<Response>(() => {});
    }),
  );
  try {
    await act(async () => root.render(<Probe />));
    expect(container.textContent).toBe('6');
    renders.length = 0;
    await act(async () => navigation.handler());
    expect(renders.every((render) => render.pages === null)).toBe(true);
    expect(container.textContent).toBe('loading');
  } finally {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  }
});
