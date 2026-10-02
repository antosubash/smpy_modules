import { expect, type Page, test } from '@playwright/test';

import { seedArticle } from './article-helpers';
import { login } from './helpers';

/**
 * The redesigned article list — search, the two-state pipeline filters, and
 * publishing from the row menu.
 *
 * These assert on what the filters *select*, not on how the pills look: the
 * point of putting search and status in the query string is that the list can
 * be linked to and reloaded, and that only shows up across a navigation.
 */

async function makeArticle(
  page: Page,
  { category = '', publish = false }: { category?: string; publish?: boolean } = {},
) {
  const { articleId, slug } = await seedArticle(page, {
    prefix: 'list',
    titlePrefix: 'List',
    category,
    publish,
  });
  return { id: articleId, slug };
}

const card = (page: Page, slug: string) =>
  page.locator(`[data-testid="article-row"][data-slug="${slug}"]`);

test.describe('Article list', () => {
  test('search narrows the list and survives a reload', async ({ page }) => {
    await login(page);
    const wanted = await makeArticle(page, { publish: true });
    const other = await makeArticle(page, { publish: true });

    await page.goto('/admin/news/');
    await expect(card(page, wanted.slug)).toBeVisible();

    await page.getByLabel('Search headline or slug').fill(wanted.slug);
    await expect(card(page, other.slug)).toHaveCount(0);
    await expect(card(page, wanted.slug)).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`[?&]q=${wanted.slug}`));

    await page.reload();
    await expect(card(page, wanted.slug)).toBeVisible();
    await expect(card(page, other.slug)).toHaveCount(0);
  });

  test('the draft pill hides published articles', async ({ page }) => {
    await login(page);
    const draft = await makeArticle(page);
    const live = await makeArticle(page, { publish: true });

    await page.goto('/admin/news/');
    await expect(card(page, draft.slug)).toBeVisible();
    await expect(card(page, live.slug)).toBeVisible();

    await page.getByRole('button', { name: /^Draft \d+$/ }).click();
    await expect(card(page, live.slug)).toHaveCount(0);
    await expect(card(page, draft.slug)).toBeVisible();
    await expect(page).toHaveURL(/[?&]status=draft/);
  });

  test('an empty filter result offers a way back rather than "no articles yet"', async ({
    page,
  }) => {
    await login(page);
    await makeArticle(page, { publish: true });

    await page.goto('/admin/news/?q=zzz-nothing-matches-this-zzz');
    // The distinction the design draws: a filtered-to-nothing list is not the
    // same message as an empty archive.
    await expect(page.getByText(/No articles match/)).toBeVisible();
    // "Clear" drops every filter; "Search all statuses" only widens the
    // status, and is offered separately when one is active.
    await page.getByRole('button', { name: /^clear$/i }).click();

    await expect(page.getByText(/No articles match/)).toHaveCount(0);
    await expect(page).not.toHaveURL(/[?&]q=/);
  });

  test('a draft publishes from the row menu', async ({ page }) => {
    await login(page);
    const { slug } = await makeArticle(page);

    await page.goto('/admin/news/');
    const row = card(page, slug);
    await expect(row).toContainText('Draft');

    await row.getByRole('button', { name: /More actions/ }).click();
    await page.getByRole('menuitem', { name: /publish now/i }).click();

    await expect(row).toContainText('Published');
    // And it is genuinely live, not just relabelled.
    const listed = await page.request.get(`/api/news/articles?q=${slug}`);
    const body = (await listed.json()) as { items: { slug: string; status: string }[] };
    expect(body.items.find((i) => i.slug === slug)?.status).toBe('published');
  });

  test('status counts on the pills reflect the search, not the whole archive', async ({ page }) => {
    await login(page);
    const { slug } = await makeArticle(page, { publish: true });

    await page.goto(`/admin/news/?q=${slug}`);
    // One article matches the search, and it is published — so All and
    // Published both read 1 while Draft reads 0.
    await expect(page.getByRole('button', { name: /^All 1$/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /^Published 1$/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /^Draft 0$/ })).toBeVisible();
  });
});
