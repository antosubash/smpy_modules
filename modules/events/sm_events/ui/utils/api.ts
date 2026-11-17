/** Framework transport supplies same-origin credentials and the session CSRF token. */
import { type ApiFetchInit, apiFetch, NETWORK_FAILURE } from '@simple-module-py/ui/lib/api';
import { keys, translate as t } from './i18n';
import type { Calendar, CalendarInput, Category, CategoryInput, Visibility } from './types';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    /** The 422's `loc` entries (without the leading `body`), dotted: `names.de`. */
    public readonly fields: string[] = [],
    /** Seconds the server asked to wait (429), when it said. */
    public readonly retryAfter: number | null = null,
  ) {
    super(code);
  }
}

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
  };
  if (!(error instanceof ApiError)) return t(keys.events.errors.generic);
  if (gone && error.status === 404) return t(gone);
  if (error.status === 429) return rateLimitText(error.retryAfter);
  if (messages[error.code]) return t(messages[error.code]);
  if (error.status === NETWORK_FAILURE) return t(keys.events.errors.offline);
  if (error.status === 401) return t(keys.events.errors.session_expired);
  if (error.status === 403) return t(keys.events.errors.forbidden);
  if (error.status === 422) return t(keys.events.errors.invalid_input);
  return t(keys.events.errors.generic);
}

function rateLimitText(seconds: number | null): string {
  return seconds === null
    ? t(keys.events.errors.rate_limited_soon)
    : t(keys.events.errors.rate_limited, { count: seconds });
}

type ErrorBody = { code?: unknown; retry_after?: unknown; detail?: unknown } | null;

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
  );
}

export const CALENDARS = '/api/events/calendars';
export const listCalendars = (trashed = false) =>
  send<Calendar[]>(`${CALENDARS}?trashed=${trashed}`);
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
