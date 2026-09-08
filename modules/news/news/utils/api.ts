/** Client for the news read API. */

import { BASE, read, write } from './http';
import { keys, type Translate } from './i18n';
import type {
  ArticleDetail,
  ArticleListResponse,
  ArticleRead,
  ArticleTranslationPayload,
  CategoryListResponse,
  RevisionRead,
} from './types';

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
  /** Only articles carrying this tag, by slug or by name. */
  tag?: string;
  /** The trash instead of the list. Needs `news.edit`; anyone else gets
   *  nothing, because a trashed article is by definition not published. */
  trashed?: boolean;
  /** Only articles in this language. A feed block on a German page passes
   *  `de`; the admin list leaves it unset and shows every language. */
  locale?: string;
  /** One article and its counterparts in other languages — what the editor's
   *  language switcher lists. */
  translation_group?: string;
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
  if (params.tag) query.set('tag', params.tag);
  if (params.trashed) query.set('trashed', 'true');
  if (params.locale) query.set('locale', params.locale);
  if (params.translation_group) query.set('translation_group', params.translation_group);
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

/** Set or clear when an article goes live and comes down.
 *
 * Its own call rather than part of `updateArticle`, because the route is behind
 * `news.publish` while that one is behind `news.edit` — see `ScheduleCard`.
 */
export const scheduleArticle = (
  id: number,
  data: { publish_at?: string | null; unpublish_at?: string | null },
) => write<ArticleRead>(`/articles/${id}/schedule`, 'POST', data);

export const updateArticle = (
  id: number,
  data: {
    title?: string;
    slug?: string;
    category?: string;
    published_at?: string | null;
    pinned?: boolean;
    show_in_feed?: boolean;
    author?: string;
    meta_description?: string;
    og_image?: string;
    canonical_url?: string;
    index_in_search?: boolean;
  },
) => write<ArticleRead>(`/articles/${id}`, 'PUT', data);

/** Delete the article outright — body, tags and all. Requires `news.publish`,
 *  the same pair `purgeArticle` needs: nothing here comes back. An author who
 *  may write but not publish keeps `trashArticle` instead.
 *
 * This was `detachArticle`, which removed news' metadata and left the document
 * standing in pagebuilder. There is no second document now, so the word had
 * nothing left to mean.
 */
export const deleteArticle = (id: number) => write<null>(`/articles/${id}`, 'DELETE');

/** Create an article, in one request.
 *
 * This used to be `createArticleWithPage`, and before that two calls from the
 * browser — a POST to pagebuilder's page API, then one back to news — which
 * meant knowing another module's cookie name and priming it with a throwaway
 * GET, and which stranded an empty articleless page whenever the second call
 * failed. One table means one insert.
 *
 * An omitted `slug` is derived from the title, server-side, and given the first
 * free variant. One the author typed is used verbatim, and a collision is a 409
 * rather than a silent rename.
 */
export const createArticle = (data: {
  title: string;
  slug?: string;
  /** Language to write in, and fixed once the article exists. Omitted means
   *  the site's default. */
  locale?: string;
  category?: string;
  published_at?: string | null;
  author?: string;
}) => write<ArticleRead>('/articles', 'POST', data);

/** Start this article's counterpart in another language.
 *
 * A sibling article sharing a `translation_group`, not a second view of this
 * one: its own slug, its own body, its own workflow state. Category, byline
 * and date are copied across, because they are facts about the story rather
 * than about the language it is told in.
 *
 * This used to translate the pagebuilder *page* the body lived in and then
 * attach a sidecar row to it — two writes across a module boundary, either of
 * which could land without the other. The article owns its body now, so one
 * request to news creates the whole thing.
 */
export const translateArticle = (articleId: number, data: ArticleTranslationPayload) =>
  write<ArticleRead>(`/articles/${articleId}/translations`, 'POST', data);

/** Everything the editor screens need, in one request. */
export const getArticleDetail = (id: number, signal?: AbortSignal) =>
  read<ArticleDetail>(`/articles/${id}/detail`, signal);

/** Autosave the block document into the draft.
 *
 * Its own route, deliberately: it fires on a timer rather than on a person
 * pressing something, so it must not be able to reach the slug or the status.
 */
export const saveArticleBody = (id: number, draft_data: Record<string, unknown>) =>
  write<ArticleDetail>(`/articles/${id}/body`, 'PUT', { draft_data });

export const listArticleRevisions = (id: number, signal?: AbortSignal) =>
  read<RevisionRead[]>(`/articles/${id}/revisions`, signal);

export const restoreArticleRevision = (id: number, revisionId: number) =>
  write<ArticleDetail>(`/articles/${id}/revisions/${revisionId}/restore`, 'POST', {});

/** Snapshot the draft and serve it. Requires `news.publish`. */
export const publishArticle = (id: number) =>
  write<ArticleRead>(`/articles/${id}/publish`, 'POST', {});

/** Take it off the public site, keeping the draft. Requires `news.publish`. */
export const unpublishArticle = (id: number) =>
  write<ArticleRead>(`/articles/${id}/unpublish`, 'POST', {});

/** Hand a draft to a reviewer. `news.edit` alone — it is what an author does
 *  when they cannot publish. */
export const submitArticle = (id: number) =>
  write<ArticleRead>(`/articles/${id}/submit`, 'POST', {});

/** Approve a submission — which also publishes it. One action, because a
 *  reviewer who has to approve and then publish separately eventually forgets
 *  the second half. Requires `news.publish`. */
export const approveArticle = (id: number) =>
  write<ArticleRead>(`/articles/${id}/approve`, 'POST', {});

/** Send a submission back, with a reason the author sees on the canvas. */
export const rejectArticle = (id: number, note: string) =>
  write<ArticleRead>(`/articles/${id}/reject`, 'POST', { note });

/** Move to the trash. Answers 204: there is no visible article to return. */
export const trashArticle = (id: number) => write<null>(`/articles/${id}/trash`, 'POST', {});

/** Remove for good, with its redirects. Requires `news.publish`. */
export const purgeArticle = (id: number) =>
  write<null>(`/articles/${id}/purge`, 'DELETE', undefined);

export const restoreArticle = (id: number) =>
  write<ArticleRead>(`/articles/${id}/restore`, 'POST', {});

/** "2d ago", "in 15d", "today" — the list's relative time.
 *
 * Rendered from the date part only, in UTC, for the same reason
 * `formatArticleDate` is: `published_at` is a display date stored at midnight
 * UTC, so reading it in the viewer's own timezone shifts it a day for everyone
 * west of UTC.
 */
export function relativeDay(iso: string | null, t: Translate, now = new Date()): string {
  if (!iso) return '';
  const then = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(then.getTime())) return '';
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const days = Math.round((then.getTime() - today) / 86_400_000);
  if (days === 0) return t(keys.news.dates.today);
  if (days > 0) return t(keys.news.dates.in_days, { days });
  return t(keys.news.dates.days_ago, { days: -days });
}

export type {
  ArticleCounts,
  ArticleDetail,
  ArticleListResponse,
  ArticleRead,
  ArticleStatus,
  ArticleTranslationPayload,
  CategoryCount,
  CategoryListResponse,
  RevisionRead,
} from './types';
