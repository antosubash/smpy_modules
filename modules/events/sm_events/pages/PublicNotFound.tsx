import { useDocumentLang } from '../ui/hooks/useDocumentLang';
import { PublicHead } from '../ui/public/PublicHead';
import type { PublicNotFoundProps } from '../ui/public/types';
import { ItemRow } from '../ui/public/UpcomingList';
import { keys, useT } from '../ui/utils/i18n';
import { PageLocale } from '../ui/utils/PageLocale';

/** The 404 when pagebuilder is not there to frame it: one message for every cause, a link to the
 *  index and the next few events. Nothing on it depends on what was asked for. */
function PublicNotFoundPage({ locale, index_url, suggestions }: PublicNotFoundProps) {
  const { t } = useT();
  const copy = keys.events.public.not_found;
  useDocumentLang(locale);
  return (
    <>
      <PublicHead
        head={{
          title: t(copy.title),
          description: null,
          canonical: null,
          image: null,
          robots: 'noindex,nofollow',
          feed_url: null,
        }}
        locale={locale}
      />
      <main className="mx-auto max-w-3xl space-y-4 p-4">
        <h1 className="text-2xl font-semibold">{t(copy.title)}</h1>
        <p>{t(copy.message)}</p>
        <p>
          <a href={index_url} className="underline">
            {t(copy.index)}
          </a>
        </p>
        {suggestions.length ? (
          <section aria-labelledby="coming-up">
            <h2 id="coming-up" className="font-semibold">
              {t(copy.suggestions)}
            </h2>
            <ul className="divide-y">
              {suggestions.map((item) => (
                <ItemRow key={item.key} item={item} locale={locale} />
              ))}
            </ul>
          </section>
        ) : null}
      </main>
    </>
  );
}

export default function PublicNotFound(props: PublicNotFoundProps) {
  return (
    <PageLocale locale={props.locale}>
      <PublicNotFoundPage {...props} />
    </PageLocale>
  );
}
