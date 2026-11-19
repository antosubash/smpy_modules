import { keys, useT } from '../utils/i18n';
import { ownLanguageName } from '../utils/language';
import type { Alternate } from './types';

/** The event's other languages, from its `alternates` (`x-default` is a hint for crawlers, not
 *  a language). Nothing renders for a single-language event. */
export function LanguageSwitch({
  alternates,
  locale,
}: {
  alternates: Alternate[];
  locale: string;
}) {
  const { t } = useT();
  const languages = alternates.filter((a) => a.locale !== 'x-default');
  if (languages.length < 2) return null;
  return (
    <nav aria-label={t(keys.events.public.language.label)} className="flex gap-3 text-sm">
      {languages.map((a) => (
        <a
          key={a.locale}
          href={a.url}
          hrefLang={a.locale}
          lang={a.locale}
          aria-current={a.locale === locale ? 'true' : undefined}
          className={a.locale === locale ? 'font-semibold' : 'underline'}
        >
          {ownLanguageName(a.locale)}
        </a>
      ))}
    </nav>
  );
}
