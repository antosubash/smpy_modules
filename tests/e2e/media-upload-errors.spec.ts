import { crc32, deflateSync } from 'node:zlib';

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

function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, 'ascii'), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

/** A few hundred bytes whose header claims 20000×20000 (400 megapixels, over
 *  twice Pillow's limit): refused with 413 `image_too_many_pixels` (#221).
 *  Pillow refuses it on reading the header, so the pixel data is never needed. */
const bomb = () => {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(20000, 0);
  ihdr.writeUInt32BE(20000, 4);
  ihdr.set([8, 0, 0, 0, 0], 8); // 8-bit greyscale
  const png = Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(Buffer.alloc(20001))),
    chunk('IEND', Buffer.alloc(0)),
  ]);
  return { name: `${uniqueSlug('bomb')}.png`, mimeType: 'image/png', buffer: png };
};

async function uploadBatch(page: Page, files: ReturnType<typeof good>[]) {
  await page.locator('input[type=file]').first().setInputFiles(files);
}

/** Nothing a person reads should be the wire format or the server's English. */
async function expectNoRawServerText(page: Page) {
  const body = await page.locator('main').innerText();
  expect(body).not.toContain('"detail"');
  expect(body).not.toContain('File contents do not match');
  expect(body).not.toContain('Image dimensions exceed');
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

  test('an image with too many pixels says so, in both languages', async ({ page, context }) => {
    await page.goto('/pagebuilder/media');
    await uploadBatch(page, [bomb()]);
    await expect(
      page.getByText('This image has too many pixels to process.', { exact: false }).first(),
    ).toBeVisible();
    await expect(page.getByText('This file is too large to upload.')).toHaveCount(0);
    await expectNoRawServerText(page);

    await context.addCookies([
      { name: 'locale', value: 'de', url: new URL('/', page.url()).toString() },
    ]);
    await page.goto('/pagebuilder/media');
    await uploadBatch(page, [bomb()]);
    await expect(
      page.getByText('Dieses Bild hat zu viele Pixel', { exact: false }).first(),
    ).toBeVisible();
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
