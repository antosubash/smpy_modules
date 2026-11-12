import { currentCsrfToken } from '@simple-module-py/ui/lib/csrf-token';
import { keys, translate } from './i18n';
import type { Filters, GeoStatus, Property, PropertyInput, Report } from './types';

const BASE = '/api/analytics';
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
      ...csrfHeaders(options.method),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let detail = '';
    try {
      const data = await response.json();
      detail =
        typeof data.detail === 'string'
          ? data.detail
          : Array.isArray(data.detail)
            ? data.detail.map((v: { msg: string }) => v.msg).join('; ')
            : '';
    } catch {
      /* Never display HTML from an upstream error. */
    }
    throw new Error(detail || translate(keys.analytics.error));
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
