/** Turn a rejected upload into a sentence in the console's language. */

import { keys, translate } from './i18n';
import { fromValidationErrors } from './request';

/**
 * The server answers in English prose (`{"detail": "..."}`), so the status is
 * the stable signal: 413 too large, 415 wrong type, 422 a list of Pydantic
 * errors. The body is only consulted for the 422 list; it is never shown raw.
 */
export function uploadErrorMessage(status: number, body: string): string {
  if (status === 413) return translate(keys.pagebuilder.errors.upload_too_large);
  if (status === 415) return translate(keys.pagebuilder.errors.upload_unsupported);
  if (status === 401 || status === 403) return translate(keys.pagebuilder.errors.upload_forbidden);
  if (status === 422) {
    try {
      const details = fromValidationErrors((JSON.parse(body) as { detail?: unknown }).detail);
      if (details) return translate(keys.pagebuilder.errors.upload_failed_invalid, { details });
    } catch {
      // Not JSON: fall through to the generic message.
    }
  }
  return translate(keys.pagebuilder.errors.upload_failed, { status });
}
