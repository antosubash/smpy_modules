/**
 * Returns the ARIA props that mark an image as decorative when alt is empty,
 * or the empty object when alt is descriptive. Callers must still write
 * `alt={imageAlt}` explicitly — biome's `useAltText` lint rule can't see
 * spread attributes, and keeping `alt` at the call-site makes the intent
 * visible to readers too.
 */
export function decorativeAriaProps(
  alt: string | undefined,
): { 'aria-hidden': 'true'; role: 'presentation' } | Record<string, never> {
  if (!alt || alt.trim() === '') {
    return { 'aria-hidden': 'true', role: 'presentation' };
  }
  return {};
}
