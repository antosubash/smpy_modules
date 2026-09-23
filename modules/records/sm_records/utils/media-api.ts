/**
 * The browser half of the `media` field picker: a small client for the host's
 * media library API, wherever `sm_records.media` found it at startup.
 *
 * Deliberately not `utils/api.ts`: that client is `/api/records/*` and knows
 * this module's error bodies. This one talks to *another module's* API —
 * `file_storage` on a stock host — directly, with the session cookie, and that
 * module's own permissions decide what the caller may list, upload or read.
 * Records never proxies a byte of it. What the two share is the connection
 * handling in `api-net.ts`: an expired session is the same redirect, a
 * dropped connection the same `ApiError`, wherever the request was going.
 *
 * **The stored value is the file's id** (`file_storage`'s UUID), never a URL:
 * the download URL is derived from `file_url_template` at render time, so a
 * library moved behind a new prefix does not strand every stored value. A
 * value saved before the picker existed may still be a plain `https://` URL,
 * and stays valid — it renders as a link (`isUrlValue`).
 */

import { ApiError, handleUnauthorized, messageFor, offlineError, parseBody } from './api-net';
import type { ApiErrorBody } from './types';

/** The `media_api` view prop — `sm_records.media.MediaApi.props()`. */
export type MediaApi = {
  prefix: string;
  list_path: string;
  upload_path: string;
  /** `{id}` is replaced with the file's id. */
  file_url_template: string;
  meta_url_template: string;
  /** The list route's filename-search parameter, when it declares one.
   *  `file_storage` declares none, so the picker filters the loaded page. */
  search_param: string | null;
};

/** The slice of `file_storage`'s `StoredFileOut` the picker shows. */
export type MediaFile = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string | null;
};

export type MediaPage = { items: MediaFile[]; total: number; page: number; perPage: number };

/** Files per picker page — a multiple of 2, 3 and 4, so no grid row of the
 *  dialog is left half-filled at any breakpoint. */
export const MEDIA_PAGE_SIZE = 24;

const ID_PLACEHOLDER = '{id}';

export function fillId(template: string, id: string): string {
  return template.split(ID_PLACEHOLDER).join(encodeURIComponent(id));
}

export function fileUrl(api: MediaApi, id: string): string {
  return fillId(api.file_url_template, id);
}

/** A value saved before the picker existed: a full URL typed into the text
 *  box. Rendered as a link, never looked up as an id. */
export function isUrlValue(value: string): boolean {
  return /^https?:\/\//i.test(value.trim());
}

export function isImage(file: Pick<MediaFile, 'content_type'>): boolean {
  return file.content_type.toLowerCase().startsWith('image/');
}

function toMediaFile(raw: Record<string, unknown>): MediaFile {
  return {
    id: String(raw.id ?? ''),
    filename: String(raw.filename ?? raw.id ?? ''),
    content_type: String(raw.content_type ?? 'application/octet-stream'),
    size_bytes: typeof raw.size_bytes === 'number' ? raw.size_bytes : 0,
    created_at: typeof raw.created_at === 'string' ? raw.created_at : null,
  };
}

/** `file_storage` answers a refusal with `detail: {code, message}` rather
 *  than this module's `detail: "…"`; its `message` is already translated
 *  server-side, so it is the one to show. */
function errorFor(status: number, statusText: string, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | null)?.detail;
  const nested =
    detail && typeof detail === 'object' && 'message' in detail
      ? String((detail as { message: unknown }).message)
      : null;
  const normalised = (nested ? { detail: nested } : body) as ApiErrorBody | null;
  if (status === 401) handleUnauthorized();
  return new ApiError(status, normalised, messageFor(status, statusText, normalised));
}

async function getJson(url: string, signal?: AbortSignal): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(url, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw offlineError();
  }
  return response;
}

export async function listMediaFiles(
  api: MediaApi,
  options: { page: number; query?: string },
  signal?: AbortSignal,
): Promise<MediaPage> {
  const params = new URLSearchParams({
    page: String(options.page),
    per_page: String(MEDIA_PAGE_SIZE),
  });
  const query = (options.query ?? '').trim();
  if (api.search_param && query) params.set(api.search_param, query);
  const response = await getJson(`${api.list_path}?${params.toString()}`, signal);
  if (!response.ok) {
    throw errorFor(response.status, response.statusText, await parseBody(response));
  }
  const body = (await response.json()) as {
    items?: Record<string, unknown>[];
    total?: number;
    page?: number;
    per_page?: number;
  };
  const items = (body.items ?? []).map(toMediaFile);
  for (const file of items) rememberMediaFile(api, file);
  return {
    items,
    total: typeof body.total === 'number' ? body.total : items.length,
    page: body.page ?? options.page,
    perPage: body.per_page ?? MEDIA_PAGE_SIZE,
  };
}

/** One file's metadata, or `null` when the library does not have it — a
 *  `404` (deleted since it was picked) and a `422` (a stored value that is not
 *  an id at all) are the same answer to the person looking at the field. */
async function fetchMediaFile(
  api: MediaApi,
  id: string,
  signal?: AbortSignal,
): Promise<MediaFile | null> {
  const response = await getJson(fillId(api.meta_url_template, id), signal);
  if (response.status === 404 || response.status === 422) return null;
  if (!response.ok) {
    throw errorFor(response.status, response.statusText, await parseBody(response));
  }
  return toMediaFile((await response.json()) as Record<string, unknown>);
}

// ---- Metadata cache -------------------------------------------------------
//
// A list page of 25 records with an image column asks for up to 25 files,
// and the editor asks again for the one it opens. One promise per id, shared,
// for the life of the page: a file's metadata never changes under its id.
// Only failures are dropped, so a retry after a transient error re-fetches.

const cache = new Map<string, Promise<MediaFile | null>>();

function cacheKey(api: MediaApi, id: string): string {
  return `${api.meta_url_template}\u0000${id}`;
}

export function rememberMediaFile(api: MediaApi, file: MediaFile): void {
  cache.set(cacheKey(api, file.id), Promise.resolve(file));
}

export function getMediaFile(api: MediaApi, id: string): Promise<MediaFile | null> {
  const key = cacheKey(api, id);
  const hit = cache.get(key);
  if (hit) return hit;
  const pending = fetchMediaFile(api, id).catch((error: unknown) => {
    cache.delete(key);
    throw error;
  });
  cache.set(key, pending);
  return pending;
}

/** For tests: every test starts from an empty cache. */
export function clearMediaCache(): void {
  cache.clear();
}

// ---- Upload -----------------------------------------------------------------

export type UploadHandle = { promise: Promise<MediaFile>; abort: () => void };

/**
 * `POST {upload_path}` as multipart, through `XMLHttpRequest` rather than
 * `fetch` for the one thing `fetch` still cannot do: report upload progress.
 * `onProgress` gets 0–100. The failure paths end in the same `ApiError`s the
 * `fetch` clients raise, so a 401 redirects and a dropped connection says
 * nothing was lost, exactly as they do everywhere else in the module.
 */
export function uploadMediaFile(
  api: MediaApi,
  file: File,
  onProgress: (percent: number) => void,
): UploadHandle {
  const xhr = new XMLHttpRequest();
  const promise = new Promise<MediaFile>((resolve, reject) => {
    xhr.open('POST', api.upload_path);
    xhr.withCredentials = true;
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.onerror = () => reject(offlineError());
    xhr.onabort = () => reject(new DOMException('Upload aborted', 'AbortError'));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        body = null;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(errorFor(xhr.status, xhr.statusText, body));
        return;
      }
      const uploaded = toMediaFile((body ?? {}) as Record<string, unknown>);
      rememberMediaFile(api, uploaded);
      onProgress(100);
      resolve(uploaded);
    };
    const form = new FormData();
    form.append('file', file, file.name);
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}

// ---- Display ---------------------------------------------------------------

const UNITS = ['byte', 'kilobyte', 'megabyte', 'gigabyte'] as const;

/** `1.5 MB` in the viewer's locale — `Intl` supplies the unit words, so
 *  there is nothing here to translate. */
export function formatBytes(bytes: number): string {
  let value = Math.max(0, bytes);
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return new Intl.NumberFormat(undefined, {
    style: 'unit',
    unit: UNITS[unit],
    unitDisplay: 'short',
    maximumFractionDigits: unit === 0 ? 0 : 1,
  }).format(value);
}
