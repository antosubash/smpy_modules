import { expect, type Page, test } from '@playwright/test';

import { login, uniqueSlug } from './helpers';

/**
 * Media library upload rejections (#145).
 *
 * The server answers a refused upload in English prose (`{"detail": …}`); the
 * library used to print that body raw. What a person should see instead is a
 * sentence in the console's language on the failed row, and one toast for the
 * whole batch, however many files in it failed.
 */

/** 1×1 transparent PNG — the upload endpoint sniffs content, not the name. */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
);

const good = () => ({ name: `${uniqueSlug('ok')}.png`, mimeType: 'image/png', buffer: PNG });
/** Text wearing a .png name: refused with 415. */
const fake = (name = `${uniqueSlug('fake')}.png`) => ({
  name,
  mimeType: 'image/png',
  buffer: Buffer.from('not an image'),
});
/** Over the 10 MiB default `media_max_bytes`: refused with 413. */
const huge = () => ({
  name: `${uniqueSlug('huge')}.png`,
  mimeType: 'image/png',
  buffer: Buffer.concat([PNG, Buffer.alloc(11 * 1024 * 1024)]),
});

async function uploadBatch(page: Page, files: ReturnType<typeof good>[]) {
  await page.locator('input[type=file]').first().setInputFiles(files);
}

/** Nothing a person reads should be the wire format or the server's English. */
async function expectNoRawServerText(page: Page) {
  const body = await page.locator('main').innerText();
  expect(body).not.toContain('"detail"');
  expect(body).not.toContain('File contents do not match');
  expect(body).not.toMatch(/errors\.upload_|media\.uploaded/);
}

test.describe('Media library upload errors', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('a mixed batch shows translated rows and one summary toast', async ({ page }) => {
    await page.goto('/pagebuilder/media');
    await uploadBatch(page, [good(), fake(), huge()]);

    const toast = page.locator('[data-sonner-toast]');
    await expect(toast.getByText('2 files could not be uploaded.')).toBeVisible();
    await expect(toast).toHaveCount(1);
    await expect(
      page.getByText('This file type is not supported. Upload a valid image.'),
    ).toBeVisible();
    await expect(page.getByText('This file is too large to upload.')).toBeVisible();
    await expect(page.getByText('Uploaded 1 file.')).toBeVisible();
    await expectNoRawServerText(page);
  });

  test('in German, a single refusal names the file in one toast', async ({ page, context }) => {
    await context.addCookies([
      { name: 'locale', value: 'de', url: new URL('/', page.url()).toString() },
    ]);
    await page.goto('/pagebuilder/media');
    await expect(page.getByRole('heading', { name: 'Mediathek', exact: true })).toBeVisible();

    const name = `${uniqueSlug('kaputt')}.png`;
    await uploadBatch(page, [fake(name)]);

    const toast = page.locator('[data-sonner-toast]');
    await expect(
      toast.getByText(
        `${name} konnte nicht hochgeladen werden: Dieser Dateityp wird nicht unterstützt. Laden Sie ein gültiges Bild hoch.`,
      ),
    ).toBeVisible();
    await expect(toast).toHaveCount(1);
    await expectNoRawServerText(page);
  });

  test('in German, successes and the batch summary are translated', async ({ page, context }) => {
    await context.addCookies([
      { name: 'locale', value: 'de', url: new URL('/', page.url()).toString() },
    ]);
    await page.goto('/pagebuilder/media');
    await uploadBatch(page, [good(), good(), fake(), fake()]);

    const toast = page.locator('[data-sonner-toast]');
    await expect(toast.getByText('2 Dateien konnten nicht hochgeladen werden.')).toBeVisible();
    await expect(toast).toHaveCount(1);
    await expect(page.getByText('2 Dateien hochgeladen.')).toBeVisible();
    await expectNoRawServerText(page);
  });
});
