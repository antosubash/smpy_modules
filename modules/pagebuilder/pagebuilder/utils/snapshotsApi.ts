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
  layout: {
    header: number;
    footer: number;
    header_present?: boolean;
    footer_present?: boolean;
  };
  counts: { pages: number; redirects: number; media: number };
  missing_media: string[];
  /** Every section the bundle carries, pagebuilder's own included (#80). */
  contents?: { section: string; version?: number; counts?: Record<string, number> }[];
  /** Sections the capture left out: its taker lacked their permissions. */
  omitted?: SectionNote[];
}

/** How the screens name a contributed section registered on this host (#80).
 *  Both keys are the contributor's own, resolved when rendered. */
export interface SectionLabels {
  section: string;
  label_key: string;
  count_label_keys: Record<string, string>;
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
  locale?: string | null;
  title: string | null;
  added?: number;
  removed?: number;
  changed?: number;
  /** The live page under this slug is in the trash; restoring brings it back. */
  revived?: boolean;
  /** The page was renamed since the snapshot: its slug today. Restoring moves
   *  it back to `slug` and redirects this one to it. */
  renamed_from?: string;
}

export interface ImportPlan {
  pages: {
    new: PagePlanEntry[];
    overwritten: PagePlanEntry[];
    unchanged: PagePlanEntry[];
    untouched: PagePlanEntry[];
  };
  layout: {
    header: number;
    footer: number;
    header_present?: boolean;
    footer_present?: boolean;
  };
  redirects: { added: string[]; removed: string[]; dropped: string[] };
  /** What each contributed section would do (#80). */
  sections?: SectionPlanEntry[];
  /** Sections the stager may not restore: not planned, and left out. */
  denied?: SectionNote[];
  /** Sections the bundle carries that no module here can restore. */
  skipped?: SectionNote[];
  /** Sections registered here that the bundle does not carry. */
  absent?: SectionNote[];
}

export interface SectionPlanItem {
  title: string;
  slug: string;
  locale?: string | null;
  note_key?: string | null;
}

export interface SectionPlanLine {
  label_key: string;
  count: number;
  /** Empty for a reader who may not see the section's rows. */
  items: SectionPlanItem[];
  tone?: 'warning' | null;
}

export interface SectionPlanEntry {
  section: string;
  label_key: string;
  version?: number;
  lines: SectionPlanLine[];
  overwrites: number;
  /** Counts only: the reader lacks `permissions` to see the rows. */
  redacted?: boolean;
  /** The rows could not be read back; the counts stand. */
  details_unavailable?: boolean;
  reason_key?: string;
  note_key?: string;
  permissions?: string[];
}

/** A section named beside the plan rather than planned: denied, absent,
 *  omitted at capture, or skipped. Which keys are present says which. */
export interface SectionNote {
  section: string;
  label_key?: string;
  reason_key?: string;
  permissions?: string[];
  omitted?: boolean;
  version?: number | null;
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
  /** Per contributed section, the counts its apply reported. */
  sections?: Record<string, Record<string, number>>;
  /** Sections this restore left out for want of permission. */
  denied_sections?: SectionNote[];
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
