/** Shared fetch plumbing for the news API clients.
 *
 * Split out of `api.ts` so the taxonomy client reuses one CSRF read and one
 * error decoder rather than growing a second copy that drifts from it.
 */

import { keys, translate } from './i18n';

export const BASE = '/api/news';

const CSRF_COOKIE = 'news_csrf';

export function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/** How many characters of an unrecognised error body are worth showing. */
const MAX_BODY_SNIPPET = 200;

/** A failed response, keeping its status so a caller can tell a stale write
 *  (409) or a vanished article (404) from any other failure. */
export class HttpError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
  }
}

export function isHttpStatus(e: unknown, status: number): boolean {
  return e instanceof HttpError && e.status === status;
}

/** Turn a failed response into something worth showing a person.
 *
 * The body is only useful when it is our own JSON `detail`. An HTML error page
 * — which is what an auth or CSRF failure returns — would otherwise be thrown
 * verbatim and rendered as a wall of markup, leaking the whole Inertia payload
 * into the DOM.
 *
 * Deliberately a sibling of `pagebuilder/utils/request.ts`'s `errorMessage`,
 * and the two must be changed together: they answer the same question for the
 * same backend, and a difference between them shows up as one module
 * explaining a failure while the other shrugs at it.
 */
export async function errorFrom(response: Response): Promise<HttpError> {
  const body = await response.text().catch(() => '');
  const fallback = translate(keys.news.errors.request_failed, {
    status: response.status,
    statusText: response.statusText,
  }).trim();
  if (!body) return new HttpError(fallback, response.status);

  try {
    const detail = (JSON.parse(body) as { detail?: unknown }).detail;
    if (typeof detail === 'string' && detail.trim()) return new HttpError(detail, response.status);
    const validation = fromValidationErrors(detail);
    if (validation) return new HttpError(validation, response.status);
  } catch {
    // Not JSON — fall through rather than echo markup.
  }

  // Anything that looks like a document is structure, not a message.
  if (/^\s*[<{[]/.test(body)) return new HttpError(fallback, response.status);
  const snippet = body.trim().slice(0, MAX_BODY_SNIPPET);
  return new HttpError(
    snippet
      ? translate(keys.news.errors.request_failed_snippet, { message: fallback, snippet })
      : fallback,
    response.status,
  );
}

/**
 * FastAPI's 422 body, as a sentence rather than as its wire format.
 *
 * ``detail`` is a *list* of Pydantic errors there, not a string, so stringifying
 * it put `[{"type":"string_pattern_mismatch","loc":["body","slug"],…}]` in front
 * of an author who had simply typed a space into a URL field.
 */
export function fromValidationErrors(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) return null;
  const parts: string[] = [];
  for (const entry of detail) {
    const item = entry as { type?: unknown; loc?: unknown; msg?: unknown; ctx?: unknown };
    // `loc` is ["body", "<field>"]; the wrapper is noise to the reader.
    const field = Array.isArray(item.loc)
      ? item.loc.filter((p) => p !== 'body' && typeof p !== 'number').join('.')
      : '';
    parts.push(describeError(item, field));
  }
  return parts.join('; ');
}

/** One Pydantic error as a sentence. The common types get their own wording;
 *  anything else keeps the server's `msg`, which is at least readable. */
function describeError(
  item: { type?: unknown; msg?: unknown; ctx?: unknown },
  field: string,
): string {
  const e = keys.news.errors;
  const ctx = (item.ctx ?? {}) as { max_length?: unknown; min_length?: unknown };
  const name = field || translate(e.this_field);
  switch (item.type) {
    case 'string_pattern_mismatch':
      return field === 'slug'
        ? translate(keys.news.inspector.slug_invalid)
        : translate(e.pattern_mismatch, { field: name });
    case 'string_too_long':
      return typeof ctx.max_length === 'number'
        ? translate(e.too_long, { field: name, max: ctx.max_length })
        : translate(e.too_long_generic, { field: name });
    case 'string_too_short':
      return typeof ctx.min_length === 'number' && ctx.min_length > 1
        ? translate(e.too_short, { field: name, min: ctx.min_length })
        : translate(e.required, { field: name });
    case 'missing':
      return translate(e.required, { field: name });
    default: {
      const message = typeof item.msg === 'string' && item.msg ? item.msg : translate(e.not_valid);
      return field ? translate(e.field_message, { field, message }) : message;
    }
  }
}

/** GET returning JSON, with the abort signal the callers all need. */
export async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
    signal,
  });
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as T;
}

export async function write<T>(path: string, method: string, body?: unknown): Promise<T | null> {
  const token = readCookie(CSRF_COOKIE);
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(token ? { 'X-CSRF-Token': token } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await errorFrom(response);
  return response.status === 204 ? null : ((await response.json()) as T);
}
