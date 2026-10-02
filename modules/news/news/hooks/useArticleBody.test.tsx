// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useArticleBody } from './useArticleBody';

// Lets `act` know this is a React test environment.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const STALE =
  'This article was changed somewhere else. Reload to get the latest version, then make your change again.';

type Api = ReturnType<typeof useArticleBody>;

function detail(updated_at: string, body: Record<string, unknown> = {}) {
  return { id: 7, title: 'T', status: 'draft', updated_at, draft_data: body };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('useArticleBody — stale writes', () => {
  let api: Api;
  let calls: { url: string; method: string; body: Record<string, unknown> | null }[];
  let responder: (url: string, method: string) => Response;

  function Harness() {
    api = useArticleBody(7);
    return null;
  }

  beforeEach(() => {
    calls = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
        return responder(url, method);
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  async function mount() {
    const root = createRoot(document.createElement('div'));
    await act(async () => root.render(<Harness />));
    await act(async () => {
      await api.load();
    });
    return root;
  }

  it('sends the last-known updated_at, refreshes it from the response, and 409 keeps the edit', async () => {
    let saves = 0;
    responder = (_url, method) => {
      if (method === 'GET') return json(detail('2026-01-01T00:00:00Z'));
      saves += 1;
      return saves === 1 ? json(detail('2026-01-01T00:00:05Z')) : json({ detail: STALE }, 409);
    };
    const root = await mount();
    const edit = (n: number) => ({ content: [], root: { props: {} }, zones: { n } }) as never;

    await act(async () => api.change(edit(1)));
    await act(async () => {
      await api.saveNow();
    });
    expect(calls.at(-1)?.body?.expected_updated_at).toBe('2026-01-01T00:00:00Z');

    await act(async () => api.change(edit(2)));
    await act(async () => {
      await api.saveNow();
    });
    // Updated from the previous write's response, not from the first load.
    expect(calls.at(-1)?.body?.expected_updated_at).toBe('2026-01-01T00:00:05Z');
    expect(api.conflict).toBe(true);
    expect(api.error).toBe(STALE);
    // The writer's edit is still on screen.
    expect((api.data as unknown as { zones: { n: number } }).zones.n).toBe(2);

    // Nothing further is sent until Reload — no silent overwrite.
    const before = calls.length;
    await act(async () => {
      await api.saveNow();
    });
    expect(calls.length).toBe(before);

    responder = () => json(detail('2026-01-01T00:01:00Z', { zones: { n: 9 } }));
    await act(async () => {
      await api.reload();
    });
    expect(api.conflict).toBe(false);
    expect(api.error).toBeNull();
    await act(async () => root.unmount());
  });

  it('publishes once however many times it is clicked', async () => {
    responder = (url, method) =>
      method === 'POST'
        ? json(detail('2026-01-01T00:00:09Z'))
        : json(detail('2026-01-01T00:00:00Z'));
    const root = await mount();

    await act(async () => {
      await Promise.all([api.publish(), api.publish(), api.publish(), api.publish()]);
    });

    expect(calls.filter((c) => c.method === 'POST' && c.url.endsWith('/publish'))).toHaveLength(1);
    await act(async () => root.unmount());
  });
});
