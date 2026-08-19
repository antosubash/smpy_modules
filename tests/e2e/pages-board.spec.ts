import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * The pages board — the default view.
 *
 * What is worth asserting here is *movement*: a card has to leave one column
 * and appear in another when its state changes. A test that only checked the
 * columns render would pass against a board that never updates.
 */

async function makePage(
  page: Page,
  { publish = false, publishAt = null }: { publish?: boolean; publishAt?: string | null } = {},
) {
  const headers = await csrfHeader(page);
  const slug = uniqueSlug('board');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title: `Board ${slug}`,
      slug,
      draft_data: { root: { props: { title: slug, width: 'full' } }, content: [], zones: {} },
    },
  });
  const { id } = (await created.json()) as { id: number };
  if (publish) {
    await page.request.post(`/api/pagebuilder/pages/${id}/publish`, { headers, data: {} });
  }
  if (publishAt) {
    await page.request.post(`/api/pagebuilder/pages/${id}/schedule`, {
      headers,
      data: { publish_at: publishAt },
    });
  }
  return { id, slug };
}

const stage = (page: Page, key: string) =>
  page.locator(`[data-testid="board-stage"][data-stage="${key}"]`);
const cardIn = (page: Page, key: string, slug: string) =>
  stage(page, key).locator(`[data-testid="board-card"][data-slug="${slug}"]`);

test.describe('Pages board', () => {
  test('is the default view and shows the pipeline columns', async ({ page }) => {
    await login(page);
    await makePage(page);

    await page.goto('/pagebuilder/');
    await expect(stage(page, 'draft')).toBeVisible();
    await expect(stage(page, 'scheduled')).toBeVisible();
    await expect(stage(page, 'published')).toBeVisible();
  });

  test('publishing from a card moves it into the published column', async ({ page }) => {
    await login(page);
    const { slug } = await makePage(page);

    await page.goto('/pagebuilder/');
    await expect(cardIn(page, 'draft', slug)).toBeVisible();

    await cardIn(page, 'draft', slug)
      .getByRole('button', { name: /^publish$/i })
      .click();

    await expect(cardIn(page, 'published', slug)).toBeVisible();
    await expect(cardIn(page, 'draft', slug)).toHaveCount(0);
  });

  test('a draft with a future date sits in Scheduled, not Draft', async ({ page }) => {
    await login(page);
    // Scheduled is not a third status — it is a draft that will flip itself,
    // and the board is the only place that distinction is visible.
    const future = new Date(Date.now() + 21 * 86_400_000).toISOString();
    const { slug } = await makePage(page, { publishAt: future });

    await page.goto('/pagebuilder/');
    await expect(cardIn(page, 'scheduled', slug)).toBeVisible();
    await expect(cardIn(page, 'scheduled', slug)).toContainText('publishes');
    await expect(cardIn(page, 'draft', slug)).toHaveCount(0);
  });

  test('deleting a published page demands its slug typed out', async ({ page }) => {
    await login(page);
    const { slug } = await makePage(page, { publish: true });

    await page.goto('/pagebuilder/');
    await cardIn(page, 'published', slug)
      .getByRole('button', { name: /^delete$/i })
      .click();

    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toContainText('starts answering 404');
    const confirm = dialog.getByRole('button', { name: /delete forever/i });
    // Locked until the slug is typed exactly — the delay is the safeguard.
    await expect(confirm).toBeDisabled();
    await dialog.getByRole('textbox').fill(slug.slice(0, -1));
    await expect(confirm).toBeDisabled();
    await dialog.getByRole('textbox').fill(slug);
    await expect(confirm).toBeEnabled();
    await confirm.click();

    await expect(cardIn(page, 'published', slug)).toHaveCount(0);
  });

  test('a draft deletes without ceremony', async ({ page }) => {
    await login(page);
    const { slug } = await makePage(page);

    await page.goto('/pagebuilder/');
    await cardIn(page, 'draft', slug)
      .getByRole('button', { name: /^delete$/i })
      .click();

    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toContainText('never published');
    // No phrase to type: nothing on the site changes.
    await expect(dialog.getByRole('textbox')).toHaveCount(0);
    await dialog.getByRole('button', { name: /^delete$/i }).click();

    await expect(cardIn(page, 'draft', slug)).toHaveCount(0);
  });

  test('the view toggle swaps the board for the table and back', async ({ page }) => {
    await login(page);
    await makePage(page);

    await page.goto('/pagebuilder/');
    await expect(stage(page, 'draft')).toBeVisible();

    await page.getByRole('button', { name: /^list view$/i }).click();
    await expect(stage(page, 'draft')).toHaveCount(0);
    await expect(page.getByRole('table')).toBeVisible();
    await expect(page).toHaveURL(/[?&]view=list/);

    await page.getByRole('button', { name: /^board view$/i }).click();
    await expect(stage(page, 'draft')).toBeVisible();
  });
});
