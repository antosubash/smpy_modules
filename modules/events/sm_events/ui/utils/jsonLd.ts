/** JSON for a `<script type="application/ld+json">` that cannot close its element.
 *
 *  `<`, `>` and `&` and the two JavaScript line separators are written as `\uXXXX`, which
 *  parses back to the same document. The server's `safe_json_ld` does the same. The separators
 *  are built from their code points so no editor or formatter can turn them into raw characters. */
const LINE_SEPARATOR = String.fromCharCode(0x2028);
const PARAGRAPH_SEPARATOR = String.fromCharCode(0x2029);

const ESCAPES: Record<string, string> = {
  '<': '\\u003c',
  '>': '\\u003e',
  '&': '\\u0026',
  [LINE_SEPARATOR]: '\\u2028',
  [PARAGRAPH_SEPARATOR]: '\\u2029',
};
const DANGEROUS = new RegExp(`[<>&${LINE_SEPARATOR}${PARAGRAPH_SEPARATOR}]`, 'g');

export function safeJsonLd(doc: unknown): string {
  return JSON.stringify(doc).replace(DANGEROUS, (char) => ESCAPES[char] ?? char);
}
