/** Turning a locale tag into something a person can read, and into a URL. */

/** The language's own name for itself, e.g. `de` → "Deutsch".
 *
 * A tag is what the database stores and what the URL carries, but it is not
 * what an editor scanning a list of languages wants to read. `Intl` already
 * knows every name the browser's locale data covers, so shipping a hardcoded
 * map would be a second, worse copy that goes stale as soon as a deployment
 * configures a language nobody anticipated.
 *
 * Rendered in the language's *own* terms rather than the reader's: a
 * translator looking for Japanese looks for 日本語. Falls back to the tag,
 * which is exactly right when `Intl` has never heard of it.
 */
export function localeLabel(locale: string): string {
  try {
    const names = new Intl.DisplayNames([locale], { type: 'language' });
    return names.of(locale) ?? locale;
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
 * for `Intl`: `''` and a POSIX-style `en_US` make `toLocaleString` throw a
 * `RangeError` mid-render, and `undefined` would quietly mean the browser's
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

/** The URL segment a language contributes — `''` for the site's default.
 *
 * Mirrors `pagebuilder.locales.path_prefix` on the server. Kept in step by
 * being three lines rather than by being shared: the alternative is another
 * round trip to learn something the page already knows. */
export function localePrefix(locale: string, defaultLocale: string): string {
  return locale === defaultLocale ? '' : `/${locale}`;
}

/** Where a page serves publicly, in one language. */
export function publicPath(
  prefix: string,
  slug: string,
  locale: string,
  defaultLocale: string,
): string {
  return `${localePrefix(locale, defaultLocale)}${prefix.replace(/\/$/, '')}/${slug}`;
}
