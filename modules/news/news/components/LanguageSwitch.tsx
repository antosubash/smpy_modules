import { keys, useT } from '../utils/i18n';

/** One entry of the article's `alternates` prop. */
export interface Alternate {
  locale: string;
  url: string;
}

/** A language's name in that language ("Deutsch"), or its code if the runtime
 *  does not know it. */
export function endonym(locale: string): string {
  try {
    const name = new Intl.DisplayNames([locale], { type: 'language' }).of(locale);
    if (name) return name.charAt(0).toLocaleUpperCase(locale) + name.slice(1);
  } catch {
    // Not a valid language tag — fall through to the code.
  }
  return locale;
}

/** The entries worth a link: not `x-default` (a crawler hint, not a language)
 *  and not the language already on screen. */
export function switchTargets(alternates: Alternate[] | undefined, current?: string): Alternate[] {
  return (alternates ?? []).filter(
    (entry) => entry.locale !== 'x-default' && entry.locale !== current,
  );
}

/** Links to this article in its other languages.
 *
 * The `hreflang` tags in the head are for crawlers; this is the same set for a
 * reader. Renders nothing for a monolingual article.
 */
export function LanguageSwitch({
  alternates,
  current,
}: {
  alternates: Alternate[] | undefined;
  current?: string;
}) {
  const { t } = useT();
  const others = switchTargets(alternates, current);
  if (others.length === 0) return null;
  return (
    <nav aria-label={t(keys.news.public_switch.label)} className="mt-4 text-sm">
      <ul className="flex flex-wrap gap-x-4 gap-y-1">
        {others.map((entry) => (
          <li key={entry.locale}>
            <a
              href={entry.url}
              hrefLang={entry.locale}
              lang={entry.locale}
              className="text-primary underline-offset-4 hover:underline"
            >
              {endonym(entry.locale)}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
