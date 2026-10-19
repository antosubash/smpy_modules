/** Turn a rejected upload into a sentence in the console's language. */

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

/** The rejection for a non-2xx upload response. */
export const uploadRejected = (status: number) =>
  new UploadError(uploadErrorMessage(status), status);

/** The rejection for an upload that never got a response. */
export const uploadNetworkError = () =>
  new UploadError(translate(keys.pagebuilder.errors.upload_network));
