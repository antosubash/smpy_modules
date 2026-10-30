// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { boundsOf, MAX_POINT_PAGES, pointsBounds, resolveMapSource } from './mapSource';

const urls = {
  pointsUrl: '/api/images/public/c/s/points',
  mapUrl: '/api/images/public/c/s/map.pmtiles',
};
const point = (id: string) => ({
  type: 'Feature',
  geometry: { type: 'Point', coordinates: [1, 2] },
  properties: { id, captured_at: null, group_id: null },
});
const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });

afterEach(() => vi.unstubAllGlobals());

type Route = (url: string, init?: RequestInit) => Response | Promise<Response>;
const stub = (route: Route) => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    route(String(input), init),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
};
const isHead = (init?: RequestInit) => init?.method === 'HEAD';

describe('resolveMapSource', () => {
  it('uses the points, with no archive probe, when they fit in one page', async () => {
    // QA TEST-003: an archive built from the first 4 located images was drawn
    // while the other 16 waited for the rebuild. One page of points is always
    // fresh and complete; and an empty collection probes no archive (TEST-011).
    const fetchMock = stub((_url, init) =>
      isHead(init)
        ? new Response(null, { status: 200 })
        : json({ features: [point('a')], next_cursor: null }),
    );
    const source = await resolveMapSource(urls);
    expect(source).toEqual({ kind: 'points', features: [point('a')] });
    expect(fetchMock.mock.calls.some(([, init]) => isHead(init))).toBe(false);
  });

  it('prefers the PMTiles archive for a collection past one page', async () => {
    const fetchMock = stub((_url, init) =>
      isHead(init)
        ? new Response(null, { status: 200 })
        : json({ features: [point('a')], next_cursor: 'next' }),
    );
    const source = await resolveMapSource(urls);
    expect(source.kind).toBe('tiles');
    expect(source.kind === 'tiles' && source.url).toMatch(
      /^http.*\/api\/images\/public\/c\/s\/map\.pmtiles$/,
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({ method: 'HEAD' });
  });

  it('keeps a stale archive for a collection past one page: paging would truncate it', async () => {
    // Review: 25 000 points past a stale archive were cut to the 20 000 the
    // fallback pages; the stale archive is complete, only late.
    const fetchMock = stub((_url, init) =>
      isHead(init)
        ? new Response(null, { status: 200, headers: { 'X-Map-Stale': '1' } })
        : json({ features: [point('a')], next_cursor: 'next' }),
    );
    const source = await resolveMapSource(urls);
    expect(source.kind).toBe('tiles');
    expect(fetchMock.mock.calls.filter(([, init]) => !isHead(init))).toHaveLength(1);
  });

  it('falls back to paged points when there is no archive', async () => {
    stub((url, init) => {
      if (isHead(init)) return new Response(null, { status: 404 });
      return url.includes('cursor=next')
        ? json({ features: [point('b')], next_cursor: null })
        : json({ features: [point('a')], next_cursor: 'next' });
    });
    const source = await resolveMapSource(urls);
    expect(source).toEqual({ kind: 'points', features: [point('a'), point('b')] });
  });

  it('stops paging at the cap rather than looping on a cursor that never ends', async () => {
    const fetchMock = stub((_url, init) =>
      isHead(init)
        ? new Response(null, { status: 404 })
        : json({ features: [], next_cursor: 'again' }),
    );
    const source = await resolveMapSource(urls);
    expect(fetchMock).toHaveBeenCalledTimes(1 + MAX_POINT_PAGES);
    expect(source.kind === 'points' && source.truncated).toBe(true); // and says so
  });

  it('surfaces a failing points read', async () => {
    stub(() => new Response('nope', { status: 500 }));
    await expect(resolveMapSource(urls)).rejects.toThrow('500');
  });

  it('treats a failing HEAD as no archive', async () => {
    stub((url, init) => {
      if (isHead(init)) throw new Error('offline');
      return url.includes('cursor=next')
        ? json({ features: [point('b')], next_cursor: null })
        : json({ features: [point('a')], next_cursor: 'next' });
    });
    expect((await resolveMapSource(urls)).kind).toBe('points');
  });
});

describe('pointsBounds', () => {
  it('boxes the points it is given, and none without points', () => {
    const at = (x: number, y: number) => ({
      ...point('p'),
      geometry: { type: 'Point', coordinates: [x, y] },
    });
    expect(pointsBounds([at(14, 60), at(-8, 53), at(25, 65)] as never)).toEqual([
      [-8, 53],
      [25, 65],
    ]);
    expect(pointsBounds([])).toBeNull();
  });
});

describe('boundsOf', () => {
  it('turns a box into corner pairs and refuses a malformed one', () => {
    expect(boundsOf([1, 2, 3, 4])).toEqual([
      [1, 2],
      [3, 4],
    ]);
    expect(boundsOf(null)).toBeNull();
    expect(boundsOf([1, 2, 3])).toBeNull();
    expect(boundsOf([1, Number.NaN, 3, 4])).toBeNull();
  });
});
