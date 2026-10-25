// @vitest-environment happy-dom
import * as React from 'react';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useUsageDetail } from './useUsageDetail';

(globalThis as unknown as { React: unknown }).React = React;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const HOLD = {
  id: 'h1',
  meter: 'demo.jobs',
  quantity: 1,
  status: 'held',
  idempotency_key: 'k',
  source: 's',
  expires_at: null,
  created_at: '2026-10-01T00:00:00Z',
  settled_at: null,
};
const LEDGER = { items: [], total: 0, page: 1, per_page: 20, pages: 1 };

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

let detail: ReturnType<typeof useUsageDetail> | undefined;

function Harness() {
  detail = useUsageDetail('t1', 'csrf');
  return null;
}

describe('useUsageDetail', () => {
  let root: Root | undefined;

  afterEach(() => {
    act(() => root?.unmount());
    vi.unstubAllGlobals();
    detail = undefined;
  });

  async function mount(fetcher: (url: string) => Promise<Response>) {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => fetcher(url)),
    );
    root = createRoot(document.createElement('div'));
    await act(async () => root?.render(<Harness />));
  }

  it('hides the last filter’s holds the moment the filter changes, and after a failure', async () => {
    let fail = false;
    let release: (() => void) | undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    await mount(async (url) => {
      if (fail) {
        await gate;
        return json({ detail: 'boom' }, 500);
      }
      return url.includes('/holds') ? json([HOLD]) : json(LEDGER);
    });
    expect(detail?.holds?.map((h) => h.id)).toEqual(['h1']);
    expect(detail?.failed).toBe(false);

    fail = true;
    await act(async () => detail?.setMeter('demo.exports'));
    // In flight: nothing from the old query is shown.
    expect(detail?.holds).toBeNull();
    expect(detail?.ledger).toBeNull();

    await act(async () => {
      release?.();
      await gate;
    });
    expect(detail?.holds).toBeNull();
    expect(detail?.ledger).toBeNull();
    expect(detail?.failed).toBe(true);
  });

  it('drops the rows when a refresh of the same query fails', async () => {
    let fail = false;
    await mount((url) => {
      if (fail) return json({ detail: 'boom' }, 500);
      return url.includes('/holds') ? json([HOLD]) : json(LEDGER);
    });
    expect(detail?.holds).toHaveLength(1);
    fail = true;
    await act(async () => detail?.refresh());
    expect(detail?.holds).toBeNull();
    expect(detail?.failed).toBe(true);

    fail = false;
    await act(async () => detail?.refresh());
    expect(detail?.holds).toHaveLength(1);
    expect(detail?.failed).toBe(false);
  });
});
