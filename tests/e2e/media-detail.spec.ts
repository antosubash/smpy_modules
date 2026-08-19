import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * Media asset detail — screen 2e.
 *
 * The case worth a browser is the refusal: deleting an asset a page still uses
 * does not fail loudly, it just leaves a broken image nobody notices. So the
 * assertions are about the block and about it naming somewhere to go.
 */

/** A real PNG — the upload endpoint sniffs content, not just the extension. */
function pngBytes(): Buffer {
  // 1×1 transparent PNG.
  return Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
    'base64',
  );
}

async function upload(page: Page) {
  const headers = await csrfHeader(page);
  const name = `${uniqueSlug('asset')}.png`;
  const created = await page.request.post('/api/pagebuilder/uploads', {
    headers,
    multipart: {
      file: { name, mimeType: 'image/png', buffer: pngBytes() },
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  return (await created.json()) as { id: number; url: string; original_filename: string };
}

async function pageUsing(page: Page, url: string, title: string) {
  const headers = await csrfHeader(page);
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title,
      slug: uniqueSlug('uses'),
      draft_data: {
        root: { props: { title, width: 'full' } },
        content: [{ type: 'Image', props: { id: 'i1', src: url } }],
        zones: {},
      },
    },
  });
  expect(created.ok()).toBeTruthy();
}

test.describe('Media asset detail', () => {
  test('is reachable from the library and shows the file facts', async ({ page }) => {
    await login(page);
    const asset = await upload(page);

    await page.goto(`/pagebuilder/media/${asset.id}`);

    await expect(
      page.getByRole('heading', { name: asset.original_filename, level: 1 }),
    ).toBeVisible();
    await expect(page.getByText(asset.url, { exact: false })).toBeVisible();
  });

  test('alt text, caption and credit save', async ({ page }) => {
    await login(page);
    const asset = await upload(page);

    await page.goto(`/pagebuilder/media/${asset.id}`);
    await page.getByLabel('Alt text').fill('Aerial view of mixed canopy over plot 14');
    await page.getByLabel('Credit').fill('J. Okonkwo / field team');
    await page.getByRole('button', { name: /^save$/i }).click();

    // Scoped to the toast: the panel's own status line also says "Saved".
    await expect(page.locator('[data-sonner-toast]').getByText('Saved')).toBeVisible();
    const back = await (await page.request.get(`/api/pagebuilder/uploads/${asset.id}`)).json();
    expect(back.asset.alt_text).toBe('Aerial view of mixed canopy over plot 14');
    expect(back.asset.credit).toBe('J. Okonkwo / field team');
  });

  test('an unused asset says so and offers delete', async ({ page }) => {
    await login(page);
    const asset = await upload(page);

    await page.goto(`/pagebuilder/media/${asset.id}`);

    await expect(page.getByTestId('media-usage')).toHaveAttribute('data-total', '0');
    await expect(page.getByRole('button', { name: /delete asset/i })).toBeVisible();
  });

  test('an asset in use names the page and blocks deleting', async ({ page }) => {
    await login(page);
    const asset = await upload(page);
    await pageUsing(page, asset.url, 'Depends on this image');

    await page.goto(`/pagebuilder/media/${asset.id}`);

    const usage = page.getByTestId('media-usage');
    await expect(usage).not.toHaveAttribute('data-total', '0');
    // Named, not counted: the reason to read this list is to go and detach it.
    await expect(usage).toContainText('Depends on this image');
    await expect(page.getByText(/Delete is blocked while this asset is in use/)).toBeVisible();
    await expect(page.getByRole('button', { name: /delete asset/i })).toHaveCount(0);
  });

  test('the API refuses a delete even when asked directly', async ({ page }) => {
    await login(page);
    const asset = await upload(page);
    await pageUsing(page, asset.url, 'Still using it');

    const headers = await csrfHeader(page);
    const refused = await page.request.delete(`/api/pagebuilder/uploads/${asset.id}/checked`, {
      headers,
    });

    expect(refused.status()).toBe(409);
    const detail = (await refused.json()).detail as string;
    expect(detail).toContain('Still using it');
    expect(detail).toContain('Detach it there first');
  });

  test('an unused asset deletes and leaves the library', async ({ page }) => {
    await login(page);
    const asset = await upload(page);

    await page.goto(`/pagebuilder/media/${asset.id}`);
    await page.getByRole('button', { name: /delete asset/i }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toContainText('No page references this asset');
    await dialog.getByRole('button', { name: /^delete$/i }).click();

    await expect(page).toHaveURL(/\/pagebuilder\/media$/);
    expect((await page.request.get(`/api/pagebuilder/uploads/${asset.id}`)).status()).toBe(404);
  });
});
