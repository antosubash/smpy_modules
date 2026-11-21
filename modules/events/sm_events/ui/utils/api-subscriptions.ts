/** A calendar's external subscriptions. The address is write-only: it goes up on create and on an
 *  edit that changes it, and no response carries it (only `url_display`). */
import { ApiError, errorText, send } from './api';
import { keys, translate as t } from './i18n';

export type SubscriptionStatus = 'pending' | 'ok' | 'error' | 'paused' | 'disabled';
export type Subscription = {
  id: string;
  calendar_id: string;
  url_display: string;
  label: string;
  color: string | null;
  refresh_minutes: number | null;
  effective_refresh_minutes: number;
  public: boolean;
  status: SubscriptionStatus;
  error_code: string | null;
  last_http_status: number | null;
  last_fetched_at: string | null;
  last_ok_at: string | null;
  next_fetch_at: string | null;
  consecutive_failures: number;
  item_count: number;
  last_counts: { stored?: number; skipped?: number; reasons?: Record<string, number> };
  may_use_internal_addresses: boolean;
  /** The token an edit sends back as `expected`. */
  version: string;
  /** Only on a refresh-now answer: the fetch has not run yet and will within `queued_minutes`. */
  queued?: boolean;
  queued_minutes?: number | null;
};
export type SubscriptionInput = {
  url: string;
  label: string;
  color: string | null;
  refresh_minutes: number | null;
  public: boolean;
};
export type SubscriptionPatch = Partial<SubscriptionInput> & { expected?: string };

const base = (calendarId: string) => `/api/events/calendars/${calendarId}/subscriptions`;
const one = (id: string) => `/api/events/subscriptions/${id}`;

export const listSubscriptions = (calendarId: string, signal?: AbortSignal) =>
  send<Subscription[]>(base(calendarId), { signal });
export type Capacity = Record<'calendar' | 'owner' | 'tenant', { used: number; limit: number }>;
export const subscriptionCapacity = (calendarId: string, signal?: AbortSignal) =>
  send<Capacity>(`${base(calendarId)}/capacity`, { signal });
export const createSubscription = (calendarId: string, body: SubscriptionInput) =>
  send<Subscription>(base(calendarId), { method: 'POST', json: body });
export const updateSubscription = (id: string, patch: SubscriptionPatch) =>
  send<Subscription>(one(id), { method: 'PATCH', json: patch });
export const refreshSubscription = (id: string) =>
  send<Subscription>(`${one(id)}/refresh`, { method: 'POST' });
export const pauseSubscription = (id: string) =>
  send<Subscription>(`${one(id)}/pause`, { method: 'POST' });
export const resumeSubscription = (id: string) =>
  send<Subscription>(`${one(id)}/resume`, { method: 'POST' });
export const deleteSubscription = (id: string) => send<null>(one(id), { method: 'DELETE' });

const copy = keys.events.subscriptions;
const messages: Record<string, string> = {
  ...copy.codes,
  ...copy.errors,
};

/** The message for a failed request: a refusal code of the address, or one of this feature's own
 *  conflicts, in words; anything else through the module's generic text. */
export function subscriptionErrorText(error: unknown): string {
  if (error instanceof ApiError && error.status !== 404 && messages[error.code]) {
    return t(messages[error.code] as string);
  }
  return errorText(error);
}

/** The words for a stored failure code (`http_status` carries the server's number). */
export function failureText(code: string, status: number | null): string {
  const key = messages[code] ?? copy.codes.internal;
  return t(key, { status: status ?? '' });
}
