/** A 422 from request validation lists one entry per bad field (`loc`).
 *  Each becomes a localized message next to that field; a field with no
 *  message of its own falls back to the generic one. */
import { ApiError } from './api';
import { keys, translate as t } from './i18n';

const MESSAGES: Record<string, string> = {
  name: keys.events.errors.name_invalid,
  names: keys.events.errors.names_invalid,
  slug: keys.events.errors.slug_invalid,
  color: keys.events.errors.color_invalid,
  description: keys.events.errors.description_invalid,
  default_timezone: keys.events.errors.default_timezone_invalid,
};

/** `{ field: message }` for a 422, keyed by the first `loc` segment and, for a
 *  nested one (`names.de`), by the whole path as well; `{}` for anything else. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.status !== 422) return {};
  const out: Record<string, string> = {};
  for (const path of error.fields) {
    const [head] = path.split('.');
    if (!head) continue;
    const message = t(MESSAGES[head] ?? keys.events.errors.invalid_input);
    out[head] = message;
    if (path !== head) out[path] = message;
  }
  return out;
}

export const requiredText = (): string => t(keys.events.errors.required);
export const timezoneText = (): string => t(keys.events.errors.default_timezone_invalid);
