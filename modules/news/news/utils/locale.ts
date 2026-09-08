/** Turning a locale tag into something a person can read.
 *
 * A copy of pagebuilder's helper rather than an import of it: news' frontend
 * borrows one thing from that module — the `article-cards-render` widget the
 * feed block reuses — and everything else it needs from the neighbour comes
 * through the server. Four lines is a smaller price than a second reason for
 * the two bundles to be coupled.
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
