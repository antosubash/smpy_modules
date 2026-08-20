import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * The article editor — everything about an article except its body.
 *
 * Each field here is a rule about what the *feed* does, so the assertions run
 * through the listing rather than reading the form back: a checkbox that saves
 * but changes nothing has not done its job.
 */

async function makeArticle(
  page: Page,
  { publish = true, prefix = 'editor' }: { publish?: boolean; prefix?: string } = {},
) {
  const headers = await csrfHeader(page);
  const slug = uniqueSlug(prefix);
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title: `Editor ${slug}`,
      slug,
      draft_data: { root: { props: { title: slug, width: 'full' } }, content: [], zones: {} },
    },
  });
  const { id: pageId } = (await created.json()) as { id: number };
  if (publish) {
    await page.request.post(`/api/pagebuilder/pages/${pageId}/publish`, { headers, data: {} });
  }
  const attached = await page.request.post('/api/news/articles', {
    headers,
    data: { page_id: pageId, category: '', published_at: null },
  });
  const article = (await attached.json()) as { id: number };
  return { articleId: article.id, pageId, slug };
}

test.describe('Article editor', () => {
  test('is where the list Edit button goes', async ({ page }) => {
    await login(page);
    const { articleId, slug } = await makeArticle(page);

    await page.goto('/news/');
    await page
      .locator(`[data-testid="article-row"][data-slug="${slug}"]`)
      .getByRole('link', { name: /^edit$/i })
      .click();

    await expect(page).toHaveURL(new RegExp(`/news/articles/${articleId}/edit$`));
    await expect(page.getByRole('heading', { name: `Editor ${slug}`, level: 1 })).toBeVisible();
  });

  test('saves the byline, the date and the feed flags in one go', async ({ page }) => {
    await login(page);
    const { articleId, slug } = await makeArticle(page);

    await page.goto(`/news/articles/${articleId}/edit`);
    await page.getByLabel('Author').fill('J. Okonkwo');
    await page.getByLabel('Publish date').fill('2026-03-12');
    await page.getByLabel('Pin to top of /news').check();
    await page.getByLabel('Show in feed blocks').uncheck();
    await page.getByRole('button', { name: /^save$/i }).click();

    await expect(page.getByText('Saved', { exact: true })).toBeVisible();

    const listed = await page.request.get(`/api/news/articles?q=${slug}`);
    const body = (await listed.json()) as {
      items: { author: string; pinned: boolean; show_in_feed: boolean }[];
    };
    expect(body.items[0].author).toBe('J. Okonkwo');
    expect(body.items[0].pinned).toBe(true);
    expect(body.items[0].show_in_feed).toBe(false);
  });

  test('hiding an article keeps it in the admin list but out of the feed', async ({ page }) => {
    await login(page);
    const { articleId, slug } = await makeArticle(page);

    await page.goto(`/news/articles/${articleId}/edit`);
    await page.getByLabel('Show in feed blocks').uncheck();
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();

    // Out of the feed…
    const feed = await page.request.get(`/api/news/articles?in_feed=true&q=${slug}`);
    expect(((await feed.json()) as { total: number }).total).toBe(0);

    // …but still on the screen that can put it back.
    await page.goto('/news/');
    await expect(page.locator(`[data-testid="article-row"][data-slug="${slug}"]`)).toBeVisible();
  });

  test('tags are chips that add and remove', async ({ page }) => {
    await login(page);
    const { articleId } = await makeArticle(page);

    await page.goto(`/news/articles/${articleId}/edit`);
    const field = page.getByLabel('Add a tag');
    await field.fill('canopy');
    await field.press('Enter');
    await field.fill('urban');
    await field.press('Enter');
    await expect(page.locator('[data-testid="article-tag"]')).toHaveCount(2);

    await page.getByRole('button', { name: 'Remove tag canopy' }).click();
    await expect(page.locator('[data-testid="article-tag"]')).toHaveCount(1);

    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();

    const tags = await (await page.request.get(`/api/news/articles/${articleId}/tags`)).json();
    expect(tags).toEqual(['urban']);
  });

  test('a draft publishes from the editor header', async ({ page }) => {
    await login(page);
    const { articleId, slug } = await makeArticle(page, { publish: false });

    await page.goto(`/news/articles/${articleId}/edit`);
    await expect(page.getByText(/Draft/)).toBeVisible();
    await page.getByRole('button', { name: /publish now/i }).click();

    // Preview is a link to the public URL, not a button — it opens the live
    // article rather than doing anything to it.
    await expect(page.getByRole('link', { name: /^preview$/i })).toBeVisible();
    const listed = await page.request.get(`/api/news/articles?q=${slug}`);
    const body = (await listed.json()) as { items: { page_status: string }[] };
    expect(body.items[0].page_status).toBe('published');
  });

  test('pinning lifts the article above newer ones in the feed order', async ({ page }) => {
    await login(page);
    // Their own slug prefix, so the feed reads below can be scoped to exactly
    // these two. Unscoped, the assertion is "the pinned one leads the whole
    // feed", which only holds while no other spec has left a pinned article
    // with a later date behind it.
    const prefix = uniqueSlug('pinning');
    const older = await makeArticle(page, { prefix });
    const newer = await makeArticle(page, { prefix });
    const feed = `/api/news/articles?in_feed=true&limit=100&q=${prefix}`;

    // Give them dates so the order is unambiguous.
    await page.goto(`/news/articles/${older.articleId}/edit`);
    await page.getByLabel('Publish date').fill('2026-01-01');
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();

    await page.goto(`/news/articles/${newer.articleId}/edit`);
    await page.getByLabel('Publish date').fill('2026-06-01');
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();

    // Unpinned, the newer one leads.
    const before = await page.request.get(feed);
    const beforeSlugs = ((await before.json()) as { items: { slug: string }[] }).items.map(
      (i) => i.slug,
    );
    // Exact, not indexOf-vs-indexOf: with only one slug missing that
    // comparison reads -1 < n and passes for the wrong reason.
    expect(beforeSlugs).toEqual([newer.slug, older.slug]);

    // Pin the older one and it goes first — without its date changing.
    await page.goto(`/news/articles/${older.articleId}/edit`);
    await page.getByLabel('Pin to top of /news').check();
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();

    const after = await page.request.get(feed);
    const items = (
      (await after.json()) as {
        items: { slug: string; published_at: string }[];
      }
    ).items;
    expect(items[0].slug).toBe(older.slug);
    expect(items[0].published_at).toContain('2026-01-01');
  });
});
