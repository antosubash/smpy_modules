import { afterEach, describe, expect, it, vi } from 'vitest';

import { bulkRecords, emptyTrash } from './api-records';

function ok(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

function lastCall(fetchMock: ReturnType<typeof vi.fn>): { url: string; init: RequestInit } {
  const [url, init] = fetchMock.mock.calls.at(-1) as [string, RequestInit];
  return { url, init };
}

describe('bulkRecords', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('posts the action and the uuids to the type’s bulk route', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(ok({ action: 'trash', requested: 2, changed: 2, cascaded: 0 }));
    vi.stubGlobal('fetch', fetchMock);

    await bulkRecords('article', 'trash', ['a', 'b']);

    const { url, init } = lastCall(fetchMock);
    expect(url).toBe('/api/records/types/article/records/bulk');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ action: 'trash', uuids: ['a', 'b'] });
  });

  it('omits expected_versions entirely rather than sending null', async () => {
    // A fresh Response per call: one is consumed by each `request()`.
    const fetchMock = vi.fn().mockImplementation(async () => ok({}));
    vi.stubGlobal('fetch', fetchMock);

    await bulkRecords('article', 'publish', ['a']);
    expect(JSON.parse(String(lastCall(fetchMock).init.body))).not.toHaveProperty(
      'expected_versions',
    );

    await bulkRecords('article', 'publish', ['a'], { a: 3 });
    expect(JSON.parse(String(lastCall(fetchMock).init.body)).expected_versions).toEqual({ a: 3 });
  });
});

describe('emptyTrash', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('sends no query at all when nothing is filtered', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ purged: 3, filtered: false }));
    vi.stubGlobal('fetch', fetchMock);

    await emptyTrash('article');

    expect(lastCall(fetchMock).url).toBe('/api/records/types/article/records/trash/empty');
  });

  it('repeats `filter=` once per term — the server ANDs them', async () => {
    // One of two terms would empty *more* than the screen listed, which is
    // the one mistake an irreversible action must not make.
    const fetchMock = vi.fn().mockResolvedValue(ok({ purged: 1, filtered: true }));
    vi.stubGlobal('fetch', fetchMock);

    await emptyTrash('article', ['topic:eq:news', 'views:gt:10']);

    expect(lastCall(fetchMock).url).toBe(
      '/api/records/types/article/records/trash/empty?filter=topic%3Aeq%3Anews&filter=views%3Agt%3A10',
    );
  });

  it('drops an empty term rather than sending `filter=`', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok({ purged: 0, filtered: false }));
    vi.stubGlobal('fetch', fetchMock);

    await emptyTrash('article', ['']);

    expect(lastCall(fetchMock).url).toBe('/api/records/types/article/records/trash/empty');
  });
});
