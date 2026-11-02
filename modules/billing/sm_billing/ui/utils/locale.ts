/** Normalising a locale tag before `Intl` sees it. */

/** The language `Intl` formats in when `locale` gives none it can use. */
export const DEFAULT_LOCALE = 'en';

/** `locale` as a tag `Intl` accepts — never one that throws at render.
 *
 * Every date and money helper runs its `locale` through this (#189). The
 * console's `i18n.language` is a string nothing validated for `Intl`: `''`
 * and a POSIX-style `en_US` make `Intl.DateTimeFormat` throw a `RangeError`
 * mid-render, and `undefined` would quietly mean the browser's language. An
 * underscore becomes a hyphen; a blank or malformed tag becomes
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
