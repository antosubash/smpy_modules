import { Head } from '@inertiajs/react';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';

import { ArchiveSearch } from '../components/ArchiveSearch';
import { type ArticleRead, formatArticleDate } from '../utils/api';
import { archiveUrl } from '../utils/archiveUrl';
import { keys, useT } from '../utils/i18n';

/** The archive's front page, and the same screen narrowed to one category,
 *  tag, byline or search.
 *
 * The reader's way in. Until this existed a visitor could only open an article
 * they already had a link to: the public router had one route, `/{slug}`, so
 * the archive had no front door and the only browsing surface — the `NewsFeed`
 * block — lived in pagebuilder's palette. A module that could be installed
 * alone could not be read alone.
 *
 * Deliberately plain. This is the one screen in the module a host is most
 * likely to want to replace with something on-brand, and the less opinion it
 * carries the less there is to unpick.
 */

interface Props {
  heading: string;
  description?: string | null;
  items: ArticleRead[];
  page: number;
  pages: number;
  total: number;
  /** Path this archive lives at, for building page links. */
  base_path: string;
  /** The search term this page was narrowed by, or ''. Server-trimmed, so what
   *  is echoed here is exactly what was searched for. */
  query?: string;
  /** Whether this archive was already narrowed before any search — a category,
   *  a tag or a byline. */
  narrowed?: boolean;
  feed_url: string;
  site_name?: string | null;
}

export default function PublicIndex({
  heading,
  description,
  items,
  page,
  pages,
  total,
  base_path,
  query = '',
  narrowed = false,
  feed_url,
}: Props) {
  const { t } = useT();
  const copy = keys.news.public;
  return (
    <div>
      {/* A public page has no admin layout, so without this the configured
          brand colour and favicon would stop at the sign-in wall. */}
      <BrandingHead />
      <Head title={query ? t(copy.title_with_query, { query, heading }) : heading}>
        {/* Results pages stay out of the index: the input space is unbounded,
            so one indexed `?q=` link invites a crawler to enumerate query
            strings forever, and every result page is a rearrangement of
            articles already indexed at their own addresses. `follow`, though —
            the links out of it are the real documents. The server writes the
            same tag into the head for the crawler that never runs this script;
            see `endpoints/public/_head.py`. */}
        {query && <meta name="robots" content="noindex,follow" />}
      </Head>

      <div className="mx-auto max-w-2xl px-4 py-12">
        <header className="mb-10">
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{heading}</h1>
          {description && <p className="mt-2 text-muted-foreground">{description}</p>}
        </header>

        <ArchiveSearch basePath={base_path} query={query} narrowed={narrowed} heading={heading} />

        {items.length === 0 ? (
          // An archive with nothing in it says so. A blank page is
          // indistinguishable from one that failed to load — and a search that
          // found nothing needs a way out as well as an explanation, or the
          // reader's only route back is the browser's Back button.
          <div className="text-muted-foreground">
            {query ? (
              <>
                {/* One entry per sentence rather than a translated fragment
                    around the emphasised term: which half of "in {heading}"
                    leads is the translator's call. */}
                <p>
                  {narrowed
                    ? t(copy.no_match_narrowed, { query, heading })
                    : t(copy.no_match, { query })}
                </p>
                <p className="mt-2">
                  <a href={base_path} className="underline underline-offset-2">
                    {narrowed ? t(copy.show_all_narrowed, { heading }) : t(copy.show_all)}
                  </a>
                </p>
              </>
            ) : (
              <p>{t(copy.empty)}</p>
            )}
          </div>
        ) : (
          <ul className="space-y-8">
            {items.map((article) => {
              const dated = formatArticleDate(article.published_at);
              return (
                <li key={article.id}>
                  <article>
                    {article.category && (
                      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-primary">
                        {article.category}
                      </p>
                    )}
                    <h2 className="text-xl font-semibold tracking-tight">
                      <a href={article.url} className="hover:underline">
                        {article.title}
                      </a>
                    </h2>
                    {dated && <p className="mt-1 text-sm text-muted-foreground">{dated}</p>}
                    {article.excerpt && (
                      <p className="mt-2 leading-relaxed text-muted-foreground">
                        {article.excerpt}
                      </p>
                    )}
                  </article>
                </li>
              );
            })}
          </ul>
        )}

        {pages > 1 && (
          // Real links, not buttons: this is the surface a crawler follows to
          // reach everything past the first page, and "load more" is not a link.
          <nav className="mt-12 flex items-center justify-between border-t pt-5 text-sm">
            {page > 1 ? (
              <a
                href={archiveUrl(base_path, page - 1, query)}
                className="underline underline-offset-2"
              >
                {t(copy.newer)}
              </a>
            ) : (
              <span />
            )}
            <span className="text-muted-foreground">
              {t(copy.pager, { page, pages, count: total })}
            </span>
            {page < pages ? (
              <a
                href={archiveUrl(base_path, page + 1, query)}
                className="underline underline-offset-2"
              >
                {t(copy.older)}
              </a>
            ) : (
              <span />
            )}
          </nav>
        )}

        <p className="mt-10 text-sm text-muted-foreground">
          <a href={feed_url} className="underline underline-offset-2">
            {t(copy.feed)}
          </a>
        </p>
      </div>
    </div>
  );
}
