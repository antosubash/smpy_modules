import { Head } from '@inertiajs/react';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';

import { type ArticleRead, formatArticleDate } from '../utils/api';

/** The archive's front page, and the same screen narrowed to one category or
 *  tag.
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
  feed_url: string;
  site_name?: string | null;
}

function pageHref(basePath: string, page: number): string {
  return page <= 1 ? basePath : `${basePath}?page=${page}`;
}

export default function PublicIndex({
  heading,
  description,
  items,
  page,
  pages,
  total,
  base_path,
  feed_url,
}: Props) {
  return (
    <div>
      {/* A public page has no admin layout, so without this the configured
          brand colour and favicon would stop at the sign-in wall. */}
      <BrandingHead />
      <Head title={heading} />

      <div className="mx-auto max-w-2xl px-4 py-12">
        <header className="mb-10">
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{heading}</h1>
          {description && <p className="mt-2 text-muted-foreground">{description}</p>}
        </header>

        {items.length === 0 ? (
          // An archive with nothing in it says so. A blank page is
          // indistinguishable from one that failed to load.
          <p className="text-muted-foreground">Nothing published here yet.</p>
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
              <a href={pageHref(base_path, page - 1)} className="underline underline-offset-2">
                ← Newer
              </a>
            ) : (
              <span />
            )}
            <span className="text-muted-foreground">
              Page {page} of {pages} · {total} articles
            </span>
            {page < pages ? (
              <a href={pageHref(base_path, page + 1)} className="underline underline-offset-2">
                Older →
              </a>
            ) : (
              <span />
            )}
          </nav>
        )}

        <p className="mt-10 text-sm text-muted-foreground">
          <a href={feed_url} className="underline underline-offset-2">
            Subscribe by RSS
          </a>
        </p>
      </div>
    </div>
  );
}
