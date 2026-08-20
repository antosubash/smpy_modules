import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * Deleting is reversible now, and that changes what is worth asserting.
 *
 * The interesting cases are the ones that span two screens or two states: a
 * deleted page has to leave the board *and* appear in the trash, and undo has
 * to put it back without silently returning it to the live site.
 */

async function makePage(page: Page, { publish = false }: { publish?: boolean } = {}) {
  const headers = await csrfHeader(page);
  const slug = uniqueSlug('trash');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title: `Trash ${slug}`,
      slug,
      draft_data: { root: { props: { title: slug, width: 'full' } }, content: [], zones: {} },
    },
  });
  const { id } = (await created.json()) as { id: number };
  if (publish) {
    await page.request.post(`/api/pagebuilder/pages/${id}/publish`, { headers, data: {} });
  }
  return { id, slug };
}

const boardCard = (page: Page, stageKey: string, slug: string) =>
  page.locator(
    `[data-testid="board-stage"][data-stage="${stageKey}"] [data-testid="board-card"][data-slug="${slug}"]`,
  );
const trashRow = (page: Page, slug: string) =>
  page.locator(`[data-testid="trash-row"][data-slug="${slug}"]`);

test.describe('Trash', () => {
  test('a deleted draft leaves the board and lands in the trash', async ({ page }) => {
    await login(page);
    const { slug } = await makePage(page);

    await page.goto('/pagebuilder/');
    await boardCard(page, 'draft', slug)
      .getByRole('button', { name: /^delete$/i })
      .click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toContainText('trash for 30 days');
    await dialog.getByRole('button', { name: /^delete$/i }).click();

    await expect(boardCard(page, 'draft', slug)).toHaveCount(0);
    await page.goto('/pagebuilder/trash');
    await expect(trashRow(page, slug)).toBeVisible();
  });

  test('the undo toast puts it straight back', async ({ page }) => {
    await login(page);
    const { slug } = await makePage(page);

    await page.goto('/pagebuilder/');
    await boardCard(page, 'draft', slug)
      .getByRole('button', { name: /^delete$/i })
      .click();
    await page
      .getByRole('alertdialog')
      .getByRole('button', { name: /^delete$/i })
      .click();

    // Ten seconds is the window; the click is what matters, not the timing.
    await page.getByRole('button', { name: /^undo$/i }).click();

    await expect(boardCard(page, 'draft', slug)).toBeVisible();
    await page.goto('/pagebuilder/trash');
    await expect(trashRow(page, slug)).toHaveCount(0);
  });

  test('restoring from the trash returns a published page as a draft', async ({ page }) => {
    await login(page);
    const { id, slug } = await makePage(page, { publish: true });
    expect((await page.request.get(`/p/${slug}`)).status()).toBe(200);

    await page.goto('/pagebuilder/');
    await boardCard(page, 'published', slug)
      .getByRole('button', { name: /^delete$/i })
      .click();
    const dialog = page.getByRole('alertdialog');
    await dialog.getByRole('textbox').fill(slug);
    await dialog.getByRole('button', { name: /^delete$/i }).click();

    // Offline at once — the retention window is for recovery, not for staying live.
    await expect.poll(async () => (await page.request.get(`/p/${slug}`)).status()).toBe(404);

    await page.goto('/pagebuilder/trash');
    await trashRow(page, slug)
      .getByRole('button', { name: /^restore$/i })
      .click();
    await expect(trashRow(page, slug)).toHaveCount(0);

    // Back as a draft, not silently back on the public site.
    const body = await (await page.request.get(`/api/pagebuilder/pages/${id}`)).json();
    expect(body.status).toBe('draft');
    expect((await page.request.get(`/p/${slug}`)).status()).toBe(404);
  });

  test('purging from the trash demands the slug and is final', async ({ page }) => {
    await login(page);
    const { slug } = await makePage(page);
    await page.goto('/pagebuilder/');
    await boardCard(page, 'draft', slug)
      .getByRole('button', { name: /^delete$/i })
      .click();
    await page
      .getByRole('alertdialog')
      .getByRole('button', { name: /^delete$/i })
      .click();

    await page.goto('/pagebuilder/trash');
    await trashRow(page, slug)
      .getByRole('button', { name: /delete forever/i })
      .click();
    const dialog = page.getByRole('alertdialog');
    const confirm = dialog.getByRole('button', { name: /delete forever/i });
    await expect(confirm).toBeDisabled();
    await dialog.getByRole('textbox').fill(slug);
    await confirm.click();

    await expect(trashRow(page, slug)).toHaveCount(0);
    // The slug is free again, which is the observable difference from a soft delete.
    const headers = await csrfHeader(page);
    const again = await page.request.post('/api/pagebuilder/pages', {
      headers,
      data: { title: 'Again', slug, draft_data: { content: [] } },
    });
    expect(again.status()).toBe(201);
  });

  test('the empty trash says what the screen is for', async ({ page }) => {
    await login(page);
    await page.goto('/pagebuilder/trash');
    // Nothing has been deleted in this test, but other specs may have left
    // rows behind — assert the screen renders either way.
    await expect(page.getByRole('heading', { name: 'Trash', level: 1 })).toBeVisible();
    await expect(page.getByText(/recoverable for 30 days/i)).toBeVisible();
  });
});

test.describe('Unpublish', () => {
  test('takes a page offline without losing it', async ({ page }) => {
    await login(page);
    const { slug } = await makePage(page, { publish: true });

    await page.goto('/pagebuilder/');
    await boardCard(page, 'published', slug)
      .getByRole('button', { name: /^unpublish$/i })
      .click();

    const dialog = page.getByRole('alertdialog');
    // The copy has to carry the distinction, or people read this as "delete".
    await expect(dialog).toContainText('answering 404 immediately');
    await expect(dialog).toContainText('Your content is kept');
    await dialog.getByRole('button', { name: /^unpublish$/i }).click();

    // It moves to the draft column rather than disappearing.
    await expect(boardCard(page, 'draft', slug)).toBeVisible();
    await expect(boardCard(page, 'published', slug)).toHaveCount(0);
    await expect.poll(async () => (await page.request.get(`/p/${slug}`)).status()).toBe(404);
  });
});
