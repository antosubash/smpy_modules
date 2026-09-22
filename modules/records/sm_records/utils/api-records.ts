/**
 * Record CRUD (list/create/get/update/delete/restore/purge) for
 * `/api/records/*`.
 *
 * Split out of `api.ts` to keep that file under the 300-line cap (design
 * §12) — same `request()`/`ApiError` plumbing, just the record-instance
 * slice of the API surface rather than the type-schema one. Record
 * *revisions* and referrers live in a third file, `utils/api-history.ts`,
 * split out for the same reason before this one existed.
 */

import { request } from './api';
import type { RecordPage, RecordRead, RecordStatus } from './types';

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

/** The five whole-record transitions `POST …/records/bulk` takes. */
export type BulkAction = 'trash' | 'restore' | 'purge' | 'publish' | 'unpublish';

/** One record the server would not apply the action to, and why. `status` is
 *  what that record alone would have answered. */
export type BulkFailure = { uuid: string; status: number; message: string };

/** The `report` a refused batch carries in its `409` body. Nothing was
 *  written — the caller deselects what this names and sends the rest. */
export type BulkReport = { action: BulkAction; requested: number; failed: BulkFailure[] };

export type BulkResult = {
  action: BulkAction;
  requested: number;
  changed: number;
  /** Records a `trash` reached through an `on_delete: cascade` relation and
   *  which the request never named. */
  cascaded: number;
};

/** All or nothing: a batch that refuses one record refuses all of them, with
 *  a `409` whose `body.report` is a `BulkReport` (see `ApiError`). */
export function bulkRecords(
  typeKey: string,
  action: BulkAction,
  uuids: string[],
  expectedVersions?: Record<string, number>,
): Promise<BulkResult> {
  return request(`/types/${encodeURIComponent(typeKey)}/records/bulk`, {
    method: 'POST',
    body: JSON.stringify({
      action,
      uuids,
      ...(expectedVersions ? { expected_versions: expectedVersions } : {}),
    }),
  });
}

export type TrashEmptied = { purged: number; filtered: boolean };

/** Purge the type's whole trash, or — with the list's own `filter=` term —
 *  the part of it the screen is showing. Takes no uuids and is not bounded by
 *  `max_bulk_records`. */
export function emptyTrash(typeKey: string, filter?: string | null): Promise<TrashEmptied> {
  const qs = filter ? `?${new URLSearchParams({ filter }).toString()}` : '';
  return request(`/types/${encodeURIComponent(typeKey)}/records/trash/empty${qs}`, {
    method: 'POST',
  });
}
