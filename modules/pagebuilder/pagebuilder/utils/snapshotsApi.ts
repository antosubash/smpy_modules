/**
 * Client for the content snapshot endpoints.
 *
 * Built on the shared `request` helper so CSRF, credentials and error-message
 * extraction behave exactly as they do everywhere else in this admin — a
 * bundle rejected for being malformed should read as the server's own
 * sentence, not as "Request failed (422)".
 */

import { BASE, request } from './request';

export type SnapshotSource = 'manual' | 'upload' | 'pre_restore';
export type ImportStatus = 'pending' | 'approved' | 'rejected';

export interface SnapshotManifest {
  format_version: number;
  created_at: string;
  pages: { slug: string; title: string; status: string; parent_slug: string | null }[];
  layout: { header: number; footer: number };
  counts: { pages: number; redirects: number; media: number };
  missing_media: string[];
}

export interface Snapshot {
  id: number;
  note: string | null;
  source: SnapshotSource;
  format_version: number;
  manifest: SnapshotManifest;
  size_bytes: number;
  created_at: string | null;
  created_by: string | null;
}

export interface PagePlanEntry {
  slug: string;
  title: string | null;
  added?: number;
  removed?: number;
  changed?: number;
}

export interface ImportPlan {
  pages: {
    new: PagePlanEntry[];
    overwritten: PagePlanEntry[];
    unchanged: PagePlanEntry[];
    untouched: PagePlanEntry[];
  };
  layout: { header: number; footer: number };
  redirects: { added: string[]; removed: string[]; dropped: string[] };
}

export interface PendingImport {
  id: number;
  snapshot_id: number;
  plan: ImportPlan;
  status: ImportStatus;
  note: string | null;
  created_at: string | null;
  created_by: string | null;
}

export interface ApplyResult {
  pages_created: number;
  pages_updated: number;
  media_added: number;
  redirects: number;
  redirects_dropped: string[];
}

export function listSnapshots(): Promise<{ items: Snapshot[] }> {
  return request<{ items: Snapshot[] }>('/snapshots');
}

export function takeSnapshot(note?: string): Promise<Snapshot> {
  return request<Snapshot>('/snapshots', {
    method: 'POST',
    body: JSON.stringify({ note: note || null }),
  });
}

export function uploadBundle(file: File): Promise<Snapshot> {
  const form = new FormData();
  form.append('file', file);
  return request<Snapshot>('/snapshots/upload', { method: 'POST', body: form });
}

export function deleteSnapshot(id: number): Promise<void> {
  return request<void>(`/snapshots/${id}`, { method: 'DELETE' });
}

export function requestRestore(id: number): Promise<PendingImport> {
  return request<PendingImport>(`/snapshots/${id}/restore`, { method: 'POST' });
}

export function approveImport(id: number): Promise<ApplyResult> {
  return request<ApplyResult>(`/imports/${id}/approve`, { method: 'POST' });
}

export function rejectImport(id: number, note?: string): Promise<PendingImport> {
  return request<PendingImport>(`/imports/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ note: note || null }),
  });
}

/**
 * Where a snapshot's zip lives.
 *
 * A plain URL rather than a fetch: letting the browser navigate to it gives
 * the real Save-as dialog and the filename the server chose, which an
 * in-memory blob download would have to reinvent.
 */
export function downloadUrl(id: number): string {
  return `${BASE}/snapshots/${id}/download`;
}
