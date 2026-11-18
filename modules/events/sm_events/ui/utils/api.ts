/** Framework transport supplies same-origin credentials and the session CSRF token. */
import { type ApiFetchInit, apiFetch, NETWORK_FAILURE } from '@simple-module-py/ui/lib/api';
import { keys, translate as t } from './i18n';
import { EVENT_MAX_DAYS, SERIES_EVENT_MAX_DAYS } from './limits';
import type { Calendar, CalendarInput, Category, CategoryInput, Visibility } from './types';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    /** The 422's `loc` entries (without the leading `body`), dotted: `names.de`. */
    public readonly fields: string[] = [],
    /** Seconds the server asked to wait (429), when it said. */
    public readonly retryAfter: number | null = null,
    /** The input the server says the refusal belongs to (`times.end`, `texts.de.slug`). */
    public readonly field: string | null = null,
  ) {
    super(code);
  }
}

/** The error codes the editor branches on (`sm_events/core/constants.py`). */
export const CODE = {
  stale: 'stale',
  overridesOrphaned: 'overrides_orphaned',
  slugTaken: 'slug_taken',
  defaultLocaleRequired: 'default_locale_required',
  invalidLocalTime: 'invalid_local_time',
} as const;

const hasCode = (error: unknown, status: number, code: string): boolean =>
  error instanceof ApiError && error.status === status && error.code === code;

/** The event changed under the caller: 409 `stale`. */
export const isStale = (error: unknown): boolean => hasCode(error, 409, CODE.stale);
/** A series change would orphan overrides: 409 `overrides_orphaned`. */
export const isOrphaning = (error: unknown): boolean => hasCode(error, 409, CODE.overridesOrphaned);

/** The request hit something that is gone: a 404, whatever its code. */
export const isGone = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 404;

/** The message for a failed request. `gone` words a 404 for this screen's
 *  subject ("This calendar no longer exists.") instead of the generic one. */
export function errorText(error: unknown, gone?: string): string {
  const messages: Record<string, string> = {
    slug_taken: keys.events.errors.slug_taken,
    owner_required: keys.events.errors.owner_required,
    forbidden: keys.events.errors.forbidden,
    not_found: keys.events.errors.not_found,
    tenant_required: keys.events.errors.tenant_required,
    user_directory_unavailable: keys.events.errors.user_directory_unavailable,
    owner_not_allowed: keys.events.errors.owner_not_allowed,
    unknown_locale: keys.events.errors.unknown_locale,
    default_locale_required: keys.events.errors.default_locale_required,
    stale: keys.events.errors.stale,
    overrides_orphaned: keys.events.errors.overrides_orphaned,
    has_sub_events: keys.events.errors.has_sub_events,
    invalid_transition: keys.events.errors.invalid_transition,
    publish_required: keys.events.errors.publish_required,
    invalid_rrule: keys.events.errors.invalid_rrule,
    rrule_frequency_refused: keys.events.errors.rrule_frequency_refused,
    start_not_in_rule: keys.events.errors.start_not_in_rule,
    invalid_local_time: keys.events.errors.invalid_local_time,
    end_before_start: keys.events.errors.end_before_start,
    duration_too_long: keys.events.errors.duration_too_long,
    range_too_long: keys.events.errors.range_too_long,
    invalid_range: keys.events.errors.invalid_range,
    unknown_category: keys.events.errors.unknown_category,
    unknown_type: keys.events.errors.unknown_type,
    invalid_parent: keys.events.errors.invalid_parent,
    immutable_field: keys.events.errors.immutable_field,
    not_recurring: keys.events.errors.not_recurring,
    not_an_occurrence: keys.events.errors.not_an_occurrence,
    description_too_long: keys.events.errors.description_too_long,
  };
  if (!(error instanceof ApiError)) return t(keys.events.errors.generic);
  if (gone && error.status === 404) return t(gone);
  if (error.status === 429) return rateLimitText(error.retryAfter);
  if (error.code === 'duration_too_long') {
    return t(messages.duration_too_long as string, {
      oneOff: EVENT_MAX_DAYS,
      series: SERIES_EVENT_MAX_DAYS,
    });
  }
  if (messages[error.code]) return t(messages[error.code]);
  if (error.status === NETWORK_FAILURE) return t(keys.events.errors.offline);
  if (error.status === 401) return t(keys.events.errors.session_expired);
  if (error.status === 403) return t(keys.events.errors.forbidden);
  if (error.status === 422) return t(keys.events.errors.invalid_input);
  return t(keys.events.errors.generic);
}

function rateLimitText(seconds: number | null): string {
  return seconds === null
    ? t(keys.events.errors.requests_limited_soon)
    : t(keys.events.errors.requests_limited, { count: seconds });
}

/** The message for a failed people search: a 429 says "searches", anything else is `errorText`. */
export function searchErrorText(error: unknown, gone?: string): string {
  if (!(error instanceof ApiError) || error.status !== 429) return errorText(error, gone);
  return error.retryAfter === null
    ? t(keys.events.errors.rate_limited_soon)
    : t(keys.events.errors.rate_limited, { count: error.retryAfter });
}

type ErrorBody = {
  code?: unknown;
  retry_after?: unknown;
  detail?: unknown;
  field?: unknown;
} | null;

function fieldsOf(body: ErrorBody): string[] {
  if (!Array.isArray(body?.detail)) return [];
  return (body.detail as { loc?: unknown }[]).flatMap((item) =>
    Array.isArray(item?.loc)
      ? [item.loc.filter((part) => part !== 'body' && part !== 'query').join('.')]
      : [],
  );
}

export async function send<T>(url: string, init: ApiFetchInit = {}): Promise<T> {
  const result = await apiFetch<T>(url, init);
  if (result.ok) return result.data;
  const body = result.error as ErrorBody;
  const wait = Number(body?.retry_after);
  throw new ApiError(
    result.status,
    typeof body?.code === 'string' ? body.code : '',
    result.status === 422 ? fieldsOf(body) : [],
    result.status === 429 && Number.isFinite(wait) && wait > 0 ? Math.ceil(wait) : null,
    typeof body?.field === 'string' ? body.field : null,
  );
}

export const CALENDARS = '/api/events/calendars';
export const listCalendars = (trashed = false) =>
  send<Calendar[]>(`${CALENDARS}?trashed=${trashed}`);
export const getCalendar = (id: string) => send<Calendar>(`${CALENDARS}/${id}`);
export const createCalendar = (body: CalendarInput) =>
  send<Calendar>(CALENDARS, { method: 'POST', json: body });
export const updateCalendar = (id: string, body: CalendarInput) =>
  send<Calendar>(`${CALENDARS}/${id}`, { method: 'PATCH', json: body });
export const setVisibility = (id: string, visibility: Visibility) =>
  send<Calendar>(`${CALENDARS}/${id}/visibility`, { method: 'PUT', json: { visibility } });
export const transferOwner = (id: string, owner_id: string) =>
  send<Calendar>(`${CALENDARS}/${id}/owner`, { method: 'PUT', json: { owner_id } });
export const trashCalendar = (id: string) => send<void>(`${CALENDARS}/${id}`, { method: 'DELETE' });
export const restoreCalendar = (id: string) =>
  send<Calendar>(`${CALENDARS}/${id}/restore`, { method: 'POST' });

const CATEGORIES = '/api/events/categories';
export const listCategories = () => send<Category[]>(CATEGORIES);
export const createCategory = (body: CategoryInput) =>
  send<Category>(CATEGORIES, { method: 'POST', json: body });
export const updateCategory = (id: string, body: Omit<CategoryInput, 'slug'>) =>
  send<Category>(`${CATEGORIES}/${id}`, { method: 'PATCH', json: body });
export const deleteCategory = (id: string) =>
  send<void>(`${CATEGORIES}/${id}`, { method: 'DELETE' });
