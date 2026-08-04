/**
 * Shared fetch plumbing for the pagebuilder JSON admin API.
 *
 * All endpoints live under `/api/pagebuilder` and return JSON. We use
 * plain fetch + same-origin cookies for auth, plus an `X-CSRF-Token`
 * header on every mutating request (token is read from the
 * `pagebuilder_csrf` cookie set by the view layer).
 */

export const BASE = '/api/pagebuilder';

export const CSRF_COOKIE = 'pagebuilder_csrf';

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const target = `${name}=`;
  for (const piece of document.cookie.split(';')) {
    const trimmed = piece.trim();
    if (trimmed.startsWith(target)) {
      return decodeURIComponent(trimmed.slice(target.length));
    }
  }
  return null;
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isFormData = init.body instanceof FormData;
  const method = (init.method ?? 'GET').toUpperCase();
  const csrfHeaders: Record<string, string> = {};
  if (UNSAFE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE);
    if (token) csrfHeaders['X-CSRF-Token'] = token;
  }
  const response = await fetch(`${BASE}${path}`, {
    credentials: 'same-origin',
    headers: {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      Accept: 'application/json',
      ...csrfHeaders,
      ...(init.headers || {}),
    },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Request failed (${response.status}): ${text}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
