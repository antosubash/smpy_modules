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

import type {
  ApiErrorBody,
  FieldDef,
  FilterOp,
  RecordPage,
  RecordRead,
  RecordStatus,
  SchemaPreview,
  SchemaPreviewJob,
  SchemaPreviewStarted,
  TypeRead,
} from './types';

const BASE = '/api/records';

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
  const fallback = `Request failed (${status} ${statusText})`.trim();
  if (!body) return fallback;
  if (body.errors?.length) return summarizeErrors(body.errors);
  if (typeof body.detail === 'string' && body.detail.trim()) return body.detail;
  return fallback;
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
  const response = await fetch(`${BASE}${path}`, {
    credentials: 'same-origin',
    ...init,
    headers: { ...defaultHeaders, ...(init.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await parseBody(response);
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
// `utils/api-history.ts` — kept out of here for the 300-line cap.

// ---- Records --------------------------------------------------------------

export type ListRecordsParams = {
  page?: number;
  page_size?: number;
  sort?: string;
  filter?: string;
  /** `?after=<cursor>` — keyset pagination (F11). Mutually exclusive with
   *  `page`; sending both is a 400. */
  after?: string;
  /** `?total=false` drops the count statement, so `RecordPage.total` comes
   *  back `null` (F4). For a caller that pages with `after` and never renders
   *  the number, this is the cheaper request. */
  total?: boolean;
};

export function listRecords(typeKey: string, params: ListRecordsParams = {}): Promise<RecordPage> {
  const qs = new URLSearchParams();
  if (params.page !== undefined) qs.set('page', String(params.page));
  if (params.page_size !== undefined) qs.set('page_size', String(params.page_size));
  if (params.sort) qs.set('sort', params.sort);
  if (params.filter) qs.set('filter', params.filter);
  if (params.after) qs.set('after', params.after);
  if (params.total === false) qs.set('total', 'false');
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return request(`/types/${encodeURIComponent(typeKey)}/records${suffix}`);
}

export type RecordWritePayload = {
  data: Record<string, unknown>;
  status?: RecordStatus;
  slug?: string | null;
  position?: number;
};

/** `createRecord`'s body only — `locale` names the content locale to create
 *  the record in (defaults to the type's default content locale). There is
 *  no `locale` on an update: a record's language is fixed for its lifetime
 *  (design §4.3), and the API 422s an update that sends one. */
export type RecordCreatePayload = RecordWritePayload & { locale?: string };

export function createRecord(typeKey: string, payload: RecordCreatePayload): Promise<RecordRead> {
  return request(`/types/${encodeURIComponent(typeKey)}/records`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getRecord(typeKey: string, uuid: string): Promise<RecordRead> {
  return request(`/types/${encodeURIComponent(typeKey)}/records/${encodeURIComponent(uuid)}`);
}

export function updateRecord(
  typeKey: string,
  uuid: string,
  expectedVersion: number,
  payload: RecordWritePayload,
): Promise<RecordRead> {
  return request(`/types/${encodeURIComponent(typeKey)}/records/${encodeURIComponent(uuid)}`, {
    method: 'PUT',
    body: JSON.stringify({ expected_version: expectedVersion, ...payload }),
  });
}

export function deleteRecord(typeKey: string, uuid: string): Promise<void> {
  return request(`/types/${encodeURIComponent(typeKey)}/records/${encodeURIComponent(uuid)}`, {
    method: 'DELETE',
  });
}

export function restoreRecord(typeKey: string, uuid: string): Promise<RecordRead> {
  return request(
    `/types/${encodeURIComponent(typeKey)}/records/${encodeURIComponent(uuid)}/restore`,
    { method: 'POST' },
  );
}

export function purgeRecord(typeKey: string, uuid: string): Promise<void> {
  return request(
    `/types/${encodeURIComponent(typeKey)}/records/${encodeURIComponent(uuid)}/purge`,
    { method: 'DELETE' },
  );
}

// Record revisions live in `utils/api-history.ts` alongside the type ones.
