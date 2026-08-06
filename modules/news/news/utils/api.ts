/** Client for the news read API. */

import type { PageStatus } from '@simple-module-py/pagebuilder/pagebuilder/utils/types';

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
  page_status: PageStatus;
  url: string;
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
}

const BASE = '/api/news';

export async function listArticles(params: {
  limit?: number;
  offset?: number;
  category?: string;
  signal?: AbortSignal;
}): Promise<ArticleListResponse> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.offset !== undefined) query.set('offset', String(params.offset));
  if (params.category) query.set('category', params.category);
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
const PAGEBUILDER_CSRF_COOKIE = 'pagebuilder_csrf';
/** A pagebuilder *view* route, deliberately not one of its API routes.
 *
 *  Only the view router carries the dependency that mints the CSRF token into
 *  the session; the API router merely validates one. Its cookie middleware can
 *  therefore only mirror a token that a view request already created, so
 *  priming against `/api/pagebuilder/...` returns 200 and sets nothing.
 */
const PAGEBUILDER_CSRF_PRIMER = '/pagebuilder/';

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

/** Read pagebuilder's CSRF cookie, priming it first if this session has never
 *  touched a pagebuilder route.
 *
 *  Its middleware only mirrors the token on requests under pagebuilder's own
 *  admin prefixes, so arriving at News straight from the sidebar leaves the
 *  cookie unset — and the page-creating POST below is CSRF-protected. Without
 *  this, "New article" 403s for anyone who has not already visited Pages this
 *  session, which is the common path rather than the rare one.
 */
async function pagebuilderCsrfToken(): Promise<string | null> {
  const existing = readCookie(PAGEBUILDER_CSRF_COOKIE);
  if (existing) return existing;
  await fetch(PAGEBUILDER_CSRF_PRIMER, {
    credentials: 'same-origin',
    headers: { Accept: 'text/html' },
  });
  return readCookie(PAGEBUILDER_CSRF_COOKIE);
}

/** Create the page an article's body lives in, through pagebuilder's API. */
export async function createArticlePage(title: string, slug: string): Promise<number> {
  const token = await pagebuilderCsrfToken();
  const response = await fetch('/api/pagebuilder/pages', {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(token ? { 'X-CSRF-Token': token } : {}),
    },
    body: JSON.stringify({
      title,
      slug,
      draft_data: { root: { props: { title, width: 'full' } }, content: [], zones: {} },
    }),
  });
  if (!response.ok) throw await errorFrom(response);
  const { id } = (await response.json()) as { id: number };
  return id;
}
