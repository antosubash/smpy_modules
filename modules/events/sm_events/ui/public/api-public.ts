/** The anonymous occurrences fetcher for the read-only grid. Plain `fetch`: there is no
 *  session to send a CSRF token for, and the endpoint only reads. */

import type { OccurrenceFetcher, OccurrenceQuery } from '../calendar/types';
import { ApiError } from '../utils/api';

export function publicUrl(apiUrl: string, q: OccurrenceQuery): string {
  const params = new URLSearchParams({ start: q.start, end: q.end });
  for (const id of q.calendars) params.append('calendar', id);
  for (const id of q.categories) params.append('category', id);
  for (const type of q.types) params.append('type', type);
  if (q.locale) params.set('locale', q.locale);
  return `${apiUrl}?${params.toString()}`;
}

export function publicFetcher(apiUrl: string): OccurrenceFetcher {
  return async (query, signal) => {
    const response = await fetch(publicUrl(apiUrl, query), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
      signal,
    });
    if (!response.ok) {
      let code = String(response.status);
      try {
        const body = (await response.json()) as { code?: string };
        if (typeof body.code === 'string') code = body.code;
      } catch {
        /* a body that is not JSON keeps the status as its code */
      }
      throw new ApiError(response.status, code);
    }
    return response.json();
  };
}
