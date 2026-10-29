/**
 * Where a collection map gets its points from, decided once per mount.
 *
 * A built PMTiles archive (`…/map.pmtiles`, tippecanoe-clustered) is preferred:
 * it scales to any collection and the browser reads only the ranges it draws.
 * A collection with no archive yet (never built, withdrawn by a visibility or
 * point change, or a host without tippecanoe) answers that route with a 404; the
 * map then pages through the `…/points` GeoJSON, which MapLibre clusters itself.
 * Both routes re-check access on every request, so neither can show a point the
 * caller may not see.
 */

import type { PointFeature, PointsPage } from '../../utils/types-public';

export type MapSource =
  | { kind: 'tiles'; url: string }
  | { kind: 'points'; features: PointFeature[] };

/** Points per request, and how many requests the fallback makes at most
 *  (20 000 points): past that a collection needs its archive. */
export const POINTS_PAGE = 1000;
export const MAX_POINT_PAGES = 20;

const absolute = (url: string) => new URL(url, window.location.href).toString();

async function hasArchive(mapUrl: string, signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(mapUrl, { method: 'HEAD', credentials: 'same-origin', signal });
    return response.ok;
  } catch {
    return false;
  }
}

async function pagedPoints(pointsUrl: string, signal?: AbortSignal): Promise<PointFeature[]> {
  const features: PointFeature[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < MAX_POINT_PAGES; page++) {
    const qs: string = `limit=${POINTS_PAGE}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`;
    const response = await fetch(`${pointsUrl}?${qs}`, { credentials: 'same-origin', signal });
    if (!response.ok) throw new Error(String(response.status));
    const body = (await response.json()) as PointsPage;
    features.push(...body.features);
    cursor = body.next_cursor;
    if (!cursor) break;
  }
  return features;
}

export async function resolveMapSource(
  urls: { pointsUrl: string; mapUrl: string },
  signal?: AbortSignal,
): Promise<MapSource> {
  if (await hasArchive(urls.mapUrl, signal)) return { kind: 'tiles', url: absolute(urls.mapUrl) };
  return { kind: 'points', features: await pagedPoints(urls.pointsUrl, signal) };
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
