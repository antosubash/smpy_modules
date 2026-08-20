import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * Every editable field reaches the autosave.
 *
 * `isDirty` is computed by comparing a snapshot of the form against the one it
 * loaded with. A field that the write payload carries but the snapshot omits is
 * invisible to that comparison: the autosave never fires, the status line goes
 * on saying "Saved", the unload guard never arms, and the edit dies on the next
 * navigation — while clicking Save by hand would have persisted it, which is
 * exactly what makes the omission survive casual testing.
 *
 * The Page tab's fields are the ones that had this bug, so they are the ones
 * asserted here.
 */

async function makePage(page: Page, slug: string): Promise<number> {
  const headers = await csrfHeader(page);
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: { title: 'Autosave subject', slug, draft_data: { content: [] } },
  });
  expect(created.status(), await created.text()).toBe(201);
  return (await created.json()).id as number;
}

async function stored(page: Page, id: number): Promise<Record<string, unknown>> {
  const response = await page.request.get(`/api/pagebuilder/pages/${id}`);
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()) as Record<string, unknown>;
}

test.describe('Autosave sees every Page-tab field', () => {
  test('a nav toggle marks the page dirty and saves itself', async ({ page }) => {
    await login(page);
    const id = await makePage(page, uniqueSlug('autosave-nav'));

    await page.goto(`/pagebuilder/${id}/edit`);
    await page.getByRole('button', { name: /^settings$/i }).click();
    await expect(page.getByTestId('inspector-tab-page')).toBeVisible();

    // Touch nothing else — the whole point is that this alone counts as an edit.
    await page.getByLabel('Show in header nav').click();

    await expect(page.getByTestId('autosave-status')).toHaveText(/unsaved changes/i);
    await expect.poll(async () => (await stored(page, id)).show_in_header_nav).toBe(true);
  });

  test('a meta title alone saves itself', async ({ page }) => {
    await login(page);
    const id = await makePage(page, uniqueSlug('autosave-metatitle'));

    await page.goto(`/pagebuilder/${id}/edit`);
    await page.getByRole('button', { name: /^settings$/i }).click();
    await page.getByTestId('inspector-tab-seo').click();
    await page.getByLabel('Meta title').fill('A title only search sees');

    await expect
      .poll(async () => (await stored(page, id)).meta_title)
      .toBe('A title only search sees');
  });

  test('an untouched page does not claim unsaved changes', async ({ page }) => {
    await login(page);
    const id = await makePage(page, uniqueSlug('autosave-clean'));

    await page.goto(`/pagebuilder/${id}/edit`);
    await page.getByRole('button', { name: /^settings$/i }).click();
    await expect(page.getByTestId('inspector-tab-page')).toBeVisible();

    // The other half of the fix: the initial snapshot has to match the form's
    // own defaults, or adding fields to it makes every page load dirty.
    await expect(page.getByTestId('autosave-status')).not.toHaveText(/unsaved changes/i);
  });
});
