import { expect, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * The categories + tags screen.
 *
 * The cases worth a browser are the ones where the screen's promise spans more
 * than one row: a rename has to carry every article in the category, and a
 * delete has to move them rather than take them with it. Both are invisible
 * from the row you clicked, which is exactly why they are asserted here against
 * the article list rather than against the dialog that triggered them.
 */

const CATEGORIES_URL = '/news/categories';

/** Create a published page with an article attached, in `category`. */
async function makeArticle(page: import('@playwright/test').Page, category: string) {
  const headers = await csrfHeader(page);
  const slug = uniqueSlug('e2e-article');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title: slug,
      slug,
      draft_data: { root: { props: { title: slug, width: 'full' } }, content: [], zones: {} },
    },
  });
  expect(created.ok()).toBeTruthy();
  const { id } = (await created.json()) as { id: number };

  const newsCsrf = (await page.context().cookies()).find((c) => c.name === 'news_csrf')?.value;
  const attached = await page.request.post('/api/news/articles', {
    headers: newsCsrf ? { 'X-CSRF-Token': decodeURIComponent(newsCsrf) } : {},
    data: { page_id: id, category, published_at: null },
  });
  expect(attached.ok()).toBeTruthy();
  return { id, slug };
}

/** The row for a category.
 *
 * Matched on `data-category` rather than on rendered text: entering edit mode
 * moves the name into an input, and an input's value is not text content — a
 * `hasText` locator stops matching exactly when the test needs it most.
 */
function categoryRow(page: import('@playwright/test').Page, name: string) {
  return page.locator(`[data-testid="category-row"][data-category="${name}"]`).first();
}

test.describe('News categories', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    // Prime the news CSRF cookie: the taxonomy writes are protected, and the
    // cookie is only minted on a news view route.
    await page.goto(CATEGORIES_URL);
  });

  test('the screen lists the system category and cannot delete it', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Categories', level: 1 })).toBeVisible();

    const system = categoryRow(page, 'Uncategorised');
    await expect(system).toBeVisible();
    await expect(system).toContainText('cannot be deleted or renamed');
    await expect(system.getByRole('button', { name: /^delete$/i })).toHaveCount(0);
    await expect(system.getByRole('button', { name: /^rename$/i })).toHaveCount(0);
  });

  test('a new category appears with its public filter URL', async ({ page }) => {
    const name = `Research ${Date.now().toString(36)}`;

    await page.getByLabel('New category name').fill(name);
    await page.getByRole('button', { name: /^add$/i }).click();

    const row = categoryRow(page, name);
    await expect(row).toBeVisible();
    await expect(row).toContainText('/news?category=research-');
  });

  test('renaming a category carries its articles with it', async ({ page }) => {
    const original = `Field ${Date.now().toString(36)}`;
    const renamed = `${original} reports`;
    await makeArticle(page, original);
    await page.goto(CATEGORIES_URL);

    // Formalise the free-text category so it becomes renameable.
    await categoryRow(page, original).getByRole('button', { name: /add to list/i }).click();
    const row = categoryRow(page, original);
    await expect(row.getByRole('button', { name: /^rename$/i })).toBeVisible();
    await row.getByRole('button', { name: /^rename$/i }).click();
    await row.getByLabel('Category name').fill(renamed);
    await row.getByRole('button', { name: /^save$/i }).click();

    await expect(categoryRow(page, renamed)).toBeVisible();
    // The article moved with it — the old name no longer groups anything, so
    // it is gone from the list entirely rather than left behind at zero.
    await expect(categoryRow(page, renamed)).toContainText('1 article');

    const listed = await page.request.get(
      `/api/news/articles?category=${encodeURIComponent(renamed)}`,
    );
    expect(((await listed.json()) as { total: number }).total).toBe(1);
  });

  test('deleting a category moves its articles instead of deleting them', async ({ page }) => {
    const doomed = `Doomed ${Date.now().toString(36)}`;
    await makeArticle(page, doomed);
    await page.goto(CATEGORIES_URL);
    await categoryRow(page, doomed).getByRole('button', { name: /add to list/i }).click();

    const row = categoryRow(page, doomed);
    await row.getByRole('button', { name: /^delete$/i }).click();

    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();
    // The screen must say where the articles are going before it does it.
    await expect(dialog).toContainText('Uncategorised');
    await expect(dialog).toContainText('Nothing is deleted with the category');
    await dialog.getByRole('button', { name: /delete category/i }).click();
    await expect(dialog).toHaveCount(0);

    await expect(categoryRow(page, doomed)).toHaveCount(0);
    // The article survives, now uncategorised.
    const listed = await page.request.get(
      `/api/news/articles?category=${encodeURIComponent(doomed)}`,
    );
    expect(((await listed.json()) as { total: number }).total).toBe(0);
  });

  test('an empty category deletes without asking where anything goes', async ({ page }) => {
    const name = `Empty ${Date.now().toString(36)}`;
    await page.getByLabel('New category name').fill(name);
    await page.getByRole('button', { name: /^add$/i }).click();

    const row = categoryRow(page, name);
    await expect(row).toContainText('0 articles');
    await row.getByRole('button', { name: /^delete$/i }).click();

    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toContainText('nothing moves');
    await expect(dialog.getByLabel('Move its articles to')).toHaveCount(0);
    await dialog.getByRole('button', { name: /delete category/i }).click();

    await expect(categoryRow(page, name)).toHaveCount(0);
  });
});

test.describe('News tags', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto(CATEGORIES_URL);
  });

  test('a tag can be created and then merged into another', async ({ page }) => {
    const stamp = Date.now().toString(36);
    const keep = `canopy${stamp}`;
    const fold = `canopies${stamp}`;

    for (const name of [keep, fold]) {
      await page.getByLabel('Find or create a tag').fill(name);
      await page.getByRole('button', { name: /^create$/i }).click();
      await expect(page.getByRole('button', { name: new RegExp(name) })).toBeVisible();
    }

    // Clear the filter so both chips are selectable.
    await page.getByLabel('Find or create a tag').fill('');
    await page.getByRole('button', { name: new RegExp(keep) }).click();
    await page.getByRole('button', { name: new RegExp(fold) }).click();

    await expect(page.getByText(`Merge ${fold} into ${keep}`)).toBeVisible();
    await page.getByRole('button', { name: /^merge$/i }).click();

    await expect(page.getByRole('button', { name: new RegExp(fold) })).toHaveCount(0);
    await expect(page.getByRole('button', { name: new RegExp(keep) })).toBeVisible();
  });
});
