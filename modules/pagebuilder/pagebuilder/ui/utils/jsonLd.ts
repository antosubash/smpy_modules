/** Serialise a JSON-LD document for an inline `<script type="application/ld+json">`.
 *
 * `JSON.stringify` leaves `<` alone, so a value such as
 * `"</script><script>…"` would close the element early, and `<!--` would open
 * the HTML parser's script-data escape state. Escaping every `<` as `\u003c`
 * covers both, plus any case variant, and is still valid JSON: a consumer that
 * parses the block gets the original string back. (An earlier `<\!--` escape
 * was not valid JSON — `\!` is not an escape — so strict parsers rejected the
 * whole block.)
 */
export function safeJsonLd(doc: Record<string, unknown>): string {
  return JSON.stringify(doc).replace(/</g, '\\u003c');
}
