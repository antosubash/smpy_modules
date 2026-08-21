/** Slug derivation for the new-article dialog's URL preview.
 *
 * A sibling of `news/slugify.py`, and deliberately not an import from
 * pagebuilder: the rule has to stay stable forever, because a slug that shifts
 * under an existing article silently breaks every link to it already in the
 * wild. It is also only a *preview* — the server derives the real slug from
 * the title when the field is left alone, so the two agreeing is what stops the
 * dialog from showing a URL the article does not get.
 */

/** Pagebuilder's bound on the `slug` column. */
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
 * dropped, so two visually distinct titles do not collapse onto one slug. The
 * trim runs again after truncating: the cut can land mid-separator, and a
 * trailing hyphen fails the pattern the page API validates against.
 *
 * Everything non-ASCII that survives the decomposition is *dropped*, not turned
 * into a separator, because that is what `news/slugify.py` does — it folds with
 * NFKD and then encodes to ASCII, ignoring the rest. Turning them into
 * separators instead made the two disagree on every letter NFKD leaves whole:
 * `"Straße Festival"` previewed as `stra-e-festival` while the server created
 * `strae-festival`, so the dialog showed a URL the article did not get.
 *
 * Returns `""` when nothing survives the fold — punctuation, or a script that
 * does not transliterate. The caller shows the field as empty and the server
 * substitutes its own fallback, which is better than inventing one here that
 * the two implementations would have to keep agreeing on.
 */
export function slugify(value: string): string {
  const folded = value
    .normalize('NFKD')
    // Combining marks left behind by the decomposition, and anything else that
    // did not decompose to ASCII — `encode('ascii', 'ignore')` in the Python.
    .replace(NON_ASCII, '')
    .toLowerCase();
  return folded.replace(SEPARATORS, '-').replace(TRIM, '').slice(0, MAX_SLUG_LEN).replace(TRIM, '');
}
