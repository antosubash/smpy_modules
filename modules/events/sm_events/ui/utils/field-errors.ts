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

/** `{ field: message }` for a 422, keyed by the full `loc` path (`names.de`,
 *  never just `names` for it); `{}` for anything else. The message comes from
 *  the first segment, so `names.de` and `names` read alike. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.status !== 422) return {};
  const out: Record<string, string> = {};
  for (const path of error.fields) {
    const [head] = path.split('.');
    if (!head) continue;
    out[path] = t(MESSAGES[head] ?? keys.events.errors.invalid_input);
  }
  return out;
}

export const requiredText = (): string => t(keys.events.errors.required);

/** The message under a form field; the input points at it with `aria-describedby`. */
export const fieldErrorId = (id: string): string => `${id}-error`;

/** The `aria-*` pair an input with a message needs. */
export const invalidProps = (id: string, message?: string) =>
  message ? { 'aria-invalid': true as const, 'aria-describedby': fieldErrorId(id) } : {};
