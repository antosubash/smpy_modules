/** Client for the news read API. */

import { BASE, write } from './http';

/** Workflow state of the page behind an article.
 *
 * News' own union, deliberately, even though the values are pagebuilder's
 * `PageStatus` verbatim: this is what the news API sends, and typing it against
 * a neighbour's module made every consumer of this client depend on that
 * module's file layout to name a value news is perfectly able to name itself.
 * `test_integrations` fails if the two vocabularies ever drift.
 */
export type ArticleStatus = 'draft' | 'submitted_for_review' | 'published';

export interface ArticleRead {
  id: number;
  page_id: number;
  slug: string;
  title: string;
  excerpt: string;
  cover_image_url: string;
  category: string;
  tags: string[];
  /** Held at the top of /news and of every feed block. */
  pinned: boolean;
  /** Whether feed blocks may list it. Does not affect the admin list. */
  show_in_feed: boolean;
  author: string;
  published_at: string | null;
  /** Workflow state of the page behind the article. Always `published` for
   *  anyone without `news.edit` — drafts are filtered out server-side. */
  page_status: ArticleStatus;
  url: string;
  /** Where the body is edited. Sent by the server rather than assembled here,
   *  so this list holds no opinion about how pagebuilder routes its editor. */
  edit_url: string;
}

export interface ArticleCounts {
  all: number;
  draft: number;
  published: number;
  undated: number;
}

export interface ArticleListResponse {
  items: ArticleRead[];
  /** Matched the whole filter, status included — what the pager counts. */
  total: number;
  /** What each status pill would show. `undated` overlaps draft and
   *  published, so these deliberately do not sum to `all`. */
  counts: ArticleCounts;
}

export interface CategoryCount {
  category: string;
  count: number;
}

export interface CategoryListResponse {
  items: CategoryCount[];
}

export async function listArticles(params: {
  limit?: number;
  offset?: number;
  category?: string;
  /** Free-text filter over headline and slug. */
  q?: string;
  /** `draft`, `published` or `undated`. */
  status?: string;
  /** Only articles allowed in feed blocks — the feed block's own filter. */
  in_feed?: boolean;
  /** Sort undated (work-in-progress) articles first — the admin list's view.
   *  Public feeds keep the default, which pushes undated to the end. */
  undated_first?: boolean;
  signal?: AbortSignal;
}): Promise<ArticleListResponse> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.offset !== undefined) query.set('offset', String(params.offset));
  if (params.category) query.set('category', params.category);
  if (params.q) query.set('q', params.q);
  if (params.status) query.set('status', params.status);
  if (params.in_feed) query.set('in_feed', 'true');
  if (params.undated_first) query.set('undated_first', 'true');
  const response = await fetch(`${BASE}/articles?${query}`, {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
    signal: params.signal,
  });
  if (!response.ok) throw new Error(`News request failed (${response.status})`);
  return (await response.json()) as ArticleListResponse;
}

/** Existing category names with usage counts — feeds the admin list's
 *  suggestions so one category is not spelled three ways. */
export async function listCategories(signal?: AbortSignal): Promise<CategoryListResponse> {
  const response = await fetch(`${BASE}/categories`, {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
    signal,
  });
  if (!response.ok) throw new Error(`News request failed (${response.status})`);
  return (await response.json()) as CategoryListResponse;
}

/** `2026-01-01T00:00:00Z` -> `Jan 1, 2026`. Empty for an undated article.
 *
 * Only the date part is read, and it is rendered in UTC. `published_at` is a
 * display date stored as midnight UTC, so handing the full timestamp to
 * `toLocaleDateString` in the viewer's own timezone would show everyone west
 * of UTC the previous day.
 */
export function formatArticleDate(iso: string | null, locale?: string): string {
  if (!iso) return '';
  const date = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });
}

export const attachArticle = (data: {
  page_id: number;
  category?: string;
  published_at?: string | null;
}) => write<ArticleRead>('/articles', 'POST', data);

export const updateArticle = (
  id: number,
  data: {
    category?: string;
    published_at?: string | null;
    pinned?: boolean;
    show_in_feed?: boolean;
    author?: string;
  },
) => write<ArticleRead>(`/articles/${id}`, 'PUT', data);

export const detachArticle = (id: number) => write<null>(`/articles/${id}`, 'DELETE');

/** Create the page *and* attach the article, in one request.
 *
 * One call, under news' own CSRF token. This used to be two from here — a POST
 * to pagebuilder's page API, then one back to news — which meant knowing
 * another module's cookie name and priming it with a throwaway GET, and which
 * stranded an empty articleless page whenever the second call failed. The
 * server does both writes in one transaction now, so a failure leaves nothing
 * behind.
 *
 * An omitted `slug` is derived from the title, server-side, and given the first
 * free variant. One the author typed is used verbatim, and a collision is a 409
 * rather than a silent rename.
 */
export const createArticleWithPage = (data: {
  title: string;
  slug?: string;
  category?: string;
  published_at?: string | null;
  author?: string;
}) => write<ArticleRead>('/articles/with-page', 'POST', data);

/** Publish the page behind an article, from the list's row menu.
 *
 * Also news' own route: the body belongs to the page, but routing this through
 * pagebuilder's API from the browser was the last thing that made that
 * module's CSRF cookie news' business.
 */
export const publishArticle = (id: number) =>
  write<ArticleRead>(`/articles/${id}/publish`, 'POST', {});

/** "2d ago", "in 15d", "today" — the list's relative time.
 *
 * Rendered from the date part only, in UTC, for the same reason
 * `formatArticleDate` is: `published_at` is a display date stored at midnight
 * UTC, so reading it in the viewer's own timezone shifts it a day for everyone
 * west of UTC.
 */
export function relativeDay(iso: string | null, now = new Date()): string {
  if (!iso) return '';
  const then = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(then.getTime())) return '';
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const days = Math.round((then.getTime() - today) / 86_400_000);
  if (days === 0) return 'today';
  if (days > 0) return `in ${days}d`;
  return `${-days}d ago`;
}
