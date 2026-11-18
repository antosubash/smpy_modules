/**
 * The private feed links' calls. The one response that carries a link is `createToken`'s: it
 * is handed to the caller and kept nowhere here (no cache, no storage, no log). Lists and
 * revokes never carry one.
 */

import { CALENDARS, send } from './api';

export type FeedToken = {
  id: string;
  label: string;
  locale: string;
  created_at: string;
  last_used_at: string | null;
  user_id: string;
  /** `null` for anyone the server may not name: shown as "Unknown user". */
  user_name: string | null;
  mine: boolean;
};

/** What the create call returns: the link, once. */
export type CreatedFeedToken = FeedToken & { url: string; webcal_url: string };

const tokens = (calendarId: string) => `${CALENDARS}/${calendarId}/feed-tokens`;

export function listTokens(
  calendarId: string,
  all: boolean,
  signal?: AbortSignal,
): Promise<FeedToken[]> {
  return send(`${tokens(calendarId)}${all ? '?all=true' : ''}`, { signal });
}

export function createToken(
  calendarId: string,
  body: { label: string; locale: string | null },
): Promise<CreatedFeedToken> {
  return send(tokens(calendarId), { method: 'POST', json: body });
}

export function revokeToken(id: string): Promise<void> {
  return send(`/api/events/feed-tokens/${id}`, { method: 'DELETE' });
}
