/**
 * The media picker (#234). It used to show the library's first 60 uploads and
 * nothing after them, as a plain overlay that let focus wander behind it and
 * did not hand it back. Now every upload is reachable by paging or by a
 * filename search, each thumbnail is named, focus stays in the dialog, and
 * Escape returns it to the Browse button that opened it.
 */

import { expect, type Page, test } from '@playwright/test';

import { login, makePage, moduleCsrfHeader, uniqueSlug } from './helpers';

/** 1x1 transparent PNG: the upload endpoint sniffs content, not the name. */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
);

async function upload(page: Page, name: string): Promise<string> {
  const headers = await moduleCsrfHeader(page, '/pagebuilder/');
  const created = await page.request.post('/api/pagebuilder/uploads', {
    headers,
    multipart: { file: { name, mimeType: 'image/png', buffer: PNG } },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  return ((await created.json()) as { url: string }).url;
}

test.describe('Media picker', () => {
  test('reaches the oldest upload by search, named and keyboard-safe', async ({ page }) => {
    await login(page);
    // A tag of this run's own, so a search finds these files and no others.
    const tag = uniqueSlug('pick').replaceAll('-', '');
    const oldest = `${tag}-oldest.png`;
    const oldestUrl = await upload(page, oldest);
    // Newer than the oldest by more than the 12 a picker page shows.
    let newest = '';
    for (let i = 0; i < 13; i += 1) newest = await upload(page, `${tag}-${i}.png`);

    const id = await makePage(page, {
      slug: uniqueSlug('picker'),
      blocks: [{ type: 'Image', props: { id: 'img1', src: newest, alt: 'Pick target' } }],
    });
    await page.goto(`/pagebuilder/${id}/edit`);
    // The image is 1x1, so click the block's wrapper (Puck makes it a button).
    await page.frameLocator('#preview-frame').getByRole('button', { name: 'Pick target' }).click();

    const browse = page.getByRole('button', { name: 'Browse media…' }).first();
    await browse.focus();
    await page.keyboard.press('Enter');

    const dialog = page.getByRole('dialog', { name: 'Select a file' });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole('button', { name: /\.png/ }).first()).toBeVisible();

    // Tab cycles inside the dialog, never into the editor behind it.
    for (let i = 0; i < 25; i += 1) {
      await page.keyboard.press('Tab');
      expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
    }

    // Escape closes it and gives focus back to Browse.
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(browse).toBeFocused();

    // Reopen, find the oldest upload by name, pick it.
    await browse.click();
    await dialog.getByRole('searchbox', { name: 'Search by file name' }).fill(`${tag}-oldest`);
    const pick = dialog.getByRole('button', { name: new RegExp(oldest) });
    await expect(pick).toBeVisible();
    await expect(dialog.getByRole('button', { name: /\.png/ })).toHaveCount(1);
    await pick.click();
    await expect(dialog).toBeHidden();
    // The URL input of the picker that was opened (the block has more than one).
    const field = browse.locator('xpath=ancestor::div[contains(@class, "space-y-2")][1]');
    await expect(field.getByPlaceholder('Pick from library or paste a URL')).toHaveValue(oldestUrl);

    // Leave the library as it was for the other specs in this shard (a plain
    // DELETE does not check usage, so the page's image goes too).
    const headers = await moduleCsrfHeader(page, '/pagebuilder/');
    const listed = await page.request.get('/api/pagebuilder/uploads', {
      params: { search: tag, limit: 50 },
    });
    for (const asset of ((await listed.json()) as { items: { id: number }[] }).items) {
      await page.request.delete(`/api/pagebuilder/uploads/${asset.id}`, { headers });
    }
  });
});
