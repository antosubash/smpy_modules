/**
 * The `fetch` plumbing every call to `/api/records/*` shares: the error
 * type, the parsed body, the message a status gets, and the two branches
 * that are about the *connection* rather than about the request — an
 * expired session and a server that is not there.
 *
 * Split out of `utils/api.ts` for R9: the import upload builds its own
 * `fetch` (it must, so the browser can choose the multipart boundary) and
 * therefore missed both. An expired session mid-import was
 * `Import failed (401)` in a toast with no redirect, and a dropped
 * connection was a raw `TypeError: Failed to fetch`. Neither is a thing this
 * module should say twice, so neither lives in `api.ts` any more.
 */

import { t } from '@simple-module-py/i18n';

import type { ApiErrorBody } from './types';

/** Where an expired session is sent back to sign in (R12b). */
const LOGIN_PATH = '/users/login';

/** Long enough for the toast that says where you're going to be read. */
const REDIRECT_DELAY_MS = 1200;

/** `t` read inside the function, never at module scope, so a message follows
 *  the active locale rather than freezing against the boot one (CLAUDE.md
 *  § i18n) — and falls back to the literal when i18next isn't configured
 *  (unit tests, a failure before the app mounts). */
export function translate(key: string, fallback: string): string {
  const message = t(key, { defaultValue: fallback }) as unknown;
  return typeof message === 'string' && message !== '' ? message : fallback;
}

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody | null;

  constructor(status: number, body: ApiErrorBody | null, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

type ValidationErrorLike = { field?: string; message: string };

/** Turn a validation-error list into "field: message; field: message". */
function summarizeErrors(errors: ValidationErrorLike[]): string {
  return errors
    .map((e) => (e.field ? `${e.field}: ${e.message}` : e.message))
    .filter(Boolean)
    .join('; ');
}

export async function parseBody(response: Response): Promise<ApiErrorBody | null> {
  const text = await response.text().catch(() => '');
  if (!text) return null;
  try {
    return JSON.parse(text) as ApiErrorBody;
  } catch {
    return null;
  }
}

export function messageFor(status: number, statusText: string, body: ApiErrorBody | null): string {
  // A 401 is never about this request's payload: the session went away while
  // the page stayed open, and the server's own "Not authenticated" says
  // nothing a person can act on. `handleUnauthorized` is what acts; this is
  // what it says while doing it (R12b).
  if (status === 401) {
    return translate(
      'records.errors.session_expired',
      'Your session has expired. Taking you to the sign-in page — your changes are still on this page until you leave it.',
    );
  }
  // U34: R12 covered the offline case (`OFFLINE_STATUS`) and 401 above; a
  // 5xx with no usable detail fell through to the raw status line —
  // "Request failed (500 Internal Server Error)" — machine text with no
  // statement of whether the write landed and no next step. A 5xx means
  // the server, not this request, is the problem, so the one honest "next
  // step" is "try again"; a 4xx this build doesn't otherwise recognise
  // keeps the status-line fallback, since that range usually does mean
  // something about the request itself worth showing verbatim for support
  // purposes.
  const fallback =
    status >= 500
      ? translate(
          'records.errors.server_error',
          "Something went wrong on the server. It's not clear whether your last change was saved — check before trying again.",
        )
      : `Request failed (${status} ${statusText})`.trim();
  if (!body) return fallback;
  if (body.errors?.length) return summarizeErrors(body.errors);
  if (typeof body.detail === 'string' && body.detail.trim()) return body.detail;
  return fallback;
}

/** `ApiError.status` for a request that never reached the server (UX review
 *  R12a). Not an HTTP status — `fetch` rejected — but callers already branch
 *  on `status`, and `0` is the one value no response can carry. */
export const OFFLINE_STATUS = 0;

// Writes rely on the framework's SameSite=Lax session-cookie baseline.
// A `RequiresCsrf`-style opt-in is a later phase.

/** Send an expired session to the sign-in page, with `next` pointing back at
 *  the screen it was on, after a beat long enough to read the toast (R12b).
 *
 * Deliberately not immediate: a redirect that fires inside the rejected
 * promise replaces the page before the caller's own error handling runs, so
 * the person sees a blank sign-in form and no explanation of why they are
 * looking at one. */
export function handleUnauthorized(): void {
  if (typeof window === 'undefined') return;
  const next = `${window.location.pathname}${window.location.search}`;
  const target = `${LOGIN_PATH}?next=${encodeURIComponent(next)}`;
  window.setTimeout(() => {
    window.location.assign(target);
  }, REDIRECT_DELAY_MS);
}

/** `fetch` rejects — DNS, a dropped connection, a server that is simply not
 *  there — rather than resolving with a status. Left alone that surfaces as
 *  `toast.error('Failed to fetch')` over a form full of unsaved work; as an
 *  `ApiError` it reaches every caller's existing branch and says the one
 *  thing that matters, which is that nothing was lost (R12a). */
export function offlineError(): ApiError {
  return new ApiError(
    OFFLINE_STATUS,
    null,
    translate(
      'records.errors.offline',
      "Couldn't reach the server. Your changes are still on this page; try again.",
    ),
  );
}
