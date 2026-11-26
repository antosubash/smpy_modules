import { currentCsrfToken } from '@simple-module-py/ui/lib/csrf-token';
import { keys, translate } from './i18n';
import type { Filters, GeoStatus, Property, PropertyInput, Report } from './types';
import { validationMessage } from './validationMessage';

const BASE = '/api/analytics';
const LOGIN_PATH = '/users/login';
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly fieldErrors: Record<string, string> = {},
  ) {
    super(message);
  }
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/** The framework's `csrfToken` shared prop on a write (#342). A raw `fetch`
 *  rather than `apiFetch`, which reports an aborted read as a network failure
 *  where `useAnalytics` cancels superseded reports with the signal. */
function csrfHeaders(method: string | undefined): Record<string, string> {
  const token = UNSAFE.has((method ?? 'GET').toUpperCase()) ? currentCsrfToken() : null;
  return token ? { 'X-CSRF-Token': token } : {};
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...csrfHeaders(options.method),
      ...options.headers,
    },
  });
  options.signal?.throwIfAborted();
  if (!response.ok) {
    if (response.status === 401) {
      // The framework records return URLs on protected document navigations;
      // the login page deliberately ignores a user-supplied `next` parameter.
      if (window.location.pathname !== LOGIN_PATH) window.location.reload();
      throw new ApiError(401, translate(keys.analytics.session_expired));
    }
    let detail = '';
    const fieldErrors: Record<string, string> = {};
    try {
      const data = await response.json();
      if (typeof data.detail === 'string') detail = data.detail;
      else if (response.status === 422 && Array.isArray(data.detail)) {
        const messages: string[] = [];
        for (const item of data.detail as (Parameters<typeof validationMessage>[0] & {
          loc?: (string | number)[];
        })[]) {
          if (typeof item.msg !== 'string') continue;
          const message = validationMessage(item);
          // A nested list error belongs to its editor field, not the list index.
          const field = item.loc?.[0] === 'body' ? item.loc[1] : item.loc?.[0];
          if (typeof field === 'string')
            fieldErrors[field] = [fieldErrors[field], message].filter(Boolean).join('; ');
          messages.push(typeof field === 'string' ? `${field}: ${message}` : message);
        }
        detail = messages.join('; ');
      }
    } catch {
      /* Never display HTML from an upstream error. */
    }
    throw new ApiError(response.status, detail || translate(keys.analytics.error), fieldErrors);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const listProperties = (signal?: AbortSignal) =>
  request<Property[]>('/properties', { signal });
export const geoStatus = (signal?: AbortSignal) =>
  request<{ geo: GeoStatus }>('/status', { signal });
export const saveProperty = (data: PropertyInput, id?: string) =>
  request<Property>(id ? `/properties/${encodeURIComponent(id)}` : '/properties', {
    method: id ? 'PUT' : 'POST',
    body: JSON.stringify(data),
  });
export const deleteProperty = (id: string) =>
  request<void>(`/properties/${encodeURIComponent(id)}`, { method: 'DELETE' });
export const loadReport = (id: string, filters: Filters, signal?: AbortSignal) => {
  const query = new URLSearchParams(
    Object.entries(filters)
      .filter(([, value]) => value !== '')
      .map(([key, value]) => [key, value === '__unknown__' ? '' : value]),
  );
  return request<Report>(`/properties/${encodeURIComponent(id)}/report?${query}`, { signal });
};
