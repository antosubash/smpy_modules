// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useTaxonomy } from './useTaxonomy';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Api = ReturnType<typeof useTaxonomy>;

function json(body: unknown, status = 200) {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

/** #174: how a refused tag rename or delete reaches the screen. The server's
 *  `detail` is what the banner shows, a refused rename resolves `false` so the
 *  inline editor stays open, and a refused delete rejects so the confirmation
 *  stays open — for a clash (409), a tag someone else removed (404) and a
 *  missing permission (403) alike. */
describe('useTaxonomy — tag rename and delete failures', () => {
  let api: Api;
  let calls: { url: string; method: string }[];
  let write: () => Response;

  function Harness() {
    api = useTaxonomy();
    return null;
  }

  beforeEach(() => {
    calls = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        calls.push({ url, method });
        if (method !== 'GET') return write();
        return json({ items: [] });
      }),
    );
  });
  afterEach(() => vi.unstubAllGlobals());

  async function mount() {
    const root = createRoot(document.createElement('div'));
    await act(async () => root.render(<Harness />));
    return root;
  }

  const writes = () => calls.filter((c) => c.method !== 'GET');

  it.each([
    [409, "A tag named 'Urban' already exists."],
    [404, 'Tag not found.'],
    [403, 'Not allowed.'],
  ])('a %i rename resolves false and shows the detail', async (status, detail) => {
    write = () => json({ detail }, status);
    await mount();

    let written: boolean | undefined;
    await act(async () => {
      written = await api.renameTag(1, 'Urban');
    });

    expect(written).toBe(false);
    expect(api.error).toBe(detail);
    expect(api.busy).toBe(false);
    expect(writes()).toEqual([
      { url: expect.stringMatching(/\/taxonomy\/tags\/1$/), method: 'PUT' },
    ]);
  });

  it.each([
    [404, 'Tag not found.'],
    [403, 'Not allowed.'],
  ])('a %i delete rejects with the detail', async (status, detail) => {
    write = () => json({ detail }, status);
    await mount();

    let failure: unknown;
    await act(async () => {
      await api.removeTag(1).catch((e) => {
        failure = e;
      });
    });

    expect((failure as Error).message).toBe(detail);
    expect(api.error).toBe(detail);
    expect(api.busy).toBe(false);
  });

  it('a written rename resolves true and re-reads the lists', async () => {
    write = () => json({ id: 1, name: 'Urban', slug: 'urban', article_count: 0 });
    await mount();
    const before = calls.length;

    let written: boolean | undefined;
    await act(async () => {
      written = await api.renameTag(1, 'Urban');
    });

    expect(written).toBe(true);
    expect(api.error).toBeNull();
    expect(calls.slice(before).filter((c) => c.method === 'GET')).toHaveLength(2);
  });
});
