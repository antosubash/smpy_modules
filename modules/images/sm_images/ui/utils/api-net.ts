/**
 * The `fetch` plumbing every call to `/api/images/*` (and the sharing API the
 * share dialog uses) shares: the error type, the parsed body, the sentence a
 * status or an images error `code` gets, and the two branches that are about
 * the connection rather than the request - an expired session and no server.
 */

import en from '../../locales/en.json';
import { isCsrfRefusal } from './csrf';
import { keys, translate } from './i18n';
import type { ApiErrorBody } from './types';

const LOGIN_PATH = '/users/login';
/** Long enough for the toast that says where you are going to be read. */
const REDIRECT_DELAY_MS = 1200;
/** `ApiError.status` of a request that never reached the server. */
export const OFFLINE_STATUS = 0;

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

export async function parseBody(response: Response): Promise<ApiErrorBody | null> {
  const text = await response.text().catch(() => '');
  if (!text) return null;
  try {
    return JSON.parse(text) as ApiErrorBody;
  } catch {
    return null;
  }
}

/** The translated sentence of an upload/ingest error code, if there is one. */
export function codeMessage(code: string | null | undefined): string | null {
  if (!code || !Object.hasOwn(en.errors, code)) return null;
  return translate(`images.errors.${code}`);
}

export function messageFor(status: number, body: ApiErrorBody | null): string {
  if (status === 401) return translate(keys.images.errors.session_expired);
  if (isCsrfRefusal(status, body?.detail)) return translate(keys.images.errors.csrf_failed);
  const coded = codeMessage(body?.code);
  if (coded) return coded;
  if (status >= 500) return translate(keys.images.errors.server_error);
  if (body?.errors?.length) {
    return body.errors.map((e) => (e.field ? `${e.field}: ${e.message}` : e.message)).join('; ');
  }
  if (typeof body?.detail === 'string' && body.detail.trim()) return body.detail;
  return translate(keys.images.errors.request_failed, { status });
}

/** Send an expired session back to sign in, after a beat long enough to read
 *  the toast; immediate would replace the page before the caller reports. */
export function handleUnauthorized(): void {
  if (typeof window === 'undefined') return;
  const next = `${window.location.pathname}${window.location.search}`;
  const target = `${LOGIN_PATH}?next=${encodeURIComponent(next)}`;
  window.setTimeout(() => window.location.assign(target), REDIRECT_DELAY_MS);
}

/** What to show for a caught value: an `Error`'s message, else its text. */
export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function offlineError(): ApiError {
  return new ApiError(OFFLINE_STATUS, null, translate(keys.images.errors.offline));
}
