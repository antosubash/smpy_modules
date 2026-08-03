/**
 * Fetch wrappers for the pagebuilder JSON admin API.
 *
 * All endpoints live under `/api/pagebuilder` and return JSON. We use
 * plain fetch + same-origin cookies for auth, plus an `X-CSRF-Token`
 * header on every mutating request (token is read from the
 * `pagebuilder_csrf` cookie set by the view layer).
 */

export type PageStatus = 'draft' | 'submitted_for_review' | 'published';

export type RevisionEvent = 'publish' | 'unpublish' | 'submit' | 'approve' | 'reject';

export interface PageRead {
  id: number;
  slug: string;
  title: string;
  status: PageStatus;
  has_published: boolean;
  meta_description: string | null;
  og_image: string | null;
  canonical_url: string | null;
  index_in_search: boolean;
  rejection_note: string | null;
  publish_at: string | null;
  unpublish_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface PageDetail extends PageRead {
  draft_data: Record<string, unknown>;
  published_data: Record<string, unknown> | null;
  json_ld: Record<string, unknown> | null;
}

export interface LayoutDetail {
  id: number;
  header_data: Record<string, unknown>;
  footer_data: Record<string, unknown>;
  created_at: string;
  updated_at: string | null;
}

export interface LayoutRevisionRead {
  id: number;
  layout_id: number;
  note: string | null;
  created_at: string;
  created_by: string | null;
}

export interface LayoutUpdate {
  header_data?: Record<string, unknown> | null;
  footer_data?: Record<string, unknown> | null;
  note?: string | null;
}

export interface PageRevisionRead {
  id: number;
  page_id: number;
  title: string;
  meta_description: string | null;
  og_image: string | null;
  event: RevisionEvent;
  note: string | null;
  created_at: string;
  created_by: string | null;
}

export interface MediaAssetVariant {
  filename: string;
  url: string;
  content_type: string;
  width: number;
  height: number | null;
  size_bytes: number;
}

export interface MediaAssetRead {
  id: number;
  filename: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  url: string;
  width: number | null;
  height: number | null;
  folder: string | null;
  variants: Record<string, MediaAssetVariant>;
  created_at: string;
}

export interface MediaListResponse {
  items: MediaAssetRead[];
  next_cursor: number | null;
  folders: string[];
}

export interface MediaListQuery {
  search?: string;
  content_type?: string;
  /**
   * Folder filter. Omit for "any folder", pass an empty string for
   * "Unfiled" (rows where folder IS NULL), or pass a path like
   * "marketing/heros" to match an exact folder.
   */
  folder?: string;
  min_size_bytes?: number;
  max_size_bytes?: number;
  cursor?: number;
  limit?: number;
}

interface PageWritePayload {
  title?: string;
  slug?: string;
  meta_description?: string | null;
  og_image?: string | null;
  canonical_url?: string | null;
  index_in_search?: boolean;
  json_ld?: Record<string, unknown> | null;
  draft_data?: Record<string, unknown>;
  publish_at?: string | null;
  unpublish_at?: string | null;
}

/**
 * Body for ``POST /pages/{id}/schedule``.
 *
 * A field's *presence* tells the server "act on me" — omit a field to
 * leave the stored value alone, send ``null`` to clear it, send an ISO
 * timestamp to set it. So ``{publish_at: "2026-…"}`` schedules a publish
 * without touching ``unpublish_at``.
 */
export interface ScheduleRequest {
  publish_at?: string | null;
  unpublish_at?: string | null;
}

const BASE = '/api/pagebuilder';

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const CSRF_COOKIE = 'pagebuilder_csrf';

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const target = `${name}=`;
  for (const piece of document.cookie.split(';')) {
    const trimmed = piece.trim();
    if (trimmed.startsWith(target)) {
      return decodeURIComponent(trimmed.slice(target.length));
    }
  }
  return null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isFormData = init.body instanceof FormData;
  const method = (init.method ?? 'GET').toUpperCase();
  const csrfHeaders: Record<string, string> = {};
  if (UNSAFE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE);
    if (token) csrfHeaders['X-CSRF-Token'] = token;
  }
  const response = await fetch(`${BASE}${path}`, {
    credentials: 'same-origin',
    headers: {
      ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
      Accept: 'application/json',
      ...csrfHeaders,
      ...(init.headers || {}),
    },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Request failed (${response.status}): ${text}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const createPage = (data: PageWritePayload & { title: string; slug: string }) =>
  request<PageDetail>('/pages', { method: 'POST', body: JSON.stringify(data) });

export const savePage = (id: number, data: PageWritePayload) =>
  request<PageDetail>(`/pages/${id}`, { method: 'PUT', body: JSON.stringify(data) });

export const deletePage = (id: number) => request<void>(`/pages/${id}`, { method: 'DELETE' });

function noteBody(note?: string | null): BodyInit | undefined {
  return note ? JSON.stringify({ note }) : undefined;
}

export const publishPage = (id: number, note?: string | null) =>
  request<PageRead>(`/pages/${id}/publish`, {
    method: 'POST',
    body: noteBody(note),
  });

export const unpublishPage = (id: number, note?: string | null) =>
  request<PageRead>(`/pages/${id}/unpublish`, {
    method: 'POST',
    body: noteBody(note),
  });

export const submitPage = (id: number, note?: string | null) =>
  request<PageRead>(`/pages/${id}/submit`, {
    method: 'POST',
    body: noteBody(note),
  });

export const approvePage = (id: number, note?: string | null) =>
  request<PageRead>(`/pages/${id}/approve`, {
    method: 'POST',
    body: noteBody(note),
  });

export const rejectPage = (id: number, note: string) =>
  request<PageRead>(`/pages/${id}/reject`, {
    method: 'POST',
    body: JSON.stringify({ note }),
  });

export const listPendingPages = () => request<{ items: PageRead[] }>('/pages/pending');

export const schedulePage = (id: number, body: ScheduleRequest) =>
  request<PageRead>(`/pages/${id}/schedule`, {
    method: 'POST',
    body: JSON.stringify(body),
  });

/**
 * Drive a rejection prompt → reject API round-trip. Returns the
 * updated page on success, or a string describing why the call was
 * skipped (cancelled / empty note / API error).
 *
 * Shared by the editor and the pending-review queue so both surfaces
 * stay in sync on prompt copy + empty-note handling.
 */
export async function promptAndReject(id: number): Promise<PageRead | { skipped: string }> {
  const note = window.prompt('Reason for rejection (shown to the editor):');
  if (note === null) return { skipped: 'cancelled' };
  const trimmed = note.trim();
  if (!trimmed) return { skipped: 'A rejection note is required.' };
  try {
    return await rejectPage(id, trimmed);
  } catch (e) {
    return { skipped: e instanceof Error ? e.message : 'Reject failed' };
  }
}

export const listRevisions = (id: number) =>
  request<{ items: PageRevisionRead[] }>(`/pages/${id}/revisions`);

export const getLayout = () => request<LayoutDetail>('/layout');

export const saveLayout = (body: LayoutUpdate) =>
  request<LayoutDetail>('/layout', {
    method: 'PUT',
    body: JSON.stringify(body),
  });

export const listLayoutRevisions = () =>
  request<{ items: LayoutRevisionRead[] }>('/layout/revisions');

export const restoreLayoutRevision = (revisionId: number) =>
  request<LayoutDetail>(`/layout/revisions/${revisionId}/restore`, {
    method: 'POST',
  });

export const restoreRevision = (pageId: number, revisionId: number) =>
  request<PageDetail>(`/pages/${pageId}/revisions/${revisionId}/restore`, {
    method: 'POST',
  });

export interface BlockChange {
  id: string;
  type?: string;
  fields: string[];
  type_before?: string;
}

export interface MetadataChange {
  before: unknown;
  after: unknown;
}

export interface RevisionDiff {
  before_id: number;
  after_id: number;
  metadata: Record<string, MetadataChange>;
  blocks: {
    added: BlockChange[];
    removed: BlockChange[];
    changed: BlockChange[];
  };
}

export const diffRevisions = (pageId: number, beforeId: number, afterId: number) =>
  request<RevisionDiff>(`/pages/${pageId}/revisions/${beforeId}/diff/${afterId}`);

function buildMediaQuery(params: MediaListQuery | undefined): string {
  if (!params) return '';
  const qs = new URLSearchParams();
  if (params.search !== undefined && params.search !== '') qs.set('search', params.search);
  if (params.content_type) qs.set('content_type', params.content_type);
  // Explicitly preserve `folder=""` — that's how the API expresses the
  // "Unfiled" bucket. URLSearchParams keeps empty values as `key=`.
  if (params.folder !== undefined) qs.set('folder', params.folder);
  if (params.min_size_bytes !== undefined) qs.set('min_size_bytes', String(params.min_size_bytes));
  if (params.max_size_bytes !== undefined) qs.set('max_size_bytes', String(params.max_size_bytes));
  if (params.cursor !== undefined) qs.set('cursor', String(params.cursor));
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return q ? `?${q}` : '';
}

export const listMedia = (params?: MediaListQuery) =>
  request<MediaListResponse>(`/uploads${buildMediaQuery(params)}`);

export interface UploadMediaOptions {
  folder?: string | null;
  onProgress?: (loaded: number, total: number) => void;
  signal?: AbortSignal;
}

export const uploadMedia = (
  file: File,
  options: UploadMediaOptions = {},
): Promise<MediaAssetRead> => {
  const { folder, onProgress, signal } = options;
  const body = new FormData();
  body.append('file', file);
  if (folder !== undefined && folder !== null && folder !== '') {
    body.append('folder', folder);
  }
  // XHR (not fetch) is used here purely for the upload-progress event;
  // fetch streams uploads in some browsers but exposes no progress
  // callback. Everything else (CSRF header, cookies, error shape)
  // mirrors the shared `request` helper above.
  if (!onProgress) {
    return request<MediaAssetRead>('/uploads', { method: 'POST', body, signal });
  }
  return new Promise<MediaAssetRead>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE}/uploads`);
    xhr.withCredentials = true;
    xhr.responseType = 'text';
    const token = readCookie(CSRF_COOKIE);
    if (token) xhr.setRequestHeader('X-CSRF-Token', token);
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded, e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as MediaAssetRead);
        } catch (err) {
          reject(err);
        }
      } else {
        reject(new Error(`Request failed (${xhr.status}): ${xhr.responseText}`));
      }
    };
    xhr.onerror = () => reject(new Error('Network error during upload'));
    xhr.onabort = () => reject(new DOMException('Aborted', 'AbortError'));
    if (signal) {
      if (signal.aborted) {
        xhr.abort();
      } else {
        signal.addEventListener('abort', () => xhr.abort(), { once: true });
      }
    }
    xhr.send(body);
  });
};

export const deleteMedia = (id: number) => request<void>(`/uploads/${id}`, { method: 'DELETE' });

export const DEFAULT_IMAGE_SIZES = '(max-width: 768px) 100vw, 768px';

export function buildSrcset(asset: MediaAssetRead): string {
  return Object.values(asset.variants)
    .slice()
    .sort((a, b) => a.width - b.width)
    .map((v) => `${v.url} ${v.width}w`)
    .join(', ');
}

// Cache of MediaAssetRead objects emitted by the MediaPicker, keyed by
// asset URL. The Image block's `resolveData` reads from this so the
// auto-fill round-trip doesn't have to refetch the full list that the
// picker just loaded. Falls back to a fresh `listMedia()` for URLs not
// in the cache (manual entry, page reload, etc.).
const pickedAssetCache = new Map<string, MediaAssetRead>();

export function rememberPickedAsset(asset: MediaAssetRead): void {
  pickedAssetCache.set(asset.url, asset);
}

export async function lookupAsset(url: string): Promise<MediaAssetRead | undefined> {
  const cached = pickedAssetCache.get(url);
  if (cached) return cached;
  const { items } = await listMedia();
  for (const item of items) pickedAssetCache.set(item.url, item);
  return pickedAssetCache.get(url);
}
