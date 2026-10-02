/**
 * The one block in this palette that reads the archive rather than its own
 * props.
 *
 * Every other block renders exactly what a writer typed into it. This one asks
 * the listing API what else is published, which is the point: a "read next"
 * hand-typed at publication is stale the moment the next article goes up, and
 * nobody goes back to a three-month-old story to refresh it.
 *
 * It renders its own list rather than reusing the card grid the `NewsFeed`
 * block draws with. That grid belongs to pagebuilder, and this has to work on a
 * host that never installed it — the same rule the rest of the palette follows.
 */

import type { ComponentConfig } from '@puckeditor/core';
import { useEffect, useState } from 'react';

import { type ArticleRead, formatArticleDate, listArticles } from '../../../utils/api';

export interface RelatedProps {
  title: string;
  category: string;
  limit: number;
}

/** How many the field will offer. More than a handful stops being "read next"
 *  and starts being a second front page at the foot of the article. */
const MAX = 6;

/**
 * The articles to actually list, out of what the archive returned.
 *
 * Pure, and exported, because it is the only real logic here and the rest is a
 * fetch: the effect that calls it cannot be reached by a static render, so
 * testing it through the component would test nothing.
 */
export function pickRelated(
  articles: ArticleRead[],
  currentSlug: string | undefined,
  limit: number,
): ArticleRead[] {
  return articles
    .filter((article) => article.slug !== currentSlug)
    .slice(0, Math.max(1, Math.min(limit, MAX)));
}

export function RelatedRender({
  title,
  category,
  limit,
  currentSlug,
}: RelatedProps & { currentSlug?: string }) {
  const [items, setItems] = useState<ArticleRead[] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    // One more than needed, because the article being read is very likely in
    // the response and dropping it would otherwise leave the list a row short.
    listArticles({
      limit: Math.min(limit, MAX) + 1,
      category,
      in_feed: true,
      signal: controller.signal,
    })
      .then((response) => setItems(pickRelated(response.items, currentSlug, limit)))
      // An empty list and a failed request look the same to a reader, on
      // purpose: a listing that is briefly down must not put an error box in
      // the middle of a published article.
      .catch(() => setItems([]));
    return () => controller.abort();
  }, [limit, category, currentSlug]);

  // Nothing until the first response, and nothing when the archive has nothing
  // else to offer — a heading over an empty list reads as broken.
  if (items === null || items.length === 0) return <></>;

  return (
    <section className="my-10 border-t pt-5">
      {title && <h2 className="mb-3 text-sm font-semibold tracking-tight">{title}</h2>}
      <ul className="space-y-2">
        {items.map((article) => {
          const dated = formatArticleDate(article.published_at);
          return (
            <li key={article.id}>
              <a href={article.url} className="underline underline-offset-2">
                {article.title}
              </a>
              {dated && <span className="ml-2 text-xs text-muted-foreground">{dated}</span>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export const RelatedBlock: ComponentConfig<RelatedProps> = {
  label: 'Read next',
  fields: {
    title: { type: 'text', label: 'Heading' },
    category: { type: 'text', label: 'Category filter (blank = any)' },
    limit: { type: 'number', label: 'How many', min: 1, max: MAX },
  },
  defaultProps: { title: 'Read next', category: '', limit: 3 },
  // `puck.metadata` is how the viewer tells a block which article it is inside
  // — see `PublicArticle`. On the canvas there is no current article, so the
  // filter matches nothing and the writer sees the list a reader would.
  render: ({ title, category, limit, puck }) => (
    <RelatedRender
      title={title}
      category={category}
      limit={limit}
      currentSlug={puck?.metadata?.currentSlug as string | undefined}
    />
  ),
};
