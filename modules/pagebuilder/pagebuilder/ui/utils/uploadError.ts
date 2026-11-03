/** Turn a rejected upload into a sentence in the console's language. */

import { isCsrfRefusalBody } from './csrf';
import { keys, translate } from './i18n';

/**
 * An upload failure whose `message` is already translated and safe to show.
 *
 * Callers that render an adapter's error (the image picker) check for this
 * class rather than trusting any `Error.message`, which may be browser or
 * server English.
 */
export class UploadError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = 'UploadError';
    this.status = status;
  }
}

/**
 * The server answers in English prose (`{"detail": "..."}`), so the status is
 * the stable signal: 413 too large, 415 wrong type, 422 invalid form fields.
 * The body is never shown — not even a 422's Pydantic `msg`, which is English
 * whatever language the console speaks.
 */
export function uploadErrorMessage(status: number): string {
  if (status === 413) return translate(keys.pagebuilder.errors.upload_too_large);
  if (status === 415) return translate(keys.pagebuilder.errors.upload_unsupported);
  if (status === 401 || status === 403) return translate(keys.pagebuilder.errors.upload_forbidden);
  if (status === 422) return translate(keys.pagebuilder.errors.upload_failed_invalid);
  return translate(keys.pagebuilder.errors.upload_failed, { status });
}

/** The machine-readable `detail.code` of a rejection, when it carries one.
 *  Only the code is read — the `detail.message` beside it is English. */
function rejectionCode(body: string): string | null {
  try {
    const detail = (JSON.parse(body) as { detail?: unknown }).detail;
    const code = (detail as { code?: unknown } | null)?.code;
    return typeof code === 'string' ? code : null;
  } catch {
    return null;
  }
}

/** The message for a non-2xx upload response. The status decides it, with
 *  two exceptions whose body is read. A stale CSRF token is a 403 that is not
 *  a missing permission (reloading the page fixes it). An image with too many
 *  pixels is a 413 that is not about the file's size in bytes — a small PNG
 *  can decode to gigabytes (#221) — so "too large to upload" would mislead. */
function rejectionMessage(status: number, body: string): string {
  if (isCsrfRefusalBody(status, body)) return translate(keys.pagebuilder.errors.csrf_failed);
  if (status === 413 && rejectionCode(body) === 'image_too_many_pixels') {
    return translate(keys.pagebuilder.errors.upload_too_many_pixels);
  }
  return uploadErrorMessage(status);
}

/** The rejection for a non-2xx upload response. */
export const uploadRejected = (status: number, body = '') =>
  new UploadError(rejectionMessage(status, body), status);

/** The rejection for an upload that never got a response. */
export const uploadNetworkError = () =>
  new UploadError(translate(keys.pagebuilder.errors.upload_network));
