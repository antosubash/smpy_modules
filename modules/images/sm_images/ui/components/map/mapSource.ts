/**
 * Where a collection map gets its points from, decided once per mount.
 *
 * The first page of `…/points` is read first: a collection whose points fit in
 * it is drawn from them - always fresh and complete, with no archive probe.
 * Past one page a built PMTiles archive (`…/map.pmtiles`, tippecanoe-clustered)
 * is preferred: it scales to any collection and the browser reads only the
 * ranges it draws - even one a rebuild is pending for (`X-Map-Stale: 1`, sent
 * to editors): it is complete, only late, while paging stops at
 * {@link MAX_POINT_PAGES}. A collection with no archive (never built, withdrawn
 * by a visibility or point change, or a host without tippecanoe) answers a 404;
 * the map then pages through the rest of the points, which MapLibre clusters
 * itself.
 * Both routes re-check access on every request, so neither can show a point the
 * caller may not see.
 */

import type { PointFeature, PointsPage } from '../../utils/types-public';

export type MapSource =
  | { kind: 'tiles'; url: string }
  | {
      kind: 'points';
      features: PointFeature[];
      /** Set when paging stopped at {@link MAX_POINT_PAGES} with points left. */
      truncated?: true;
    };

/** Points per request, and how many requests the fallback makes at most
 *  (20 000 points): past that a collection needs its archive. */
export const POINTS_PAGE = 1000;
export const MAX_POINT_PAGES = 20;

const absolute = (url: string) => new URL(url, window.location.href).toString();

/** Whether the archive answers the HEAD. */
async function hasArchive(mapUrl: string, signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(mapUrl, { method: 'HEAD', credentials: 'same-origin', signal });
    return response.ok;
  } catch {
    return false;
  }
}

async function pointsPage(
  pointsUrl: string,
  cursor: string | null,
  signal?: AbortSignal,
): Promise<PointsPage> {
  const qs = `limit=${POINTS_PAGE}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`;
  const response = await fetch(`${pointsUrl}?${qs}`, { credentials: 'same-origin', signal });
  if (!response.ok) throw new Error(String(response.status));
  return (await response.json()) as PointsPage;
}

export async function resolveMapSource(
  urls: { pointsUrl: string; mapUrl: string },
  signal?: AbortSignal,
): Promise<MapSource> {
  const first = await pointsPage(urls.pointsUrl, null, signal);
  const features = [...first.features];
  let cursor = first.next_cursor;
  if (cursor && (await hasArchive(urls.mapUrl, signal))) {
    return { kind: 'tiles', url: absolute(urls.mapUrl) };
  }
  for (let page = 1; cursor && page < MAX_POINT_PAGES; page++) {
    const body = await pointsPage(urls.pointsUrl, cursor, signal);
    features.push(...body.features);
    cursor = body.next_cursor;
  }
  return cursor ? { kind: 'points', features, truncated: true } : { kind: 'points', features };
}

/** The box around `features`, as MapLibre's bounds; `null` without any. */
export function pointsBounds(
  features: PointFeature[],
): [[number, number], [number, number]] | null {
  if (features.length === 0) return null;
  let [minx, miny, maxx, maxy] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const { geometry } of features) {
    const [x, y] = geometry.coordinates;
    [minx, miny, maxx, maxy] = [
      Math.min(minx, x),
      Math.min(miny, y),
      Math.max(maxx, x),
      Math.max(maxy, y),
    ];
  }
  return boundsOf([minx, miny, maxx, maxy]);
}

/** `[minx, miny, maxx, maxy]` as MapLibre's bounds, or `null` without a box. */
export function boundsOf(bbox: number[] | null): [[number, number], [number, number]] | null {
  if (bbox?.length !== 4 || bbox.some((v) => !Number.isFinite(v))) return null;
  const [minx, miny, maxx, maxy] = bbox;
  return [
    [minx, miny],
    [maxx, maxy],
  ];
}
