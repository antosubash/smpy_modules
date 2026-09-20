/**
 * Schema-revision, record-revision and referrer reads for `/api/records/*`.
 *
 * Split out of `api.ts` to keep that file under the 300-line cap (design
 * §12) — same `request()`/`ApiError` plumbing, just a different slice of the
 * API surface: "what did this used to look like" and "what points at this".
 */

import { request } from './api';
import type {
  RecordRead,
  RecordRevision,
  RecordRevisionDetail,
  ReferrersResponse,
  TypeRead,
  TypeRevision,
} from './types';

// ---- Type revisions ---------------------------------------------------------

export function listTypeRevisions(key: string): Promise<{ items: TypeRevision[] }> {
  return request(`/types/${encodeURIComponent(key)}/revisions`);
}

/** A schema rollback shares `updateType`'s body shape and 409s (§8.6). */
export function restoreTypeRevision(
  key: string,
  version: number,
  body: { expected_version: number; force?: boolean; orphaned?: 'restore' | 'discard' },
): Promise<TypeRead> {
  return request(`/types/${encodeURIComponent(key)}/revisions/${version}/restore`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// ---- Record revisions -------------------------------------------------------

export function listRevisions(typeKey: string, uuid: string): Promise<{ items: RecordRevision[] }> {
  return request(
    `/types/${encodeURIComponent(typeKey)}/records/${encodeURIComponent(uuid)}/revisions`,
  );
}

export function getRecordRevision(
  typeKey: string,
  uuid: string,
  id: number,
): Promise<RecordRevisionDetail> {
  return request(
    `/types/${encodeURIComponent(typeKey)}/records/${encodeURIComponent(uuid)}/revisions/${id}`,
  );
}

export function restoreRecordRevision(
  typeKey: string,
  uuid: string,
  id: number,
  expectedVersion: number,
): Promise<RecordRead> {
  return request(
    `/types/${encodeURIComponent(typeKey)}/records/${encodeURIComponent(uuid)}/revisions/${id}/restore`,
    { method: 'POST', body: JSON.stringify({ expected_version: expectedVersion }) },
  );
}

// ---- Referrers ---------------------------------------------------------------

export type ListReferrersParams = { page?: number; page_size?: number };

/** `GET .../records/{uuid}/referrers` — what points at this record (design
 *  §9), for the editor's "Referenced by" panel and the referrer-aware delete
 *  dialog. */
export function listReferrers(
  typeKey: string,
  uuid: string,
  params: ListReferrersParams = {},
): Promise<ReferrersResponse> {
  const qs = new URLSearchParams();
  if (params.page !== undefined) qs.set('page', String(params.page));
  if (params.page_size !== undefined) qs.set('page_size', String(params.page_size));
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return request(
    `/types/${encodeURIComponent(typeKey)}/records/${encodeURIComponent(uuid)}/referrers${suffix}`,
  );
}
