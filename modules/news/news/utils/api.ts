/** Client for the news read API. */

/** Workflow state of the page behind an article.
 *
 * News' own type, mirroring `contracts.schemas.ArticleStatus`. It used to be
 * imported from pagebuilder, which made a news component's type-check depend
 * on another package's file layout to name three strings news is perfectly
 * able to name itself.
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
  published_at: string | null;
  /** Workflow state of the page behind the article. Always `published` for
   *  anyone without `news.edit` — drafts are filtered out server-side. */
  page_status: ArticleStatus;
  url: string;
  /** Where an author edits the body. Served rather than assembled here, so
   *  this module holds no opinion about how another routes its editor. */
  edit_url: string;
}

export interface ArticleListResponse {
  items: ArticleRead[];
  total: number;
}

export interface CategoryCount {
  category: string;
  count: number;
}

export interface CategoryListResponse {
  items: CategoryCount[];
  /** How many articles carry no category at all. Its own field rather than a
   *  blank-named item, which would be indistinguishable from "All". */
  uncategorised: number;
}

const BASE = '/api/news';

/** Ask for the articles with no category at all.
 *
 * A blank string cannot mean this — the listing reads it as "no category
 * filter" — so the two states need distinct spellings on the wire. Matches
 * `constants.UNCATEGORISED`.
 */
export const UNCATEGORISED = '__none__';

export async function listArticles(params: {
  limit?: number;
  offset?: number;
  category?: string;
  /** Sort undated (work-in-progress) articles first — the admin list's view.
   *  Public feeds keep the default, which pushes undated to the end. */
  undated_first?: boolean;
  signal?: AbortSignal;
}): Promise<ArticleListResponse> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.offset !== undefined) query.set('offset', String(params.offset));
  if (params.category) query.set('category', params.category);
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

const CSRF_COOKIE = 'news_csrf';

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/** Turn a failed response into something worth showing a person.
 *
 * The body is only useful when it is our own JSON `detail`. An HTML error page
 * — which is what an auth or CSRF failure returns — would otherwise be thrown
 * verbatim and rendered as a wall of markup, leaking the whole Inertia payload
 * into the DOM.
 */
async function errorFrom(response: Response): Promise<Error> {
  const text = await response.text();
  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail;
    if (typeof detail === 'string') return new Error(detail);
    if (detail) return new Error(JSON.stringify(detail));
  } catch {
    // Not JSON — fall through to the status line rather than echo markup.
  }
  return new Error(`Request failed (${response.status} ${response.statusText})`.trim());
}

async function write<T>(path: string, method: string, body?: unknown): Promise<T | null> {
  const token = readCookie(CSRF_COOKIE);
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(token ? { 'X-CSRF-Token': token } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw await errorFrom(response);
  return response.status === 204 ? null : ((await response.json()) as T);
}

export const attachArticle = (data: {
  page_id: number;
  category?: string;
  published_at?: string | null;
}) => write<ArticleRead>('/articles', 'POST', data);

export const updateArticle = (
  id: number,
  data: { category?: string; published_at?: string | null },
) => write<ArticleRead>(`/articles/${id}`, 'PUT', data);

export const detachArticle = (id: number) => write<null>(`/articles/${id}`, 'DELETE');

/** Create an article and the page its body lives in, in one request.
 *
 *  This was two calls made from here — one to pagebuilder's page API, one back
 *  to news — and both of its problems were caused by that split. The first
 *  call was CSRF-protected by *another module's* cookie, which is unset for
 *  anyone who has not visited Pages this session, so the documented primary
 *  flow 403'd on a fresh login until a throwaway priming request was added.
 *  And the two calls committed separately, so any failure of the second left
 *  an empty, articleless page behind that nothing would ever clean up.
 *
 *  Server-side both writes share one transaction, and the request carries
 *  news' own token like every other write here.
 */
export const createArticleWithPage = (data: {
  title: string;
  category?: string;
  published_at?: string | null;
}) => write<ArticleRead>('/articles/with-page', 'POST', data);
