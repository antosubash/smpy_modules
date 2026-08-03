/** Media library calls, upload progress, and srcset helpers. */

import { BASE, CSRF_COOKIE, readCookie, request } from './request';
import type {
  MediaAssetRead,
  MediaListQuery,
  MediaListResponse,
  UploadMediaOptions,
} from './types';

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
  if (params.offset !== undefined) qs.set('offset', String(params.offset));
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return q ? `?${q}` : '';
}

export const listMedia = (params?: MediaListQuery) =>
  request<MediaListResponse>(`/uploads${buildMediaQuery(params)}`);

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
  // mirrors the shared `request` helper.
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
