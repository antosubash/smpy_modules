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
