/** Turning a locale tag into something a person can read.
 *
 * A copy of pagebuilder's/news' helper rather than an import of either:
 * modules do not import each other's frontend code (see `RecordTranslations`'s
 * own header for the fuller version of this rule), and four lines is a
 * smaller price than a second reason for the bundles to be coupled.
 */

/** The language's own name for itself, e.g. `de` → "Deutsch".
 *
 * Rendered in the language's own terms rather than the reader's: a translator
 * looking for Japanese looks for 日本語. Falls back to the tag, which is what
 * you want when `Intl` has never heard of it.
 */
export function localeLabel(locale: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: 'language' }).of(locale) ?? locale;
  } catch {
    return locale;
  }
}
