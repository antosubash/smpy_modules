import type { ArticleDraft } from '../components/editor/ArticleInspector';
import type { ArticleRead } from './api';

/** Split a stored instant into the two controls the inspector shows.
 *
 * Read in UTC, because `published_at` is a display date stored at midnight UTC
 * — reading it in the viewer's own timezone shifts the date a day for everyone
 * west of UTC, which is the bug `formatArticleDate` already documents.
 */
function splitInstant(iso: string | null): { date: string; time: string } {
  if (!iso) return { date: '', time: '' };
  return { date: iso.slice(0, 10), time: iso.slice(11, 16) || '00:00' };
}

export function toDraft(article: ArticleRead): ArticleDraft {
  const { date, time } = splitInstant(article.published_at);
  return {
    title: article.title,
    slug: article.slug,
    category: article.category,
    tags: article.tags ?? [],
    date,
    time,
    author: article.author ?? '',
    pinned: article.pinned ?? false,
    showInFeed: article.show_in_feed ?? true,
  };
}
