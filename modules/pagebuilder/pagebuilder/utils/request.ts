/**
 * Shared fetch plumbing for the pagebuilder JSON admin API.
 *
 * All endpoints live under `/api/pagebuilder` and return JSON. We use
 * plain fetch + same-origin cookies for auth, plus an `X-CSRF-Token`
 * header on every mutating request (token is read from the
 * `pagebuilder_csrf` cookie set by the view layer).
 */

import { keys, translate } from './i18n';

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

/** How many characters of an unrecognised error body are worth showing. */
const MAX_BODY_SNIPPET = 200;

/**
 * FastAPI's 422 body, as a sentence rather than as its wire format.
 *
 * `detail` is a list of Pydantic errors there. `loc` reads ["body", "<field>"];
 * the wrapper is noise to whoever is reading the message.
 */
export function fromValidationErrors(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) return null;
  const parts: string[] = [];
  for (const entry of detail) {
    const item = entry as { loc?: unknown; msg?: unknown };
    const field = Array.isArray(item.loc)
      ? item.loc.filter((p) => p !== 'body' && typeof p !== 'number').join('.')
      : '';
    const message =
      typeof item.msg === 'string' && item.msg
        ? item.msg
        : translate(keys.pagebuilder.errors.not_valid);
    parts.push(
      field ? translate(keys.pagebuilder.errors.field_message, { field, message }) : message,
    );
  }
  return parts.join('; ');
}

/**
 * A message a person can read, from whatever the server actually sent.
 *
 * The old version interpolated the whole response body. When a route answers
 * 404 with the Inertia *HTML shell* rather than JSON — which the admin routes
 * do — that put the entire document on screen: the permissions list, the i18n
 * catalogue and the sidebar menu JSON, rendered as the error text of a media
 * asset that simply did not exist.
 *
 * So: prefer the API's own `detail`, fall back to the status, and never render
 * a markup body as prose.
 *
 * The parse is attempted whatever the content-type claims. Gating on
 * `application/json` first would throw away a perfectly good `detail` from a
 * response that merely mislabelled itself, and the try/catch plus the markup
 * guard below already make the attempt safe.
 *
 * Deliberately a sibling of `news/utils/http.ts`'s `errorFrom`, and the two
 * must be changed together: they answer the same question for the same
 * backend, and a difference between them shows up as one module explaining a
 * failure while the other shrugs at it. Both are covered by unit tests that
 * assert the same six cases.
 */
export async function errorMessage(response: Response): Promise<string> {
  const fallback = translate(keys.pagebuilder.errors.request_failed, {
    status: response.status,
    statusText: response.statusText,
  }).trim();
  const body = await response.text().catch(() => '');
  if (!body) return fallback;

  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed.detail === 'string' && parsed.detail.trim()) return parsed.detail;
    // FastAPI's 422 sends a *list* of Pydantic errors. Without this the author
    // who typed a space into a URL field got "Request failed (422
    // Unprocessable Entity)" and no clue which field or why.
    const validation = fromValidationErrors(parsed.detail);
    if (validation) return validation;
  } catch {
    // Not JSON at all. Fall through to the text handling below.
  }

  // Anything that looks like a document is structure, not a message.
  if (/^\s*[<{[]/.test(body)) return fallback;
  const snippet = body.trim().slice(0, MAX_BODY_SNIPPET);
  return snippet
    ? translate(keys.pagebuilder.errors.request_failed_snippet, { message: fallback, snippet })
    : fallback;
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
    throw new Error(await errorMessage(response));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
