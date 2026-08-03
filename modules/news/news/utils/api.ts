/** Client for the news read API. */

export interface ArticleRead {
  id: number;
  page_id: number;
  slug: string;
  title: string;
  excerpt: string;
  cover_image_url: string;
  category: string;
  published_at: string | null;
  url: string;
}

export interface ArticleListResponse {
  items: ArticleRead[];
  total: number;
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

/** `2026-01-01T00:00:00` -> `Jan 1, 2026`. Empty for an undated article. */
export function formatArticleDate(iso: string | null, locale?: string): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' });
}

const CSRF_COOKIE = 'news_csrf';

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
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
  if (!response.ok) throw new Error(await response.text());
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

/** Create the page an article's body lives in, through pagebuilder's API. */
export async function createArticlePage(title: string, slug: string): Promise<number> {
  const token = readCookie('pagebuilder_csrf');
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
  if (!response.ok) throw new Error(await response.text());
  const { id } = (await response.json()) as { id: number };
  return id;
}

/** `Field campaign in Estonia` -> `field-campaign-in-estonia`. */
export function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 200);
}
