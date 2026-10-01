import { expect, type Locator, type Page, test } from '@playwright/test';

import { login } from './helpers';
import {
  addFieldInEditor,
  apiCreateRecord,
  apiCreateType,
  apiDeleteType,
  apiGetRecord,
  saveType,
  uniqueTypeKey,
} from './records-helpers';

/**
 * The `media` field's picker (records ↔ the host's `file_storage` module).
 *
 * The host this suite runs against installs `file_storage`, so the editor is
 * handed a `media_api` prop and a `media` field is a picker rather than the
 * id-or-URL text box. What only a browser can show: the upload really goes
 * through the picker to the media library, the stored value is the file's id
 * (not a URL), and the thumbnail in the editor and the list is an image that
 * actually loaded — `naturalWidth > 0`, not merely an `<img>` in the DOM.
 */

const FILES = '/api/file-storage';

/** A real 1×1 PNG. */
function pngBytes(): Buffer {
  return Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
    'base64',
  );
}

async function expectLoaded(image: Locator): Promise<void> {
  await expect(image).toBeVisible();
  await expect
    .poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0);
}

async function deleteFile(page: Page, id: string): Promise<void> {
  await page.request.delete(`${FILES}/files/${id}`);
}

/** A type with a title and one media field, built through the schema editor. */
async function createTypeInEditor(page: Page, key: string): Promise<void> {
  await page.goto('/admin/records/types/new');
  await expect(page.getByRole('heading', { name: 'New type' })).toBeVisible();
  await page.locator('#type-editor-key').fill(key);
  await page.locator('#type-editor-label').fill('Gallery item');
  await page.locator('#type-editor-label-plural').fill('Gallery items');
  await addFieldInEditor(page, 0, {
    key: 'title',
    type: 'text',
    label: 'Title',
    required: true,
    indexed: true,
  });
  await addFieldInEditor(page, 1, { key: 'photo', type: 'media', label: 'Photo' });
  await page.locator('#type-editor-display-field').selectOption('title');
  await saveType(page);
  await expect(page).toHaveURL(new RegExp(`/admin/records/types/${key}$`));
}

test.describe('Records — media field picker', () => {
  test('uploads through the picker, shows the thumbnail, and removes it', async ({ page }) => {
    test.setTimeout(120_000);
    await login(page);
    const key = uniqueTypeKey('media');
    const filename = `${key}.png`;
    await createTypeInEditor(page, key);

    await page.goto(`/admin/records/${key}/new`);
    await page.locator('#record-field-title').fill('Harbour at dawn');
    const field = page.getByTestId('records-media-field-photo');
    await expect(field.getByText('No file chosen.')).toBeVisible();

    // The Choose button carries the field's id, so a validation error can
    // focus it — and the field's label in its name.
    const choose = page.locator('#record-field-photo');
    await expect(choose).toHaveAccessibleName(/Choose file… Photo/);
    await choose.click();
    const dialog = page.getByRole('dialog', { name: 'Choose a file' });
    await expect(dialog).toBeVisible();

    // Upload picks the new file and closes the dialog.
    const uploaded = page.waitForResponse(
      (response) => response.url().endsWith(`${FILES}/upload`) && response.status() === 201,
    );
    await dialog.getByTestId('records-media-upload-input').setInputFiles({
      name: filename,
      mimeType: 'image/png',
      buffer: pngBytes(),
    });
    const fileId = ((await (await uploaded).json()) as { id: string }).id;
    await expect(dialog).toBeHidden();
    // Focus goes back to the button that opened the dialog.
    await expect(choose).toBeFocused();
    await expect(choose).toHaveAccessibleName(/Replace… Photo/);

    await expectLoaded(field.getByRole('img', { name: filename }));
    await expect(field.getByTestId('records-media-chip')).toContainText('image/png');

    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}/[0-9a-f]{32}$`));
    const uuid = page.url().split('/').pop() as string;
    // The stored value is the id the media library returned, never a URL.
    expect((await apiGetRecord(page, key, uuid)).data.photo).toBe(fileId);

    // The list shows the same file as a small thumbnail: the type's first media
    // field is one of the default columns (unsortable, like any unindexed one).
    await page.goto(`/admin/records/${key}`);
    await expect(page.getByRole('columnheader', { name: 'Photo' })).toBeVisible();
    const row = page.getByTestId('records-record-row').filter({ hasText: 'Harbour at dawn' });
    await expectLoaded(row.getByTestId('records-media-cell').getByRole('img', { name: filename }));

    // Remove, save, and the value is gone — the file itself stays in the library.
    await page.goto(`/admin/records/${key}/${uuid}`);
    await expectLoaded(field.getByRole('img', { name: filename }));
    await field.getByRole('button', { name: /Remove/ }).click();
    await expect(field.getByText('No file chosen.')).toBeVisible();
    await expect(choose).toBeFocused();
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();
    await expect
      .poll(async () => (await apiGetRecord(page, key, uuid)).data.photo ?? null)
      .toBeNull();
    expect((await page.request.get(`${FILES}/files/${fileId}`)).status()).toBe(200);

    await deleteFile(page, fileId);
    await apiDeleteType(page, key, 1);
  });

  test('picks an existing file with the keyboard, and fits a phone screen', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('mediakb');
    await apiCreateType(page, {
      key,
      label: 'Keyboard item',
      fields: [
        { key: 'title', type: 'text', label: 'Title', required: true, indexed: true },
        { key: 'photo', type: 'media', label: 'Photo' },
      ],
      display_field: 'title',
    });
    const created = await page.request.post(`${FILES}/upload`, {
      multipart: { file: { name: `${key}.png`, mimeType: 'image/png', buffer: pngBytes() } },
    });
    expect(created.status(), await created.text()).toBe(201);
    const file = (await created.json()) as { id: string; filename: string };

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/admin/records/${key}/new`);
    await page.locator('#record-field-photo').focus();
    await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog', { name: 'Choose a file' });
    await expect(dialog).toBeVisible();

    // Nothing on a 390px screen scrolls sideways, and the dialog fits it.
    const box = await dialog.boundingBox();
    expect(box && box.x >= 0 && box.x + box.width <= 390).toBeTruthy();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);

    // Uploads list newest first, so it is on page one; Enter on it picks it.
    const item = dialog.getByRole('button', { name: new RegExp(`^${file.filename}, image/png`) });
    await item.focus();
    await page.keyboard.press('Enter');
    await expect(dialog).toBeHidden();
    await expectLoaded(page.getByTestId('records-media-field-photo').getByRole('img'));

    // Escape closes without changing anything.
    await page.locator('#record-field-photo').click();
    await expect(dialog).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(dialog).toBeHidden();
    await expect(
      page.getByTestId('records-media-field-photo').getByRole('img'),
    ).toHaveAccessibleName(file.filename);

    await deleteFile(page, file.id);
    await apiDeleteType(page, key, 0);
  });

  test('a file deleted from the library shows as missing and keeps its id', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('mediagone');
    await apiCreateType(page, {
      key,
      label: 'Gone item',
      fields: [
        { key: 'title', type: 'text', label: 'Title', required: true, indexed: true },
        { key: 'photo', type: 'media', label: 'Photo' },
      ],
      display_field: 'title',
    });
    const created = await page.request.post(`${FILES}/upload`, {
      multipart: { file: { name: `${key}.png`, mimeType: 'image/png', buffer: pngBytes() } },
    });
    const file = (await created.json()) as { id: string };
    const record = await apiCreateRecord(page, key, {
      data: { title: 'Orphan', photo: file.id },
    });
    await deleteFile(page, file.id);

    await page.goto(`/admin/records/${key}/${record.uuid}`);
    const missing = page
      .getByTestId('records-media-field-photo')
      .getByTestId('records-media-missing');
    await expect(missing).toContainText('File missing');
    await expect(missing).toContainText(file.id);
    expect((await apiGetRecord(page, key, record.uuid)).data.photo).toBe(file.id);

    await page.goto(`/admin/records/${key}`);
    await expect(page.getByTestId('records-media-cell').getByText('File missing')).toBeVisible();

    await apiDeleteType(page, key, 1);
  });
});
