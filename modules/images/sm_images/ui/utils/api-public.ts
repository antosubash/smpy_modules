/**
 * The anonymous reads of `/api/images/public/c/{slug}`: a public collection's
 * gallery, points and PMTiles. Plain `fetch`, deliberately not `api.ts`'s
 * `send`: a visitor has no session, so a 401 must not bounce them to a login
 * screen, and nothing here writes (no CSRF header).
 */

import type { PublicPage } from './types-public';

const BASE = '/api/images/public/c';

export const publicBase = (slug: string) => `${BASE}/${encodeURIComponent(slug)}`;

async function read<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { credentials: 'same-origin', signal });
  if (!response.ok) throw new Error(String(response.status));
  return (await response.json()) as T;
}

export function listPublicImages(
  slug: string,
  opts: { limit?: number; cursor?: string | null; signal?: AbortSignal } = {},
): Promise<PublicPage> {
  const qs = new URLSearchParams();
  if (opts.limit) qs.set('limit', String(opts.limit));
  if (opts.cursor) qs.set('cursor', opts.cursor);
  const text = qs.toString();
  return read(`${publicBase(slug)}/images${text ? `?${text}` : ''}`, opts.signal);
}

export const publicPointsUrl = (slug: string) => `${publicBase(slug)}/points`;
export const publicMapUrl = (slug: string) => `${publicBase(slug)}/map.pmtiles`;

/** The display copy the anonymous twin serves (no `?v=`: a point names only an id). */
export const publicDisplayUrl = (slug: string, imageId: string) =>
  `${publicBase(slug)}/images/${imageId}/display`;

export type StatMetric = 'images' | 'located' | 'collections';

/** The route's answer. The server stops counting at a bound: past it a count
 *  is the bound with `capped`, and a total over too many collections is
 *  `value: null` with `capped` (unavailable, not a partial sum). */
export interface PublicStat {
  value: number | null;
  capped: boolean;
}

/** One count from `/api/images/public/stats` (the `ImageStats` block). A blank
 *  `collection`, or any collection for `collections`, is sent as no param. */
export async function fetchPublicStat(opts: {
  metric: StatMetric;
  collection: string;
  signal: AbortSignal;
}): Promise<PublicStat> {
  const qs = new URLSearchParams({ metric: opts.metric });
  if (opts.metric !== 'collections' && opts.collection) qs.set('collection', opts.collection);
  const body = await read<{ value?: unknown; capped?: unknown }>(
    `/api/images/public/stats?${qs}`,
    opts.signal,
  );
  const capped = body.capped === true;
  if (body.value === null && capped) return { value: null, capped };
  if (typeof body.value !== 'number' || !Number.isFinite(body.value)) {
    throw new Error('bad stat');
  }
  return { value: body.value, capped };
}
