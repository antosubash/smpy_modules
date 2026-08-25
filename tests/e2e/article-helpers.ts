import type { Page } from '@playwright/test';

import { csrfHeader, uniqueSlug } from './helpers';

/**
 * Seed an article, for the specs that need one to look at.
 *
 * Shared because it used to be copied into nine spec files, and every copy did
 * the same three-step dance: POST a page to pagebuilder, publish that page,
 * then POST news metadata pointing at its id. An article is one row now, so the
 * dance collapses to one request — and putting it here means the next change to
 * the shape is one edit rather than nine.
 *
 * `publish` defaults to false because a newly created article is a draft, which
 * is what the admin list is mostly about. Specs that need a public URL to hit
 * ask for it.
 */
export async function seedArticle(
  page: Page,
  {
    prefix = 'e2e',
    title,
    titlePrefix,
    category = '',
    publishedAt = null,
    author = '',
    publish = false,
    body,
  }: {
    prefix?: string;
    title?: string;
    /** Names the article `"<titlePrefix> <slug>"`, which is how most specs
     *  locate a heading. Ignored when `title` is given outright. */
    titlePrefix?: string;
    category?: string;
    publishedAt?: string | null;
    author?: string;
    publish?: boolean;
    /** Block document. Omitted, the article opens on an empty canvas. */
    body?: Record<string, unknown>;
  } = {},
): Promise<{ articleId: number; slug: string; title: string; url: string }> {
  const headers = await csrfHeader(page);
  const slug = uniqueSlug(prefix);
  const resolvedTitle = title ?? (titlePrefix ? `${titlePrefix} ${slug}` : slug);

  const created = await page.request.post('/api/news/articles', {
    headers,
    // The slug is passed explicitly rather than derived from the title: these
    // specs locate rows by it, so it has to be the value they already hold.
    data: { title: resolvedTitle, slug, category, published_at: publishedAt, author },
  });
  const article = (await created.json()) as { id: number; url: string };

  if (body) {
    await page.request.put(`/api/news/articles/${article.id}/body`, {
      headers,
      data: { draft_data: body },
    });
  }
  if (publish) {
    await page.request.post(`/api/news/articles/${article.id}/publish`, {
      headers,
      data: {},
    });
  }
  return { articleId: article.id, slug, title: resolvedTitle, url: article.url };
}

/** A block document with one paragraph — enough for the viewer to render. */
export function paragraphBody(text: string): Record<string, unknown> {
  return {
    root: { props: { title: text } },
    content: [{ type: 'Paragraph', props: { text, lead: false } }],
    zones: {},
  };
}
