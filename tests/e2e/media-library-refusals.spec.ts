import { expect, type Page, test } from '@playwright/test';

import { login, makePage, moduleCsrfHeader, uniqueSlug } from './helpers';

/**
 * The media library's refusals: an asset a page still uses cannot be deleted
 * from the library grid any more than from its own detail page, and a missing
 * asset is a clean not-found.
 *
 * A protection only one of two doors honours is not a protection.
 */

function pngBytes(): Buffer {
  return Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
    'base64',
  );
}

async function uploadAsset(page: Page) {
  const headers = await moduleCsrfHeader(page, '/pagebuilder/');
  const name = `${uniqueSlug('qa-asset')}.png`;
  const created = await page.request.post('/api/pagebuilder/uploads', {
    headers,
    multipart: { file: { name, mimeType: 'image/png', buffer: pngBytes() } },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()) as {
    id: number;
    url: string;
    original_filename: string;
  };
}

test.describe('the media library honours the in-use refusal', () => {
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
    const headers = await moduleCsrfHeader(page, '/pagebuilder/');
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

test.describe('a missing asset is a clean not-found', () => {
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
