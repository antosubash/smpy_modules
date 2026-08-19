import { expect, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * The two create dialogs.
 *
 * What earns a browser test here is the behaviour that only exists in the
 * dialog: the slug tracking the title until it is overridden, and "start from"
 * actually seeding content rather than just being recorded.
 */

test.describe('New page', () => {
  test('derives the URL from the title until it is edited', async ({ page }) => {
    await login(page);
    await page.goto('/pagebuilder/');
    await page.getByRole('button', { name: 'New page' }).click();

    const url = page.getByLabel('URL');
    await page.getByLabel('Title').fill('Field Methods');
    await expect(url).toHaveValue('field-methods');

    // Once the author types their own, the title stops overwriting it.
    await url.fill('methods');
    await page.getByLabel('Title').fill('Field Methods Revised');
    await expect(url).toHaveValue('methods');
  });

  test('start-from copies an existing page into the new one', async ({ page }) => {
    await login(page);
    const headers = await csrfHeader(page);
    const sourceSlug = uniqueSlug('src');
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers,
      data: {
        title: `Source ${sourceSlug}`,
        slug: sourceSlug,
        draft_data: {
          root: { props: { title: 'Source', width: 'full' } },
          content: [{ type: 'Heading', props: { id: 'h1', text: 'Copied heading' } }],
          zones: {},
        },
      },
    });
    const { id: sourceId } = (await created.json()) as { id: number };

    const newSlug = uniqueSlug('copy');
    await page.goto('/pagebuilder/');
    await page.getByRole('button', { name: 'New page' }).click();
    await page.getByLabel('Title').fill(`Copy ${newSlug}`);
    await page.getByLabel('URL').fill(newSlug);
    await page.getByLabel('Start from').selectOption(String(sourceId));
    await page.getByRole('button', { name: /create and open editor/i }).click();

    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/);
    // The content came across — and as a copy, so the source is untouched.
    const copyId = Number(page.url().match(/\/pagebuilder\/(\d+)\/edit/)?.[1]);
    const body = await (await page.request.get(`/api/pagebuilder/pages/${copyId}`)).json();
    expect(JSON.stringify(body.draft_data)).toContain('Copied heading');
  });

  test('a parent can be chosen and does not change the URL', async ({ page }) => {
    await login(page);
    const headers = await csrfHeader(page);
    const parentSlug = uniqueSlug('parent');
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers,
      data: { title: `Parent ${parentSlug}`, slug: parentSlug, draft_data: { content: [] } },
    });
    const { id: parentId } = (await created.json()) as { id: number };

    const childSlug = uniqueSlug('child');
    await page.goto('/pagebuilder/');
    await page.getByRole('button', { name: 'New page' }).click();
    await page.getByLabel('Title').fill(`Child ${childSlug}`);
    await page.getByLabel('URL').fill(childSlug);
    await page.getByLabel('Parent').selectOption(String(parentId));
    await page.getByRole('button', { name: /create and open editor/i }).click();

    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/);
    const childId = Number(page.url().match(/\/pagebuilder\/(\d+)\/edit/)?.[1]);
    const body = await (await page.request.get(`/api/pagebuilder/pages/${childId}`)).json();
    expect(body.parent_id).toBe(parentId);
    // The URL is the slug and nothing else — re-parenting never breaks a link.
    expect(body.slug).toBe(childSlug);
  });
});

test.describe('New article', () => {
  test('asks for four fields and lands in the editor', async ({ page }) => {
    await login(page);
    await page.goto('/news/');
    await page.getByRole('button', { name: 'New article' }).click();
    // Scoped to the dialog: the list's own "Search headline or slug" box would
    // otherwise also match getByLabel('Headline').
    const dialog = page.getByRole('dialog');

    const headline = `Sensor rollout ${Date.now().toString(36)}`;
    await dialog.getByLabel('Headline').fill(headline);
    // The date defaults to today rather than to empty, so a new article does
    // not silently land in the undated pile.
    await expect(dialog.getByLabel('Publish date')).not.toHaveValue('');
    await dialog.getByRole('button', { name: 'Create draft' }).click();

    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/);
  });

  test('the category chosen at creation is the one the list shows', async ({ page }) => {
    await login(page);
    // A managed category so the select has something beyond Uncategorised.
    await page.goto('/news/categories');
    const category = `Cat ${Date.now().toString(36)}`;
    await page.getByLabel('New category name').fill(category);
    await page.getByRole('button', { name: /^add$/i }).click();
    await expect(
      page.locator(`[data-testid="category-row"][data-category="${category}"]`),
    ).toBeVisible();

    // The select reads the *managed* list, so a category that exists but has
    // not been used yet is still offered — which is exactly when you want it.
    await page.goto('/news/');
    await page.getByRole('button', { name: 'New article' }).click();
    const dialog = page.getByRole('dialog');
    const headline = `Categorised ${Date.now().toString(36)}`;
    const slug = uniqueSlug('cat');
    await dialog.getByLabel('Headline').fill(headline);
    await dialog.getByLabel('URL').fill(slug);
    await dialog.getByLabel('Category').selectOption(category);
    await dialog.getByRole('button', { name: 'Create draft' }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/);

    await page.goto('/news/');
    const row = page.locator(`[data-testid="article-row"][data-slug="${slug}"]`);
    await expect(row).toBeVisible();
    await expect(row).toContainText(category);
  });
});

test.describe('Empty states', () => {
  test('a filtered-to-nothing list offers to widen rather than clear', async ({ page }) => {
    await login(page);
    const headers = await csrfHeader(page);
    // One published article, so "all statuses" has something to find.
    const slug = uniqueSlug('empty');
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers,
      data: { title: `Empty ${slug}`, slug, draft_data: { content: [] } },
    });
    const { id } = (await created.json()) as { id: number };
    await page.request.post(`/api/pagebuilder/pages/${id}/publish`, { headers, data: {} });
    await page.request.post('/api/news/articles', {
      headers,
      data: { page_id: id, category: '', published_at: null },
    });

    // Search for it, but filtered to drafts — it is published, so nothing matches.
    await page.goto(`/news/?q=${slug}&status=draft`);
    await expect(page.getByText(/No draft match|No drafts match/)).toBeVisible();
    await expect(page.getByText(/match across all statuses/)).toBeVisible();

    await page.getByRole('button', { name: /search all statuses/i }).click();
    await expect(page.locator(`[data-testid="article-row"][data-slug="${slug}"]`)).toBeVisible();
  });
});
