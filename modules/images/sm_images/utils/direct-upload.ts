/**
 * Direct upload: `POST /collections/{id}/uploads`, one `PUT` per part to the
 * URLs it returns, then `POST /uploads/{id}/complete`.
 *
 * The part URLs are presigned storage URLs (`direct: true`) or, on a backend
 * that cannot presign, this app's relay route. A presigned `PUT` goes straight
 * to storage with no extra headers - a custom header would break its signature
 * and CORS preflight - and its `ETag` response header is what `complete`
 * claims. A relay `PUT` goes through `send` (session cookie and CSRF token) and
 * answers `{etag}`.
 */

import { ApiError, failedUpload, send, uploadImage } from './api';
import { messageFor, offlineError, parseBody } from './api-net';
import type { UploadResult } from './types';

const BASE = '/api/images';

export type Started = {
  upload_id: string;
  part_size: number;
  part_urls: string[];
  direct: boolean;
};

export type Part = { no: number; etag: string };

async function putPresigned(url: string, chunk: Blob): Promise<string> {
  let response: Response;
  try {
    response = await fetch(url, { method: 'PUT', body: chunk });
  } catch {
    throw offlineError();
  }
  if (!response.ok) {
    const body = await parseBody(response);
    throw new ApiError(response.status, body, messageFor(response.status, body));
  }
  const etag = response.headers.get('ETag');
  if (!etag) throw new ApiError(response.status, null, messageFor(502, null));
  return etag;
}

export async function putPart(started: Started, no: number, chunk: Blob): Promise<Part> {
  const url = started.part_urls[no - 1];
  if (started.direct) return { no, etag: await putPresigned(url, chunk) };
  const done = await send<{ etag: string }>(url, { method: 'PUT', body: chunk });
  return { no, etag: done.etag };
}

/** Send every part of *file*, in order; the etags `complete`/`extract` claim. */
export async function putParts(started: Started, file: Blob): Promise<Part[]> {
  const parts: Part[] = [];
  for (let no = 1; no <= started.part_urls.length; no++) {
    const from = (no - 1) * started.part_size;
    parts.push(await putPart(started, no, file.slice(from, from + started.part_size)));
  }
  return parts;
}

export async function uploadDirect(collectionId: string, file: File): Promise<UploadResult> {
  try {
    const started = await send<Started>(`${BASE}/collections/${collectionId}/uploads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: file.name,
        size: file.size,
        content_type: file.type || undefined,
      }),
    });
    const parts = await putParts(started, file);
    return await send<UploadResult>(`${BASE}/uploads/${started.upload_id}/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ parts, filename: file.name }),
    });
  } catch (error) {
    return failedUpload(file, error);
  }
}

/** The route for *file*: a file over the server's `direct_upload_threshold`
 *  must go direct (the multipart route refuses it with `use_direct_upload`);
 *  anything else is one multipart request. */
export function uploadFile(
  collectionId: string,
  file: File,
  directThreshold: number,
): Promise<UploadResult> {
  return file.size > directThreshold
    ? uploadDirect(collectionId, file)
    : uploadImage(collectionId, file);
}
