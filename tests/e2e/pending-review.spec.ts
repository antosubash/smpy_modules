/**
 * The approver queue at /pagebuilder/pending.
 *
 * Its Approve and Reject controls became real dialogs (they were `confirm()`
 * and `window.prompt`), and nothing covered this page at all — so the
 * rejection note being *required*, and the queue emptying afterwards, were
 * only ever checked by reading the code.
 */

import { expect, type Page, test } from '@playwright/test';

import { clickAndConfirm, csrfHeader, login, uniqueSlug } from './helpers';

/** A page sitting in `submitted_for_review`, which is what the queue lists. */
async function submitForReview(page: Page, title: string): Promise<{ id: number; slug: string }> {
  const headers = await csrfHeader(page);
  const slug = uniqueSlug('review');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: { title, slug, draft_data: { content: [] } },
  });
  expect(created.status(), await created.text()).toBe(201);
  const id = (await created.json()).id as number;

  const submitted = await page.request.post(`/api/pagebuilder/pages/${id}/submit`, {
    headers,
    data: {},
  });
  expect(submitted.status(), await submitted.text()).toBe(200);
  return { id, slug };
}

async function statusOf(page: Page, id: number): Promise<string> {
  const response = await page.request.get(`/api/pagebuilder/pages/${id}`);
  return (await response.json()).status as string;
}

test.describe('Pending review queue', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('lists submitted pages and is reachable from the page list', async ({ page }) => {
    const title = `Queued ${uniqueSlug('q')}`;
    const { id } = await submitForReview(page, title);

    await page.goto('/pagebuilder/');
    await page.getByRole('button', { name: /pending review/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/pending$/);
    await expect(page.locator('tr', { hasText: title })).toBeVisible();

    await page.request.delete(`/api/pagebuilder/pages/${id}`, { headers: await csrfHeader(page) });
  });

  test('rejecting requires a note and sends the page back to draft', async ({ page }) => {
    const title = `Reject me ${uniqueSlug('r')}`;
    const { id } = await submitForReview(page, title);

    await page.goto('/pagebuilder/pending');
    const row = page.locator('tr', { hasText: title });
    await row.getByRole('button', { name: /^reject$/i }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    // The note is required, so the submit button stays disabled until there is
    // one. `window.prompt` could not express this — it accepted empty and the
    // call then failed server-side.
    const submit = dialog.getByRole('button', { name: /^reject$/i });
    await expect(submit).toBeDisabled();

    await dialog.getByRole('textbox').fill('The hero image is still a placeholder.');
    await expect(submit).toBeEnabled();
    await submit.click();

    await expect(dialog).toHaveCount(0);
    await expect(page.locator('tr', { hasText: title })).toHaveCount(0);
    expect(await statusOf(page, id)).toBe('draft');

    await page.request.delete(`/api/pagebuilder/pages/${id}`, { headers: await csrfHeader(page) });
  });

  test('cancelling a rejection leaves the page in the queue', async ({ page }) => {
    const title = `Keep me ${uniqueSlug('k')}`;
    const { id } = await submitForReview(page, title);

    await page.goto('/pagebuilder/pending');
    await page
      .locator('tr', { hasText: title })
      .getByRole('button', { name: /^reject$/i })
      .click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: /^cancel$/i }).click();

    await expect(dialog).toHaveCount(0);
    await expect(page.locator('tr', { hasText: title })).toBeVisible();
    expect(await statusOf(page, id)).toBe('submitted_for_review');

    await page.request.delete(`/api/pagebuilder/pages/${id}`, { headers: await csrfHeader(page) });
  });

  test('approving publishes the page and clears it from the queue', async ({ page }) => {
    const title = `Approve me ${uniqueSlug('a')}`;
    const { id, slug } = await submitForReview(page, title);

    await page.goto('/pagebuilder/pending');
    await clickAndConfirm(
      page,
      page.locator('tr', { hasText: title }).getByRole('button', { name: /^approve$/i }),
      /^approve$/i,
      async (dialog) => {
        // The dialog names the page and the URL it is about to go live at —
        // the `confirm()` it replaced said "Approve and publish this page?"
        // for every row in the queue.
        await expect(dialog).toContainText(title);
        await expect(dialog).toContainText(`/p/${slug}`);
      },
    );

    await expect(page.locator('tr', { hasText: title })).toHaveCount(0);
    expect(await statusOf(page, id)).toBe('published');

    // Published means actually served.
    expect((await page.request.get(`/p/${slug}`)).status()).toBe(200);

    await page.request.delete(`/api/pagebuilder/pages/${id}`, { headers: await csrfHeader(page) });
  });

  test('shows an empty state when nothing is awaiting review', async ({ page }) => {
    await page.goto('/pagebuilder/pending');
    await expect(page.getByText(/no pages are awaiting review/i)).toBeVisible();
  });
});
