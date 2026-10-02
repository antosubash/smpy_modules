/** Slug derivation for the page editor and the new-page dialog.
 *
 * Unlike an article's, a page's slug is *not* minted by the server — the API
 * only validates the one the browser sends. That makes this function the rule
 * rather than a preview of it, which is exactly why it has to agree with the
 * only implementation that has a database behind it: `news/slugify.py`. It
 * used to differ, and the symptom was an editor typing one headline into two
 * screens and being shown two different URLs.
 *
 * The shared cases live in `tests/fixtures/slug_cases.json`; the Python, this
 * file and `news/news/utils/slugify.ts` each have a test that reads them, so a
 * change to any one of the three fails somewhere.
 */

/** The bound on the `slug` column, and on `PageCreate.slug`. */
const MAX_SLUG_LEN = 200;

/** Anything the decomposition did not reduce to ASCII. Written as a Unicode
 *  property escape rather than a `\x00-\x7F` range, which reads as a control
 *  character class and is a lint error. */
const NON_ASCII = /[^\p{ASCII}]/gu;
const SEPARATORS = /[^a-z0-9]+/g;
const TRIM = /^-+|-+$/g;

/**
 * `"Field notes"` -> `"field-notes"`.
 *
 * Accents fold to their base letter (`"Étude"` -> `"etude"`) rather than being
 * dropped, so two visually distinct titles do not collapse onto one slug.
 *
 * Everything non-ASCII that *survives* the decomposition is dropped rather than
 * turned into a separator, because that is what `encode('ascii', 'ignore')`
 * does in the Python. It is not a flattering rule — `"Straße Festival"` becomes
 * `strae-festival` — but it is the rule, and a second opinion about it held
 * only in the browser is how the two screens started disagreeing.
 *
 * The trim runs again after truncating: the cut can land mid-separator, and a
 * slug ending in a hyphen is a URL nobody typed.
 *
 * Returns `""` when nothing survives the fold — punctuation, or a script that
 * does not transliterate. Callers substitute their own fallback; inventing one
 * here would be a third thing to keep in step.
 */
export function slugify(value: string): string {
  const folded = value
    .normalize('NFKD')
    // Combining marks left behind by the decomposition, and anything else that
    // did not decompose to ASCII.
    .replace(NON_ASCII, '')
    .toLowerCase();
  return folded.replace(SEPARATORS, '-').replace(TRIM, '').slice(0, MAX_SLUG_LEN).replace(TRIM, '');
}
