/** Framework transport supplies same-origin credentials and the session CSRF token. */
import { type ApiFetchInit, apiFetch } from '@simple-module-py/ui/lib/api';
import { keys, translate as t } from './i18n';
import type { Calendar, CalendarInput, Category, CategoryInput, Visibility } from './types';

class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    public readonly detail: string | null,
  ) {
    super(code);
  }
}

export function errorText(error: unknown): string {
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
  if (messages[error.code]) return t(messages[error.code]);
  if (error.status === 0) return t(keys.events.errors.offline);
  if (error.status === 401) return t(keys.events.errors.session_expired);
  if (error.status === 403) return t(keys.events.errors.forbidden);
  if (error.status === 422) return t(keys.events.errors.invalid_input);
  return t(keys.events.errors.generic);
}

export async function send<T>(url: string, init: ApiFetchInit = {}): Promise<T> {
  const result = await apiFetch<T>(url, init);
  if (result.ok) return result.data;
  const body = result.error as { code?: unknown } | null;
  throw new ApiError(result.status, typeof body?.code === 'string' ? body.code : '', result.detail);
}

export function json(method: string, body: unknown): ApiFetchInit {
  return { method, json: body };
}
const CALENDARS = '/api/events/calendars';
export const listCalendars = (trashed = false) =>
  send<Calendar[]>(`${CALENDARS}?trashed=${trashed}`);
export const createCalendar = (body: CalendarInput) =>
  send<Calendar>(CALENDARS, json('POST', body));
export const updateCalendar = (id: string, body: CalendarInput) =>
  send<Calendar>(`${CALENDARS}/${id}`, json('PATCH', body));
export const setVisibility = (id: string, visibility: Visibility) =>
  send<Calendar>(`${CALENDARS}/${id}/visibility`, json('PUT', { visibility }));
export const transferOwner = (id: string, owner_id: string) =>
  send<Calendar>(`${CALENDARS}/${id}/owner`, json('PUT', { owner_id }));
export const trashCalendar = (id: string) => send<void>(`${CALENDARS}/${id}`, { method: 'DELETE' });
export const restoreCalendar = (id: string) =>
  send<Calendar>(`${CALENDARS}/${id}/restore`, { method: 'POST' });

const CATEGORIES = '/api/events/categories';
export const listCategories = () => send<Category[]>(CATEGORIES);
export const createCategory = (body: CategoryInput) =>
  send<Category>(CATEGORIES, json('POST', body));
export const updateCategory = (id: string, body: Omit<CategoryInput, 'slug'>) =>
  send<Category>(`${CATEGORIES}/${id}`, json('PATCH', body));
export const deleteCategory = (id: string) =>
  send<void>(`${CATEGORIES}/${id}`, { method: 'DELETE' });
