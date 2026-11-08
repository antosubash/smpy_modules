/** Shared fetch plumbing for the newsletter API client: one CSRF header, one
 *  error decoder. The server's refusals are `{detail, code}`; the code is what
 *  a screen translates (`errorMessage` below), never the English `detail`.
 */

import { csrfHeaders, isCsrfRefusal } from './csrf';
import { keys, type Translate } from './i18n';

export const BASE = '/api/newsletter';

/** The catalogue key for a failure no code names (and for a CSRF refusal). */
const CSRF_CODE = 'csrf_failed';

/** A failed response: its status (409 stale vs. 404 gone) and the server's code. */
export class HttpError extends Error {
  readonly status: number;
  readonly code: string | null;
  constructor(message: string, status: number, code: string | null = null) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
    this.code = code;
  }
}

export function isHttpStatus(e: unknown, status: number): boolean {
  return e instanceof HttpError && e.status === status;
}

/** Whether `e` is a failure carrying this server error code. */
export function isCode(e: unknown, code: string): boolean {
  return e instanceof HttpError && e.code === code;
}

/** Only our own `{code}` is trusted; an HTML error page or a framework 422
 *  list is structure, not a message, and is never echoed. */
export async function errorFrom(response: Response): Promise<HttpError> {
  const body = await response.text().catch(() => '');
  let code: string | null = null;
  let message = `${response.status} ${response.statusText}`.trim();
  try {
    const parsed = JSON.parse(body) as { detail?: unknown; code?: unknown };
    if (isCsrfRefusal(response.status, parsed.detail)) code = CSRF_CODE;
    else if (typeof parsed.code === 'string' && parsed.code) code = parsed.code;
    if (typeof parsed.detail === 'string' && parsed.detail.trim()) message = parsed.detail;
  } catch {
    // Not JSON — keep the status line.
  }
  return new HttpError(message, response.status, code);
}

/** The `invalid_campaign` details (`<field>: <problem>`) that name what to fix.
 *  The detail is only looked up here, never shown. */
const INVALID_CAMPAIGN: Record<string, string> = {
  'subject: required': keys.newsletter.errors_field.subject_required,
  'scheduled_at: out of range': keys.newsletter.errors_field.schedule_out_of_range,
  'at: out of range': keys.newsletter.errors_field.schedule_out_of_range,
};

/** What a person is shown: the catalogue's text for the server's code (for
 *  `invalid_campaign`, the field's own line when the detail is a known one),
 *  else the generic line. Never the raw `detail`. */
export function errorMessage(e: unknown, t: Translate): string {
  const errors = keys.newsletter.errors as Record<string, string>;
  const code = e instanceof HttpError ? e.code : null;
  const detail = e instanceof HttpError ? e.message : '';
  if (code === 'invalid_campaign' && Object.hasOwn(INVALID_CAMPAIGN, detail)) {
    return t(INVALID_CAMPAIGN[detail]);
  }
  if (code && Object.hasOwn(errors, code) && code !== 'generic') return t(errors[code]);
  return t(keys.newsletter.errors.generic);
}

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
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...csrfHeaders(method),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await errorFrom(response);
  return response.status === 204 ? null : ((await response.json()) as T);
}
