/** `/api/images` group endpoints: list, create, edit, delete, regroup and a member's assignment. */

import { send } from './api';
import type { GroupItem, ImageItem, Page, RegroupJob, RegroupResult } from './types';

const BASE = '/api/images';

type GroupPage = { items: GroupItem[]; next_cursor: string | null };

const jsonBody = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
  headers: { 'Content-Type': 'application/json' },
});

/** A page of groups; `after` is the cursor (the last key of the previous page). */
export async function listGroups(
  collectionId: string,
  after?: string | null,
  limit?: number,
): Promise<Page<GroupItem>> {
  const qs = new URLSearchParams();
  if (after) qs.set('after', after);
  if (limit) qs.set('limit', String(limit));
  const suffix = qs.size ? `?${qs}` : '';
  const page = await send<GroupPage>(`${BASE}/collections/${collectionId}/groups${suffix}`);
  return { ...page, total: null };
}

export function createGroup(
  collectionId: string,
  body: { key: string; name?: string | null },
): Promise<GroupItem> {
  return send(`${BASE}/collections/${collectionId}/groups`, jsonBody('POST', body));
}

export function updateGroup(
  id: string,
  body: { key?: string; name?: string | null },
): Promise<GroupItem> {
  return send(`${BASE}/groups/${id}`, jsonBody('PATCH', body));
}

export function deleteGroup(id: string): Promise<void> {
  return send(`${BASE}/groups/${id}`, { method: 'DELETE' });
}

type RegroupBody = { pattern: string; reassign: boolean; dry_run: boolean };

/** A small collection answers with the counts; a big one with a job to poll. */
export function regroup(
  collectionId: string,
  body: RegroupBody,
): Promise<RegroupResult | { job_id: string }> {
  return send(`${BASE}/collections/${collectionId}/regroup`, jsonBody('POST', body));
}

export function getRegroup(id: string): Promise<RegroupJob> {
  return send(`${BASE}/regroups/${id}`);
}

export function cancelRegroup(id: string): Promise<RegroupJob> {
  return send(`${BASE}/regroups/${id}/cancel`, { method: 'POST' });
}

/** Move an image into a group (or out of one with `null`), optionally with a role. */
export function assignImage(
  imageId: string,
  change: { group_id?: string | null; group_role?: string | null },
): Promise<ImageItem> {
  return send(`${BASE}/images/${imageId}`, jsonBody('PATCH', change));
}
