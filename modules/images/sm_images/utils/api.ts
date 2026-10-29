/**
 * Typed `fetch` client for `/api/images/*`.
 *
 * Writes go through here, never through Inertia's `router.post()`: a JSON
 * response to an Inertia request is rejected. Navigation after a write still
 * uses Inertia's `router`. `ApiError` carries the parsed body next to the
 * status so a caller can branch on the `code` of an images error.
 */

import { ApiError, handleUnauthorized, messageFor, offlineError, parseBody } from './api-net';
import { csrfHeaders } from './csrf';
import type {
  Collection,
  CollectionFilter,
  GalleryFilter,
  ImageItem,
  Page,
  PipelineOverview,
  RestartScope,
  UploadResult,
  Visibility,
} from './types';

export { ApiError, OFFLINE_STATUS } from './api-net';

const BASE = '/api/images';

/** `fetch` with the plumbing every call shares. Exported for `api-shares.ts`,
 *  which talks to the framework's sharing API under another base. */
export async function send<T>(url: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      credentials: 'same-origin',
      ...init,
      headers: { Accept: 'application/json', ...csrfHeaders(init.method), ...(init.headers ?? {}) },
    });
  } catch {
    throw offlineError();
  }
  if (!response.ok) {
    const body = await parseBody(response);
    if (response.status === 401) handleUnauthorized();
    throw new ApiError(response.status, body, messageFor(response.status, body));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function json(method: string, body: unknown): RequestInit {
  return {
    method,
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  };
}

function query(params: Record<string, string | number | undefined | null>): string {
  const qs = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') qs.set(name, String(value));
  }
  const text = qs.toString();
  return text ? `?${text}` : '';
}

// ---- Collections ---------------------------------------------------------

export function listCollections(
  filter: CollectionFilter,
  cursor?: string | null,
  signal?: AbortSignal,
): Promise<Page<Collection>> {
  return send(`${BASE}/collections${query({ filter, cursor })}`, { signal });
}

export type CreateCollection = {
  name: string;
  description?: string;
  visibility: Visibility;
};

export function createCollection(body: CreateCollection): Promise<Collection> {
  return send(`${BASE}/collections`, json('POST', body));
}

export function setVisibility(id: string, visibility: Visibility): Promise<Collection> {
  return send(`${BASE}/collections/${id}/visibility`, json('PUT', { visibility }));
}

export function deleteCollection(id: string): Promise<void> {
  return send(`${BASE}/collections/${id}`, { method: 'DELETE' });
}

// ---- Images --------------------------------------------------------------

/** The list route's parameters for a gallery chip. */
export function filterParams(filter: GalleryFilter): Record<string, string> {
  switch (filter) {
    case 'located':
      return { has_location: 'true' };
    case 'unlocated':
      return { has_location: 'false' };
    case 'processing':
      return { step_status: 'pending' };
    case 'failed':
      return { step_status: 'failed' };
    default:
      return {};
  }
}

export function listImages(
  collectionId: string,
  filter: GalleryFilter,
  cursor?: string | null,
): Promise<Page<ImageItem>> {
  const qs = query({ ...filterParams(filter), cursor });
  return send(`${BASE}/collections/${collectionId}/images${qs}`);
}

export function deleteImage(id: string): Promise<void> {
  return send(`${BASE}/images/${id}`, { method: 'DELETE' });
}

/** One file per request: a single-file request answers with that file's own
 *  status and `code`, which is the sentence the person should read. A failure
 *  of one file is a result, not an exception, so the rest still go up. */
export async function uploadImage(collectionId: string, file: File): Promise<UploadResult> {
  const form = new FormData();
  form.append('files', file, file.name);
  try {
    const { results } = await send<{ results: UploadResult[] }>(
      `${BASE}/collections/${collectionId}/images`,
      { method: 'POST', body: form },
    );
    return results[0];
  } catch (error) {
    return failedUpload(file, error);
  }
}

/** An upload error as a result for that file. A 401 (or a non-API error) is not
 *  about the file, so it is rethrown for the caller to report once. */
export function failedUpload(file: File, error: unknown): UploadResult {
  if (error instanceof ApiError && error.status !== 401) {
    return {
      filename: file.name,
      status: 'error',
      id: null,
      code: error.body?.code ?? null,
      detail: error.message,
    };
  }
  throw error;
}

// ---- Pipeline ------------------------------------------------------------

export function getPipeline(collectionId: string): Promise<PipelineOverview> {
  return send(`${BASE}/collections/${collectionId}/pipeline`);
}

/** `steps` is `{id: {enabled, ...params}}`, the shape the server validates. */
export function savePipeline(
  collectionId: string,
  steps: Record<string, Record<string, unknown>>,
): Promise<PipelineOverview> {
  return send(`${BASE}/collections/${collectionId}/pipeline`, json('PUT', { steps }));
}

export function restartPipeline(collectionId: string, scope: RestartScope): Promise<unknown> {
  return send(`${BASE}/collections/${collectionId}/pipeline/restart`, json('POST', { scope }));
}
