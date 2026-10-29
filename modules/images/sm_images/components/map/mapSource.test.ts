// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { boundsOf, MAX_POINT_PAGES, resolveMapSource } from './mapSource';

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

describe('resolveMapSource', () => {
  it('prefers the PMTiles archive when the route answers a HEAD', async () => {
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(null, { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const source = await resolveMapSource(urls);
    expect(source.kind).toBe('tiles');
    expect(source.kind === 'tiles' && source.url).toMatch(
      /^http.*\/api\/images\/public\/c\/s\/map\.pmtiles$/,
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ method: 'HEAD' });
  });

  it('falls back to paged points when there is no archive', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === 'HEAD') return new Response(null, { status: 404 });
      return url.includes('cursor=next')
        ? json({ features: [point('b')], next_cursor: null })
        : json({ features: [point('a')], next_cursor: 'next' });
    });
    vi.stubGlobal('fetch', fetchMock);
    const source = await resolveMapSource(urls);
    expect(source).toEqual({ kind: 'points', features: [point('a'), point('b')] });
  });

  it('stops paging at the cap rather than looping on a cursor that never ends', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      init?.method === 'HEAD'
        ? new Response(null, { status: 404 })
        : json({ features: [], next_cursor: 'again' }),
    );
    vi.stubGlobal('fetch', fetchMock);
    await resolveMapSource(urls);
    expect(fetchMock).toHaveBeenCalledTimes(1 + MAX_POINT_PAGES);
  });

  it('treats a failing HEAD as no archive and surfaces a failing points read', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_i: RequestInfo | URL, init?: RequestInit) => {
        if (init?.method === 'HEAD') throw new Error('offline');
        return new Response('nope', { status: 500 });
      }),
    );
    await expect(resolveMapSource(urls)).rejects.toThrow('500');
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
