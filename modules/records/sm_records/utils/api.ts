/**
 * Typed `fetch` client for `/api/records/*`.
 *
 * Mutations go through here, never through Inertia's `router.post()` — a
 * JSON response to an Inertia-form request is exactly what `SM018` flags,
 * because Inertia rejects a non-Inertia response. Navigation after a
 * mutation still uses Inertia's `router` (see the pages).
 *
 * `ApiError` carries the parsed body alongside the status so a caller can
 * branch on `status === 409` and read `body.current`, or walk `body.errors`
 * for per-field `422`s, instead of pattern-matching a message string.
 */

import { t } from '@simple-module-py/i18n';

import type {
  ApiErrorBody,
  FieldDef,
  FilterOp,
  SchemaPreview,
  SchemaPreviewJob,
  SchemaPreviewStarted,
  TypeRead,
} from './types';

const BASE = '/api/records';

/** `ApiError.status` for a request that never reached the server (UX review
 *  R12a). Not an HTTP status — `fetch` rejected — but callers already branch
 *  on `status`, and `0` is the one value no response can carry. */
export const OFFLINE_STATUS = 0;

/** Where an expired session is sent back to sign in (R12b). */
const LOGIN_PATH = '/users/login';

/** Long enough for the toast that says where you're going to be read. */
const REDIRECT_DELAY_MS = 1200;

/** `t` read inside the function, never at module scope, so a message follows
 *  the active locale rather than freezing against the boot one (CLAUDE.md
 *  § i18n) — and falls back to the literal when i18next isn't configured
 *  (unit tests, a failure before the app mounts). */
function translate(key: string, fallback: string): string {
  const message = t(key, { defaultValue: fallback }) as unknown;
  return typeof message === 'string' && message !== '' ? message : fallback;
}

// Writes rely on the framework's SameSite=Lax session-cookie baseline.
// A `RequiresCsrf`-style opt-in is a later phase.

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

/** Turn a validation-error list into "field: message; field: message". */
function summarizeErrors(errors: ValidationErrorLike[]): string {
  return errors
    .map((e) => (e.field ? `${e.field}: ${e.message}` : e.message))
    .filter(Boolean)
    .join('; ');
}

type ValidationErrorLike = { field?: string; message: string };

async function parseBody(response: Response): Promise<ApiErrorBody | null> {
  const text = await response.text().catch(() => '');
  if (!text) return null;
  try {
    return JSON.parse(text) as ApiErrorBody;
  } catch {
    return null;
  }
}

function messageFor(status: number, statusText: string, body: ApiErrorBody | null): string {
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
  const fallback = `Request failed (${status} ${statusText})`.trim();
  if (!body) return fallback;
  if (body.errors?.length) return summarizeErrors(body.errors);
  if (typeof body.detail === 'string' && body.detail.trim()) return body.detail;
  return fallback;
}

/** Send an expired session to the sign-in page, with `next` pointing back at
 *  the screen it was on, after a beat long enough to read the toast (R12b).
 *
 * Deliberately not immediate: a redirect that fires inside the rejected
 * promise replaces the page before the caller's own error handling runs, so
 * the person sees a blank sign-in form and no explanation of why they are
 * looking at one. */
function handleUnauthorized(): void {
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
function offlineError(): ApiError {
  return new ApiError(
    OFFLINE_STATUS,
    null,
    translate(
      'records.errors.offline',
      "Couldn't reach the server. Your changes are still on this page; try again.",
    ),
  );
}

/** Exported for `utils/api-history.ts`, split out of this file to stay under
 *  the 300-line cap — same `fetch` plumbing, a different slice of the API
 *  surface (schema/record revisions, referrers). Not meant as a public
 *  export beyond this package. */
export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const defaultHeaders = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  };
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      credentials: 'same-origin',
      ...init,
      headers: { ...defaultHeaders, ...(init.headers ?? {}) },
    });
  } catch {
    throw offlineError();
  }
  if (!response.ok) {
    const body = await parseBody(response);
    if (response.status === 401) handleUnauthorized();
    throw new ApiError(
      response.status,
      body,
      messageFor(response.status, response.statusText, body),
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Encode one filter term as the API's `field:op:value` grammar.
 *
 * `in` joins its values with a comma; every other op takes a single scalar.
 * Neither the field, op, nor value is escaped — the API has no escape syntax
 * to receive one if a value contained `:` or `,`. This module's own UI
 * (`FilterBar`) works around that for `,` by never offering `in` in the
 * first place (F6): `deps._parse_filter` does a bare `value.split(",")`, so
 * any value that itself contains a comma would silently split into extra
 * terms. `in` stays here, and in `FilterOp`, for a caller outside the UI
 * that controls its own values and knows they're comma-free. */
export function buildFilterParam(
  field: string,
  op: FilterOp,
  value: string | number | boolean | string[],
): string {
  const encoded = Array.isArray(value) ? value.join(',') : String(value);
  return `${field}:${op}:${encoded}`;
}

// ---- Types --------------------------------------------------------------

export async function listTypes(): Promise<{ items: TypeRead[] }> {
  return request('/types');
}

/** Mirrors the API's `TypeCreate`: everything collects into one POST. */
export type CreateTypePayload = {
  key: string;
  label: string;
  label_plural?: string;
  fields?: FieldDef[];
  description?: string;
  icon?: string;
  is_public?: boolean;
  allowed_roles?: string[];
  display_field?: string;
  slug_field?: string;
  translatable?: boolean;
  /** The one request that may set it (Phase 5 §6.2). Omitted — never sent as
   *  `null` — when the new type goes in the shared tables, so the server's
   *  own default is what decides. */
  collection?: string;
  /** Opts the new type into its own admin sidebar entry (per-type sidebar
   *  entries design contract). Omitted when off — the server default is the
   *  same `false`. */
  show_in_menu?: boolean;
};

export function createType(payload: CreateTypePayload): Promise<TypeRead> {
  return request('/types', { method: 'POST', body: JSON.stringify(payload) });
}

export function getType(key: string): Promise<TypeRead> {
  return request(`/types/${encodeURIComponent(key)}`);
}

/** `PUT`'s body beyond the changed top-level keys — Phase 3's two retry
 *  paths for the two 409 shapes §8.2/§8.8 define: `force` applies a
 *  restrictive change anyway and marks failing records invalid, `orphaned`
 *  resolves a re-added key that still holds `_orphaned` values. */
export type UpdateTypeChanges = Record<string, unknown> & {
  force?: boolean;
  orphaned?: 'restore' | 'discard';
};

export function updateType(
  key: string,
  expectedVersion: number,
  changes: UpdateTypeChanges,
): Promise<TypeRead> {
  return request(`/types/${encodeURIComponent(key)}`, {
    method: 'PUT',
    body: JSON.stringify({ expected_version: expectedVersion, ...changes }),
  });
}

export function deleteType(key: string, confirmRecordCount: number): Promise<void> {
  const qs = new URLSearchParams({ confirm_record_count: String(confirmRecordCount) });
  return request(`/types/${encodeURIComponent(key)}?${qs.toString()}`, { method: 'DELETE' });
}

/** Omit a pointer to leave it unchanged, send `null` to clear it (F5). */
export type SchemaPreviewBody = {
  fields: FieldDef[];
  display_field: string | null;
  slug_field: string | null;
  /** Scan the records even when the diff is empty — what "Check records"
   *  sends. Re-previewing the saved schema is by construction a preview of no
   *  change, and without this the server skips the scan and answers
   *  `failing: 0` without having read a record. */
  rescan?: boolean;
};

/** `POST /types/{key}/schema/preview` — writes nothing; classifies the
 *  proposed schema and dry-runs it (design §8.9).
 *
 * Resolves to the report on a type small enough to scan inside the request,
 * and to a `{job, status}` handle above `preview_sync_limit` (F10). The two
 * are told apart by the presence of `job`, not by the status code, because
 * `request` does not surface one. */
export function previewSchema(
  key: string,
  body: SchemaPreviewBody,
): Promise<SchemaPreview | SchemaPreviewStarted> {
  return request(`/types/${encodeURIComponent(key)}/schema/preview`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/** One poll of a deferred preview (F10). A 404 means this process no longer
 *  holds the job — the registry is in-process by design — and the caller's
 *  answer is to preview again, which is free because a preview writes
 *  nothing. */
export function getPreviewJob(key: string, job: string): Promise<SchemaPreviewJob> {
  return request(`/types/${encodeURIComponent(key)}/schema/preview/${encodeURIComponent(job)}`);
}

/** Manually kick a stuck reindex (§8.9's health check names it). */
export function reindexType(key: string): Promise<{ scheduled: boolean }> {
  return request(`/types/${encodeURIComponent(key)}/reindex`, { method: 'POST' });
}

// Type-schema revisions, record revisions and referrers live in
// `utils/api-history.ts` — kept out of here for the 300-line cap. Record CRUD
// (list/create/get/update/delete/restore/purge) lives in `utils/api-records.ts`
// for the same reason — adding `show_in_menu` to `CreateTypePayload` above is
// what tipped this file over the cap.
