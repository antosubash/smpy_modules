/** The `NewsStats` block's read, kept beside `api.ts` rather than in it so
 *  that file stays under the 300-line cap. */

import { BASE } from './http';

/** The route's answer. Past the server's bound `value` is the bound and
 *  `capped` is true, which the block shows as "10,000+". */
export interface PublishedCount {
  value: number;
  capped: boolean;
}

/** How many articles a reader can open right now — the `NewsStats` block's
 *  number. Public and cacheable, so it carries no session. `locale` of `null`
 *  counts every language the site publishes in. */
export async function fetchPublishedCount(opts: {
  category: string;
  locale: string | null;
  signal: AbortSignal;
}): Promise<PublishedCount> {
  const query = new URLSearchParams({ metric: 'published' });
  if (opts.category) query.set('category', opts.category);
  if (opts.locale) query.set('locale', opts.locale);
  const response = await fetch(`${BASE}/stats?${query}`, {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
    signal: opts.signal,
  });
  if (!response.ok) throw new Error(`News request failed (${response.status})`);
  const body = (await response.json()) as { value?: unknown; capped?: unknown };
  if (typeof body.value !== 'number' || !Number.isFinite(body.value)) {
    throw new Error('News stats response has no value');
  }
  return { value: body.value, capped: body.capped === true };
}
