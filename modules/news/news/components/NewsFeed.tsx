import type { ComponentConfig } from '@puckeditor/core';
import {
  type ArticleCardItem,
  ArticleCardsGrid,
} from '@simple-module-py/pagebuilder/pagebuilder/components/widgets/article-cards-render';
import { useEffect, useState } from 'react';

import { useContentLocale } from '../hooks/useContentLocale';
import { type ArticleRead, formatArticleDate, listArticles } from '../utils/api';
import { keys } from '../utils/i18n';

export interface NewsFeedProps {
  title: string;
  category: string;
  limit: number;
  columns: '2' | '3' | '4';
  viewAllLabel: string;
  viewAllHref: string;
}

function toCard(article: ArticleRead): ArticleCardItem {
  return {
    imageUrl: article.cover_image_url,
    imageAlt: '',
    eyebrow: article.category,
    date: formatArticleDate(article.published_at),
    title: article.title,
    body: article.excerpt,
    // The article's own public URL, served by news. Sent by the server rather
    // than assembled here, so a card holds no opinion about the route.
    href: article.url,
  };
}

export function NewsFeedRender({
  title,
  category,
  limit,
  columns,
  viewAllLabel,
  viewAllHref,
}: NewsFeedProps) {
  const [items, setItems] = useState<ArticleCardItem[] | null>(null);
  // The page's language, not a field on the block: a feed set to one language
  // on a page written in another is a mistake nothing would catch, and an
  // English card in a German list is worse than no card.
  const locale = useContentLocale();

  useEffect(() => {
    const controller = new AbortController();
    // `in_feed` is the block's own filter: an article can be published and
    // linked to without belonging in the chronological feed.
    listArticles({ limit, category, locale, in_feed: true, signal: controller.signal })
      .then((response) => setItems(response.items.map(toCard)))
      // An empty feed and a failed fetch look the same to a visitor on
      // purpose: a broken API must not put an error box on a public page.
      .catch(() => setItems([]));
    return () => controller.abort();
  }, [limit, category, locale]);

  // Render nothing at all until the first response, and nothing when there
  // are no articles: a heading with an empty grid under it reads as a broken
  // section. An empty fragment rather than null because Puck's render must
  // return an Element.
  if (items === null || items.length === 0) return <></>;

  return (
    <ArticleCardsGrid
      title={title}
      viewAllLabel={viewAllLabel}
      viewAllHref={viewAllHref}
      columns={columns}
      items={items}
    />
  );
}

/**
 * The palette entry, whose labels are catalogue keys like every other block's.
 *
 * The resolver is the difference: an article-body block is localized by
 * `ArticleBody`, which is news' own screen, while this one lands in
 * *pagebuilder's* palette and is resolved by pagebuilder's `localizeConfig`
 * when `PageEditor` mounts Puck. That works because the host merges every
 * module's catalogue into one flat table and i18next is configured with
 * `keySeparator: false`, so `news.feed.…` is a whole key rather than a path
 * into a namespace pagebuilder would have to know about — see the floor on the
 * `pagebuilder` extra in `pyproject.toml`, which is what guarantees the
 * neighbour is new enough to resolve them.
 */
export const NewsFeedBlock: ComponentConfig<NewsFeedProps> = {
  label: keys.news.feed.label,
  fields: {
    title: { type: 'text', label: keys.news.feed.title },
    category: { type: 'text', label: keys.news.feed.category },
    limit: { type: 'number', label: keys.news.feed.limit, min: 1, max: 12 },
    columns: {
      type: 'select',
      label: keys.news.feed.columns,
      options: [
        { label: keys.news.feed.columns_2, value: '2' },
        { label: keys.news.feed.columns_3, value: '3' },
        { label: keys.news.feed.columns_4, value: '4' },
      ],
    },
    viewAllLabel: { type: 'text', label: keys.news.feed.view_all_label },
    viewAllHref: { type: 'text', label: keys.news.feed.view_all_href },
  },
  defaultProps: {
    title: 'Latest news',
    category: '',
    limit: 4,
    columns: '4',
    viewAllLabel: '',
    viewAllHref: '',
  },
  render: NewsFeedRender,
};
