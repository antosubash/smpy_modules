/**
 * Scheme and control-character checks for article body links and embed/media
 * sources (#364).
 *
 * Kept self-contained (not imported from `@simple-module-py/pagebuilder`) because
 * pagebuilder is an optional peer dependency of news, and article bodies must
 * still render safely on hosts that never installed it.
 */

// Browsers strip leading C0 controls and spaces from a URL, so
// "\x01javascript:…" has no scheme to the regex below but runs as one.
// biome-ignore lint/suspicious/noControlCharactersInRegex: matching them is the point
const CONTROL_CHAR = /[\u0000-\u001f\u007f]/;
const SCHEME_PREFIX = /^([a-zA-Z][a-zA-Z0-9+.-]*):/;

function hasAllowedScheme(url: string, schemes: readonly string[]): boolean {
  if (CONTROL_CHAR.test(url)) return false;
  const scheme = SCHEME_PREFIX.exec(url.trimStart());
  return !scheme || schemes.includes(scheme[1].toLowerCase());
}

function isProtocolRelative(value: string): boolean {
  return value.startsWith('//') || value.startsWith('/\\') || value.startsWith('\\');
}

/** Whether `href` may be written into `<a href>`. */
export function isSafeHref(href: string): boolean {
  return hasAllowedScheme(href, ['http', 'https', 'mailto', 'tel']);
}

/**
 * `href` if it is safe to write into `<a href>`, otherwise `''` (no link).
 *
 * Relative references and http(s)/mailto/tel pass; `javascript:`, `data:`,
 * control characters, and protocol-relative `//host` (or `/\host`, `\host`)
 * are dropped.
 */
export function safeHref(href: unknown): string {
  if (typeof href !== 'string') return '';
  const value = href.trim();
  if (!value || isProtocolRelative(value)) return '';
  return isSafeHref(value) ? value : '';
}

/**
 * An `Embed`, `Video` or `Audio` block's source, as it may load into the page:
 * http(s) or scheme-less site-relative path, otherwise `''`.
 *
 * Stricter than `safeHref`, since a frame or media element has no use for
 * `mailto:` or `tel:`.
 */
export function safeFrameSrc(src: unknown): string {
  if (typeof src !== 'string') return '';
  const value = src.trim();
  if (!value || isProtocolRelative(value)) return '';
  return hasAllowedScheme(value, ['http', 'https']) ? value : '';
}
