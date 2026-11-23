/** The anonymous occurrences fetcher for the read-only grid (`utils/public-get.ts`). */

import type { OccurrenceFetcher, OccurrenceQuery } from '../calendar/types';
import { publicGet } from '../utils/public-get';

export function publicUrl(apiUrl: string, q: OccurrenceQuery): string {
  const params = new URLSearchParams({ start: q.start, end: q.end });
  for (const id of q.calendars) params.append('calendar', id);
  for (const id of q.categories) params.append('category', id);
  for (const type of q.types) params.append('type', type);
  if (q.locale) params.set('locale', q.locale);
  return `${apiUrl}?${params.toString()}`;
}

export function publicFetcher(apiUrl: string): OccurrenceFetcher {
  return (query, signal) => publicGet(publicUrl(apiUrl, query), signal);
}
