/** The blocks' client for the anonymous routes under `/api/events/public/` (plain `fetch`: there
 *  is no session to carry and the routes only read). A refusal is an `ApiError` with the module's
 *  code, a non-JSON body keeps the status as its code. */

import type { PublicListItem } from '../public/types';
import { publicGet } from '../utils/public-get';

const BASE = '/api/events/public';

export type BlockCalendar = {
  id: string;
  slug: string;
  name: string;
  color: string;
  default_timezone: string;
};
export type BlockCategory = { id: string; slug: string; name: string; color: string | null };
export type BlockCalendars = {
  calendars: BlockCalendar[];
  categories: BlockCategory[];
  default_timezone: string;
};

export type UpcomingQuery = {
  slugs: string[];
  category: string;
  count: number;
  locale: string;
};

const get = <T>(path: string, params: URLSearchParams, signal: AbortSignal) =>
  publicGet<T>(`${BASE}${path}?${params.toString()}`, signal);

export function fetchBlockCalendars(
  slugs: string[],
  locale: string,
  signal: AbortSignal,
): Promise<BlockCalendars> {
  const params = new URLSearchParams();
  for (const slug of slugs) params.append('calendar', slug);
  if (locale) params.set('locale', locale);
  return get<BlockCalendars>('/calendars', params, signal);
}

export async function fetchUpcoming(
  q: UpcomingQuery,
  signal: AbortSignal,
): Promise<PublicListItem[]> {
  const params = new URLSearchParams();
  for (const slug of q.slugs) params.append('calendar', slug);
  if (q.category) params.set('category', q.category);
  params.set('count', String(q.count));
  if (q.locale) params.set('locale', q.locale);
  return (await get<{ items: PublicListItem[] }>('/upcoming', params, signal)).items;
}
