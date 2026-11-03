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

/** The language `Intl` formats in when `locale` gives none it can use. */
export const DEFAULT_LOCALE = 'en';

/** `locale` as a tag `Intl` accepts — never one that throws at render.
 *
 * Every date helper runs its `locale` through this (#189). The console's
 * `i18n.language` and a page's stored locale are strings nothing validated
 * for `Intl`: `''` and a POSIX-style `en_US` make `Intl.DateTimeFormat` throw
 * a `RangeError` mid-render, and `undefined` would quietly mean the browser's
 * language. An underscore becomes a hyphen; a blank or malformed tag becomes
 * {@link DEFAULT_LOCALE}.
 */
export function intlLocale(locale: string | null | undefined): string {
  const tag = (locale ?? '').trim().replace(/_/g, '-');
  if (!tag) return DEFAULT_LOCALE;
  try {
    return Intl.getCanonicalLocales(tag)[0] ?? DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
}
