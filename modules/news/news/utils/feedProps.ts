/** Sanitisers for the `NewsFeed` block's props, applied where they are used.
 *
 * Applied at render rather than only in the editor: pages saved before these
 * existed hold whatever the editor let through (`limit: 4.5`), and the API is
 * deliberately strict, so a bad value must be fixed on the way out.
 */

export const FEED_LIMIT_MIN = 1;
export const FEED_LIMIT_MAX = 12;
export const FEED_LIMIT_DEFAULT = 4;

/** A whole number inside the block's own bounds (the API itself allows 1..100). */
export function clampFeedLimit(value: unknown): number {
  const n = typeof value === 'string' ? Number(value) : value;
  if (typeof n !== 'number' || !Number.isFinite(n)) return FEED_LIMIT_DEFAULT;
  return Math.min(FEED_LIMIT_MAX, Math.max(FEED_LIMIT_MIN, Math.trunc(n)));
}

/** `href` if it is safe to write into `<a href>`, otherwise `''` (no link).
 *
 * Allowed: relative references (`/x`, `./x`, `../x`, `x/y`, `?q=1`, `#a`) but
 * not protocol-relative `//host` (or `/\host`, `\host`, which browsers read
 * the same way), and absolute http(s)/mailto/tel. Every other scheme —
 * `javascript:`, `data:`, `vbscript:`, … — is dropped. React 19 happens to
 * neutralise `javascript:`, but that is a framework safeguard, not a policy.
 */
export function safeHref(href: unknown): string {
  if (typeof href !== 'string') return '';
  const value = href.trim();
  if (!value) return '';
  // Browsers strip tabs/newlines inside a URL, so `java\nscript:` is a scheme.
  // biome-ignore lint/suspicious/noControlCharactersInRegex: that is the point.
  if (/[\u0000-\u001f\u007f]/.test(value)) return '';
  if (value.startsWith('//') || value.startsWith('/\\') || value.startsWith('\\')) return '';
  // A scheme is a `:` before the first `/`, `?` or `#` (RFC 3986 §4.2), so
  // `x/y:z` and `?a=b:c` are relative while `javascript:` is not.
  if (!/^[^/?#]*:/.test(value)) return value;
  return /^(https?|mailto|tel):/i.test(value) ? value : '';
}
