/** `/api/images` group endpoints: list, delete, regroup and a member's assignment. */

import { send } from './api';
import type { GroupItem, ImageItem, Page, RegroupResult } from './types';

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
): Promise<Page<GroupItem>> {
  const qs = after ? `?after=${encodeURIComponent(after)}` : '';
  const page = await send<GroupPage>(`${BASE}/collections/${collectionId}/groups${qs}`);
  return { ...page, total: null };
}

export function deleteGroup(id: string): Promise<void> {
  return send(`${BASE}/groups/${id}`, { method: 'DELETE' });
}

export function regroup(
  collectionId: string,
  body: { pattern: string; reassign: boolean; dry_run: boolean },
): Promise<RegroupResult> {
  return send(`${BASE}/collections/${collectionId}/regroup`, jsonBody('POST', body));
}

/** Move an image into a group (or out of one with `null`), optionally with a role. */
export function assignImage(
  imageId: string,
  change: { group_id?: string | null; group_role?: string | null },
): Promise<ImageItem> {
  return send(`${BASE}/images/${imageId}`, jsonBody('PATCH', change));
}
