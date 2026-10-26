// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { withBlockIds } from '../components/body/blockIds';
import { articleOutline } from '../components/body/blocks/outline';
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

  it('repairs block ids on load the way the public page does, and saves them (#266)', async () => {
    // Written through the API: two headings without ids, one id twice.
    const stored = {
      root: { props: {} },
      content: [
        { type: 'Heading', props: { text: 'Background', level: '2' } },
        { type: 'Heading', props: { id: 'dup', text: 'Background', level: '2' } },
        { type: 'Paragraph', props: { id: 'dup', text: 'x', lead: false } },
        { type: 'Heading', props: { text: 'Background 2', level: '2' } },
      ],
    };
    responder = (_url, method) =>
      method === 'GET' ? json(detail('2026-01-01T00:00:00Z', stored)) : json(detail('t2'));
    const root = await mount();

    const blocks = (api.data?.content ?? []) as { props: { id: string } }[];
    const ids = blocks.map((block) => block.props.id);
    expect(ids.every(Boolean)).toBe(true);
    expect(new Set(ids).size).toBe(ids.length);
    // The canvas's outline is the published page's, entry for entry.
    const canvas = articleOutline(api.data);
    expect(canvas).toEqual(articleOutline(withBlockIds(stored)));
    expect(canvas.map((entry) => entry.anchor)).toEqual([
      'background',
      'background-2',
      'background-2-2',
    ]);
    expect(new Set(canvas.map((entry) => entry.blockId)).size).toBe(3);
    // Opening is not an edit; the first real save carries the ids.
    expect(api.dirty).toBe(false);
    await act(async () => api.change({ ...(api.data as object), zones: {} } as never));
    await act(async () => {
      await api.saveNow();
    });
    const saved = calls.at(-1)?.body?.draft_data as { content: { props: { id: string } }[] };
    expect(saved.content.map((block) => block.props.id)).toEqual(ids);
    await act(async () => root.unmount());
  });
});
