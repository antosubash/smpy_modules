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
  RecordRevision,
  RecordStatus,
  TypeRead,
} from './types';

const BASE = '/api/records';

/** Mirrors the naming the `ai`/`pagebuilder` modules use for their own CSRF
 *  cookie (`sm_ai_csrf`, `pagebuilder_csrf`): the view layer mints a token
 *  into the session and mirrors it here for JS to echo back. Tolerant when
 *  absent — same as those modules, the header is simply omitted and the
 *  server skips enforcement in that case. */
const CSRF_COOKIE = 'sm_records_csrf';

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function csrfHeader(): Record<string, string> {
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE}=([^;]*)`));
  return match ? { 'X-CSRF-Token': decodeURIComponent(match[1]) } : {};
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

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase();
  const csrf = UNSAFE_METHODS.has(method) ? csrfHeader() : {};
  const response = await fetch(`${BASE}${path}`, {
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...csrf,
      ...(init.headers ?? {}),
    },
    ...init,
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
 * Neither the field, op, nor value is escaped — none of the callers in this
 * module produce a value containing `:` or `,`, and the API has no escape
 * syntax to receive one if they did. */
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

export type CreateTypePayload = {
  key: string;
  label: string;
  label_plural: string;
  fields: FieldDef[];
};

export function createType(payload: CreateTypePayload): Promise<TypeRead> {
  return request('/types', { method: 'POST', body: JSON.stringify(payload) });
}

export function getType(key: string): Promise<TypeRead> {
  return request(`/types/${encodeURIComponent(key)}`);
}

export function updateType(
  key: string,
  expectedVersion: number,
  changes: Record<string, unknown>,
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

// ---- Records --------------------------------------------------------------

export type ListRecordsParams = {
  page?: number;
  page_size?: number;
  sort?: string;
  filter?: string;
};

export function listRecords(typeKey: string, params: ListRecordsParams = {}): Promise<RecordPage> {
  const qs = new URLSearchParams();
  if (params.page !== undefined) qs.set('page', String(params.page));
  if (params.page_size !== undefined) qs.set('page_size', String(params.page_size));
  if (params.sort) qs.set('sort', params.sort);
  if (params.filter) qs.set('filter', params.filter);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return request(`/types/${encodeURIComponent(typeKey)}/records${suffix}`);
}

export type RecordWritePayload = {
  data: Record<string, unknown>;
  status?: RecordStatus;
  slug?: string | null;
  position?: number;
};

export function createRecord(typeKey: string, payload: RecordWritePayload): Promise<RecordRead> {
  return request(`/types/${encodeURIComponent(typeKey)}/records`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getRecord(typeKey: string, uuid: string): Promise<RecordRead> {
  return request(`/types/${encodeURIComponent(typeKey)}/records/${uuid}`);
}

export function updateRecord(
  typeKey: string,
  uuid: string,
  expectedVersion: number,
  payload: RecordWritePayload,
): Promise<RecordRead> {
  return request(`/types/${encodeURIComponent(typeKey)}/records/${uuid}`, {
    method: 'PUT',
    body: JSON.stringify({ expected_version: expectedVersion, ...payload }),
  });
}

export function deleteRecord(typeKey: string, uuid: string): Promise<void> {
  return request(`/types/${encodeURIComponent(typeKey)}/records/${uuid}`, { method: 'DELETE' });
}

export function restoreRecord(typeKey: string, uuid: string): Promise<RecordRead> {
  return request(`/types/${encodeURIComponent(typeKey)}/records/${uuid}/restore`, {
    method: 'POST',
  });
}

export function purgeRecord(typeKey: string, uuid: string): Promise<void> {
  return request(`/types/${encodeURIComponent(typeKey)}/records/${uuid}/purge`, {
    method: 'DELETE',
  });
}

export function listRevisions(typeKey: string, uuid: string): Promise<{ items: RecordRevision[] }> {
  return request(`/types/${encodeURIComponent(typeKey)}/records/${uuid}/revisions`);
}
