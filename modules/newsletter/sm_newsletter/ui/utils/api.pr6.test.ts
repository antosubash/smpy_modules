import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@inertiajs/react', () => ({ router: { on: () => () => undefined } }));

async function load(props: unknown) {
  vi.resetModules();
  const text = JSON.stringify({ component: 'Newsletter/Campaigns', props });
  vi.stubGlobal('document', {
    querySelector: (selector: string) =>
      selector.includes('data-page="app"') ? { textContent: text } : null,
  });
  return { api: (await import('./api')).api };
}

function stubFetch(response: () => Response) {
  const fetchMock = vi.fn().mockImplementation(async () => response());
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const ok = () => new Response('{}', { status: 200 });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('PR 6 calls', () => {
  it('hit the right path, method and body', async () => {
    const { api } = await load({ csrf_token: 'tok' });
    const fetchMock = stubFetch(ok);
    const signal = new AbortController().signal;
    const rules = [{ field: 'tags', op: 'any' as const, value: ['vip'] }];
    await api.listFields('news');
    await api.audienceCount('news', 'tag:vip', signal);
    await api.listSegments();
    await api.listSegments('news');
    await api.getSegment(3);
    await api.createSegment({ name: 'A', list_type_key: 'news', rules });
    await api.patchSegment(3, { name: 'B' });
    await api.deleteSegment(3);
    await api.previewSegment({ list_type_key: 'news', rules }, signal);
    await api.searchSubscribers('news', { q: 'a@b.c', offset: 50 }, signal);
    await api.getSubscriber('news', 'abc');
    await api.tagSubscriber('news', 'abc', { add: ['x'], remove: [] });
    await api.unsubscribeSubscriber('news', 'abc');
    await api.listSuppressions({ reason: 'complaint', offset: 0, limit: 50 }, signal);
    await api.lookupSuppressions('a@b.c');
    await api.liftSuppression(9, { version: 'v1', email: 'a@b.c', note: 'n' });
    await api.listLifts({ offset: 50 }, signal);
    const sent = fetchMock.mock.calls.map((c) => ({
      call: `${(c[1] as RequestInit).method ?? 'GET'} ${c[0] as string}`,
      body: (c[1] as RequestInit).body,
      signal: (c[1] as RequestInit).signal,
    }));
    const b = '/api/newsletter';
    expect(sent.map((s) => s.call)).toEqual([
      `GET ${b}/lists/news/fields`,
      `GET ${b}/lists/news/audience-count?audience=tag%3Avip`,
      `GET ${b}/segments`,
      `GET ${b}/segments?list_type_key=news`,
      `GET ${b}/segments/3`,
      `POST ${b}/segments`,
      `PATCH ${b}/segments/3`,
      `DELETE ${b}/segments/3`,
      `POST ${b}/segments/preview`,
      `POST ${b}/lists/news/subscribers/search`,
      `GET ${b}/lists/news/subscribers/abc`,
      `POST ${b}/lists/news/subscribers/abc/tags`,
      `POST ${b}/lists/news/subscribers/abc/unsubscribe`,
      `GET ${b}/suppressions?reason=complaint&offset=0&limit=50`,
      `POST ${b}/suppressions/lookup`,
      `POST ${b}/suppressions/9/lift`,
      `GET ${b}/suppressions/lifts?offset=50`,
    ]);
    const body = (i: number) => JSON.parse(sent[i].body as string);
    expect(body(5)).toEqual({ name: 'A', list_type_key: 'news', rules });
    expect(body(6)).toEqual({ name: 'B' });
    expect(body(8)).toEqual({ list_type_key: 'news', rules });
    expect(body(11)).toEqual({ add: ['x'], remove: [] });
    expect(body(12)).toEqual({});
    expect(body(14)).toEqual({ email: 'a@b.c' });
    expect(sent[1].signal).toBe(signal);
    expect(sent[8].signal).toBe(signal);
    expect(sent[16].signal).toBe(signal);
  });

  it('searches with the text in the body only (C5)', async () => {
    const { api } = await load({ csrf_token: 'tok' });
    const fetchMock = stubFetch(ok);
    await api.searchSubscribers('news', { q: 'secret@example.com', status: 'pending' });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe('POST');
    expect(url).not.toContain('?');
    expect(url).not.toContain('secret');
    expect(JSON.parse(init.body as string)).toEqual({ q: 'secret@example.com', status: 'pending' });
  });

  it('sends the version a lift read (C3)', async () => {
    const { api } = await load({ csrf_token: 'tok' });
    const fetchMock = stubFetch(ok);
    await api.liftSuppression(9, { version: 'v7', email: 'a@b.c', note: 'asked' });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({
      version: 'v7',
      email: 'a@b.c',
      note: 'asked',
    });
  });
});
