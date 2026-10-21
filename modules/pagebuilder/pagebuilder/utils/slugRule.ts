/** What the API accepts as a page slug, and what to tell an author who typed
 *  something else (#188).
 *
 * `SLUG_PATTERN` is `PageCreate.slug`'s `pattern` (contracts/schemas/_pages.py),
 * copied rather than fetched: the editor checks it on every keystroke, and the
 * server's 422 stays the authority — `validationMessage` below translates that
 * 422 when a slug reaches the server anyway.
 */

import { keys, translate } from './i18n';

export const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]*$/;

/** True for a slug the API would accept. Empty is not one. */
export function isValidSlug(slug: string): boolean {
  return SLUG_PATTERN.test(slug);
}

/** The sentence shown under a slug field the API would reject. */
export function slugInvalidMessage(): string {
  return translate(keys.pagebuilder.settings.slug_invalid);
}

/**
 * A readable message for one FastAPI 422 entry this module knows how to
 * explain, or null to fall back to pydantic's own `msg`.
 *
 * Pydantic's text for a pattern mismatch is `String should match pattern
 * '^[a-z0-9][a-z0-9-]*$'` — in English whatever the console speaks, and a
 * regex to the author. It is matched on `type` and `loc`, never on `msg`,
 * which is pydantic's wording and changes between its releases.
 */
export function validationMessage(entry: { loc?: unknown; type?: unknown }): string | null {
  const loc = Array.isArray(entry.loc) ? entry.loc : [];
  if (entry.type === 'string_pattern_mismatch' && loc[loc.length - 1] === 'slug') {
    return slugInvalidMessage();
  }
  return null;
}
