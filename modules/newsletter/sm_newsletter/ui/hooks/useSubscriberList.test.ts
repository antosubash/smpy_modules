// @vitest-environment happy-dom
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { SubscriberPage } from '../utils/types';
import { SEARCH_DEBOUNCE_MS } from './useCampaignList';
import { PAGE_SIZE, useSubscriberList } from './useSubscriberList';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let list: ReturnType<typeof useSubscriberList>;
let listKey = 'news';
function Harness() {
  list = useSubscriberList(listKey);
  return null;
}

const page = (emails: string[], total = 120): SubscriberPage => ({
  items: emails.map((email) => ({ uuid: email, email }) as SubscriberPage['items'][number]),
  total,
  counts: { pending: 1, confirmed: 2, unsubscribed: 3 },
  records_url: '/admin/records/news',
});

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('useSubscriberList', () => {
  let root: ReturnType<typeof createRoot>;
  let fetchMock: ReturnType<typeof vi.fn>;
  let respond: (body: Record<string, unknown>) => Promise<Response>;

  beforeEach(() => {
    listKey = 'news';
    respond = async () => json(page([]));
    fetchMock = vi.fn((_url: string, init?: RequestInit) =>
      respond(JSON.parse(String(init?.body ?? '{}'))),
    );
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    act(() => root.unmount());
    vi.unstubAllGlobals();
  });

  async function mount() {
    root = createRoot(document.createElement('div'));
    await act(async () => root.render(createElement(Harness)));
  }
  const wait = (ms: number) =>
    act(async () => {
      await new Promise((r) => setTimeout(r, ms));
    });
  const last = () => {
    const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
    return { url, init, body: JSON.parse(String(init.body)) };
  };

  it('POSTs the filters in the body, never the search text in the URL', async () => {
    await mount();
    expect(last().url).toBe('/api/newsletter/lists/news/subscribers/search');
    expect(last().init.method).toBe('POST');
    await act(async () => list.setStatus('confirmed'));
    await act(async () => list.setTag('vip'));
    await act(async () => list.setSegment('7'));
    await act(async () => list.setQ('ada@example.com'));
    await wait(SEARCH_DEBOUNCE_MS + 100);
    const { url, body } = last();
    expect(url).not.toContain('ada');
    expect(url).not.toContain('?');
    expect(body).toMatchObject({
      status: 'confirmed',
      q: 'ada@example.com',
      tag: 'vip',
      segment: 7,
      offset: 0,
    });
  });

  it('debounces the search text', async () => {
    await mount();
    const before = fetchMock.mock.calls.length;
    await act(async () => list.setQ('a'));
    await act(async () => list.setQ('ad'));
    expect(fetchMock.mock.calls.length).toBe(before);
    await wait(SEARCH_DEBOUNCE_MS + 100);
    expect(fetchMock.mock.calls.length).toBe(before + 1);
    expect(last().body.q).toBe('ad');
  });

  it('puts the list back on its first page when a filter changes', async () => {
    respond = async () => json(page([], 500));
    await mount();
    await act(async () => list.setOffset(PAGE_SIZE));
    expect(last().body.offset).toBe(PAGE_SIZE);
    await act(async () => list.setTag('vip'));
    expect(list.offset).toBe(0);
    expect(last().body).toMatchObject({ tag: 'vip', offset: 0 });
    await act(async () => list.setOffset(PAGE_SIZE));
    await act(async () => list.setSegment('2'));
    expect(last().body).toMatchObject({ segment: 2, offset: 0 });
    await act(async () => list.setOffset(PAGE_SIZE));
    await act(async () => list.setStatus('pending'));
    expect(last().body).toMatchObject({ status: 'pending', offset: 0 });
  });

  it('lets only the newest response win', async () => {
    await mount();
    let resolveSlow: (r: Response) => void = () => {};
    respond = () => new Promise<Response>((r) => (resolveSlow = r));
    await act(async () => list.setStatus('pending'));
    respond = async () => json(page(['new@example.com'], 1));
    await act(async () => list.setStatus('confirmed'));
    expect(list.items?.map((i) => i.email)).toEqual(['new@example.com']);
    await act(async () => resolveSlow(json(page(['old@example.com'], 1))));
    expect(list.items?.map((i) => i.email)).toEqual(['new@example.com']);
    expect(list.counts.confirmed).toBe(2);
    expect(list.recordsUrl).toBe('/admin/records/news');
  });

  it("never sends the previous list's filters to a new list, and clears the counts", async () => {
    await mount();
    await act(async () => list.setSegment('7'));
    await act(async () => list.setTag('vip'));
    expect(list.counts.confirmed).toBe(2);
    const before = fetchMock.mock.calls.length;
    listKey = 'other';
    await act(async () => root.render(createElement(Harness)));
    const fresh = fetchMock.mock.calls.slice(before);
    expect(fresh.length).toBeGreaterThan(0);
    for (const [url, init] of fresh) {
      expect(url).toBe('/api/newsletter/lists/other/subscribers/search');
      expect(JSON.parse(String(init.body))).toMatchObject({
        segment: null,
        tag: null,
        status: null,
      });
    }
    expect(list.segment).toBe('');
    expect(list.tag).toBe('');
  });
});
