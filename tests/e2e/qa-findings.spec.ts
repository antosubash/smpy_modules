import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * The three gaps the QA browser pass found, each pinned.
 *
 * They share a theme: a guarantee was implemented on one route and not on the
 * other route that reaches the same operation. A protection only one of two
 * doors honours is not a protection.
 */

function pngBytes(): Buffer {
  return Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
    'base64',
  );
}

async function uploadAsset(page: Page) {
  const headers = await csrfHeader(page);
  const name = `${uniqueSlug('qa-asset')}.png`;
  const created = await page.request.post('/api/pagebuilder/uploads', {
    headers,
    multipart: { file: { name, mimeType: 'image/png', buffer: pngBytes() } },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()) as { id: number; url: string; original_filename: string };
}

async function makePage(
  page: Page,
  { slug, publish = false, blocks = [] as unknown[] },
): Promise<number> {
  const headers = await csrfHeader(page);
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title: `QA ${slug}`,
      slug,
      draft_data: {
        root: { props: { title: `QA ${slug}`, width: 'full' } },
        content: blocks,
        zones: {},
      },
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  const id = (await created.json()).id as number;
  if (publish) {
    const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
      headers,
      data: {},
    });
    expect(published.ok(), await published.text()).toBeTruthy();
  }
  return id;
}

test.describe('QA: the media library honours the in-use refusal', () => {
  test('deleting an in-use asset from the library is refused, not just from its detail page', async ({
    page,
  }) => {
    await login(page);
    const asset = await uploadAsset(page);
    await makePage(page, {
      slug: uniqueSlug('qa-uses-asset'),
      blocks: [{ type: 'Image', props: { id: 'i1', src: asset.url } }],
    });

    // The library grid used to call the *unchecked* delete, so the whole
    // "refuses while in use" guarantee could be walked around by deleting from
    // the grid instead of from the asset's own page.
    const headers = await csrfHeader(page);
    const refused = await page.request.delete(`/api/pagebuilder/uploads/${asset.id}/checked`, {
      headers,
    });
    expect(refused.status()).toBe(409);

    await page.goto('/pagebuilder/media');
    const card = page.locator(`li:has-text("${asset.original_filename}")`).first();
    await expect(card).toBeVisible();
    await card.getByRole('button', { name: /^delete$/i }).click();

    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: /^delete$/i }).click();

    // The dialog stays open and shows the refusal rather than closing on a
    // delete that did not happen.
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText(/still used|in use|Detach/i);

    // And the asset is still there.
    expect((await page.request.get(`/api/pagebuilder/uploads/${asset.id}`)).status()).toBe(200);
  });
});

test.describe('QA: deleting a published page from the list view', () => {
  test('demands the slug typed, exactly as the board card does', async ({ page }) => {
    await login(page);
    const slug = uniqueSlug('qa-published-del');
    await makePage(page, { slug, publish: true });

    await page.goto(`/pagebuilder/?view=list&search=${slug}`);
    const row = page.locator('tr', { hasText: slug });
    await expect(row).toBeVisible();
    await row.getByRole('button', { name: /^delete$/i }).click();

    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();
    // Locked until the slug is typed — the live URL going dark is the design's
    // high blast radius wherever it is triggered from.
    await expect(dialog.getByRole('button', { name: /^delete$/i })).toBeDisabled();

    await dialog.locator('#confirm-dialog-phrase').fill('not-the-slug');
    await expect(dialog.getByRole('button', { name: /^delete$/i })).toBeDisabled();

    await dialog.locator('#confirm-dialog-phrase').fill(slug);
    await expect(dialog.getByRole('button', { name: /^delete$/i })).toBeEnabled();
  });

  test('a draft keeps the one-click confirm', async ({ page }) => {
    await login(page);
    const slug = uniqueSlug('qa-draft-del');
    await makePage(page, { slug });

    await page.goto(`/pagebuilder/?view=list&search=${slug}`);
    await page
      .locator('tr', { hasText: slug })
      .getByRole('button', { name: /^delete$/i })
      .click();

    const dialog = page.getByRole('alertdialog');
    await expect(dialog.locator('#confirm-dialog-phrase')).toHaveCount(0);
    await expect(dialog.getByRole('button', { name: /^delete$/i })).toBeEnabled();
    // And it says where the page actually goes, rather than "for good".
    await expect(dialog).toContainText(/trash for 30 days/i);
  });
});

test.describe('QA: a missing asset is a clean not-found', () => {
  test('does not dump the server response into the page', async ({ page }) => {
    await login(page);

    await page.goto('/pagebuilder/media/999999');

    await expect(page.getByRole('heading', { name: /asset not found/i })).toBeVisible();
    // The old error path rendered the whole Inertia HTML shell as the message,
    // putting the permissions list and menu JSON on screen.
    const body = (await page.locator('body').innerText()).toLowerCase();
    expect(body).not.toContain('data-page');
    expect(body).not.toContain('"permissions"');
    expect(body).not.toContain('<!doctype');
  });
});
