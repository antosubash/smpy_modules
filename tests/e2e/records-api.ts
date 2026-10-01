import { expect, type Page } from '@playwright/test';

/**
 * The `records-*.spec.ts` suite's seeding layer: the module's own JSON API
 * (`/api/records/*`) driven through `page.request`, which shares the logged-in
 * context's cookie jar. Records writes ride the framework's `SameSite=Lax`
 * baseline and opt into no CSRF token (see `sm_records/utils/api.ts`), so
 * unlike `csrfHeader()` for pagebuilder there is no header to attach here.
 *
 * Split out of `records-helpers.ts` (300-line cap), which re-exports all of
 * it — specs keep importing from there.
 */

const BASE = '/api/records';

export type Json = Record<string, unknown>;

export type FieldDef = {
  key: string;
  type: string;
  label: string;
  required?: boolean;
  unique?: boolean;
  indexed?: boolean;
  default?: unknown;
  help?: string | null;
  constraints?: Json;
  options?: Json;
};

export type TypeRead = {
  key: string;
  label: string;
  label_plural: string;
  fields: Required<FieldDef>[];
  version: number;
  schema_version: number;
  display_field: string | null;
  slug_field: string | null;
  record_count: number;
  trashed_record_count: number;
  reindex_pending: Record<string, string>;
  translatable: boolean;
  show_in_menu: boolean;
  collection: string | null;
};

export type RecordRead = {
  uuid: string;
  version: number;
  data: Json;
  display_title: string;
  status: string;
  slug: string | null;
  locale: string;
  translation_group: string;
  position: number;
  is_deleted: boolean;
  invalid: { field: string; message: string }[];
};

/** `total` is capped at `max_count` (F4); `next_cursor` feeds `?after=` (F11). */
export type RecordPage = {
  items: RecordRead[];
  total: number;
  total_capped: boolean;
  page: number;
  page_size: number;
  next_cursor: string | null;
};

/**
 * A type key that is unique per run and still satisfies the server's
 * `^[a-z][a-z0-9_]*$` / 64-character rule — and is never `types` or `new`,
 * both of which would shadow a view route (`constants.RESERVED_TYPE_KEYS`).
 */
export function uniqueTypeKey(prefix = 'e2e'): string {
  const stamp = Date.now().toString(36);
  const salt = Math.random().toString(36).slice(2, 6);
  return `${prefix}_${stamp}_${salt}`.toLowerCase();
}

async function api<T>(
  page: Page,
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  data?: Json,
): Promise<T> {
  const response = await page.request.fetch(`${BASE}${path}`, {
    method,
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    ...(data === undefined ? {} : { data }),
  });
  if (!response.ok()) {
    throw new Error(`${method} ${path} → ${response.status()}: ${await response.text()}`);
  }
  if (response.status() === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Wait until a just-created row is readable over the API.
 *
 * Before framework 0.0.35 a write was committed in the session dependency's
 * exit code, which FastAPI runs *after* the response is delivered — so the
 * 201 could reach this process before the row was visible to the next
 * request (upstream GH #257). 0.0.35 commits before the response starts; the
 * read-back stays as a cheap guard, since every seed here creates something
 * and immediately writes to or reads it, and it waits on the row itself
 * instead of on a clock. */
async function readable(page: Page, path: string): Promise<void> {
  await expect.poll(async () => (await page.request.get(`${BASE}${path}`)).status()).toBe(200);
}

// ---- Types --------------------------------------------------------------

export async function apiCreateType(page: Page, body: Json): Promise<TypeRead> {
  const created = await api<TypeRead>(page, 'POST', '/types', body);
  await readable(page, `/types/${created.key}`);
  return created;
}

export function apiGetType(page: Page, key: string): Promise<TypeRead> {
  return api(page, 'GET', `/types/${key}`);
}

export async function apiUpdateType(
  page: Page,
  key: string,
  expectedVersion: number,
  changes: Json,
): Promise<TypeRead> {
  const updated = await api<TypeRead>(page, 'PUT', `/types/${key}`, {
    expected_version: expectedVersion,
    ...changes,
  });
  // Same GH #257 window as `readable`: the 200 can arrive before the commit,
  // and a page rendered in between (the sidebar sync reads the type row)
  // still shows the old value. Wait on the row's version, not on a clock.
  await expect.poll(async () => (await apiGetType(page, key)).version).toBe(updated.version);
  return updated;
}

export function apiListTypes(page: Page): Promise<{ items: TypeRead[] }> {
  return api(page, 'GET', '/types');
}

export async function apiDeleteType(page: Page, key: string, count: number): Promise<void> {
  await api(page, 'DELETE', `/types/${key}?confirm_record_count=${count}`);
}

// ---- Records ------------------------------------------------------------

export async function apiCreateRecord(page: Page, key: string, body: Json): Promise<RecordRead> {
  const created = await api<RecordRead>(page, 'POST', `/types/${key}/records`, body);
  await readable(page, `/types/${key}/records/${created.uuid}`);
  return created;
}

export function apiGetRecord(page: Page, key: string, uuid: string): Promise<RecordRead> {
  return api(page, 'GET', `/types/${key}/records/${uuid}`);
}

export function apiUpdateRecord(
  page: Page,
  key: string,
  uuid: string,
  expectedVersion: number,
  body: Json,
): Promise<RecordRead> {
  return api(page, 'PUT', `/types/${key}/records/${uuid}`, {
    expected_version: expectedVersion,
    ...body,
  });
}

export async function apiDeleteRecord(page: Page, key: string, uuid: string): Promise<void> {
  await api(page, 'DELETE', `/types/${key}/records/${uuid}`);
}

export function apiRestoreRecord(page: Page, key: string, uuid: string): Promise<RecordRead> {
  return api(page, 'POST', `/types/${key}/records/${uuid}/restore`);
}

export function apiListRecords(page: Page, key: string, query = ''): Promise<RecordPage> {
  return api(page, 'GET', `/types/${key}/records${query ? `?${query}` : ''}`);
}

// ---- Translations ---------------------------------------------------------

export function apiCreateTranslation(
  page: Page,
  key: string,
  uuid: string,
  body: Json,
): Promise<RecordRead> {
  return api(page, 'POST', `/types/${key}/records/${uuid}/translations`, body);
}
