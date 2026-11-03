/** Sanitisers for the `NewsFeed` block's props, applied where they are used.
 *
 * Applied at render rather than only in the editor: pages saved before these
 * existed hold whatever the editor let through (`limit: 4.5`), and the API is
 * deliberately strict, so a bad value must be fixed on the way out.
 */

import { isSafeHref } from '@simple-module-py/pagebuilder/pagebuilder/utils/markdown-links';

export const FEED_LIMIT_MIN = 1;
export const FEED_LIMIT_MAX = 12;
export const FEED_LIMIT_DEFAULT = 4;

/** A whole number inside the block's own bounds (the API itself allows 1..100). */
export function clampFeedLimit(value: unknown): number {
  // `Number('')` is 0, which would clamp a cleared field to 1 rather than
  // fall back to the default like any other non-number.
  const n = typeof value === 'string' && value.trim() ? Number(value) : value;
  if (typeof n !== 'number' || !Number.isFinite(n)) return FEED_LIMIT_DEFAULT;
  return Math.min(FEED_LIMIT_MAX, Math.max(FEED_LIMIT_MIN, Math.trunc(n)));
}

/** `href` if it is safe to write into `<a href>`, otherwise `''` (no link).
 *
 * The scheme and control-character rules are the pagebuilder's `isSafeHref`
 * (relative references and http(s)/mailto/tel pass; `javascript:`, `data:`, …
 * do not). On top of that, protocol-relative `//host` (or `/\host`, `\host`,
 * which browsers read the same way) is dropped: it is scheme-less, so
 * `isSafeHref` lets it through, but it is an off-site link.
 */
export function safeHref(href: unknown): string {
  if (typeof href !== 'string') return '';
  const value = href.trim();
  if (!value) return '';
  if (value.startsWith('//') || value.startsWith('/\\') || value.startsWith('\\')) return '';
  return isSafeHref(value) ? value : '';
}
