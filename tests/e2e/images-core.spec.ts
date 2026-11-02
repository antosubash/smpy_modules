import { fileURLToPath } from 'node:url';

import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';

/**
 * The images console, end to end: create a collection, upload two JPEGs, see
 * the thumbnails (the pipeline runs eagerly in e2e), open the viewer, then share
 * the collection with a second user who can open it.
 *
 * Standalone: it seeds its own collection and user, and relies on no settings
 * beyond the suite's (`start-test-server.sh`).
 */

const fixture = (name: string) =>
  fileURLToPath(new URL(`../../modules/images/tests/fixtures/${name}`, import.meta.url));
const JPEGS = [fixture('rotated.jpg'), fixture('geotagged.jpg')];

async function createUser(admin: Page, permissions: string[]) {
  const email = `images-e2e-${Date.now().toString(36)}@example.com`;
  const password = 'changeme1';
  const created = await admin.request.post('/api/users/admin', {
    headers: { 'content-type': 'application/json' },
    data: { email, password, role_names: [] },
  });
  expect(created.status(), await created.text()).toBe(201);
  const users = (await (await admin.request.get('/api/users/admin?per_page=100')).json()) as {
    id: string;
    email: string;
  }[];
  const id = users.find((u) => u.email === email)?.id;
  expect(id, 'the user just created should be listed').toBeTruthy();
  const granted = await admin.request.put(`/api/permissions/users/${id}`, {
    headers: { 'content-type': 'application/json' },
    data: { permissions },
  });
  expect(granted.status(), await granted.text()).toBe(200);
  return { email, password };
}

async function thumbsLoaded(page: Page, count: number) {
  const tiles = page.getByTestId('images-gallery-tile');
  await expect(tiles).toHaveCount(count);
  for (let i = 0; i < count; i++) {
    const img = tiles.nth(i).locator('img');
    await expect(img).toBeVisible({ timeout: 20_000 });
    await expect
      .poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0))
      .toBe(true);
  }
}

test('create a collection, upload two images, view one and share the collection', async ({
  page,
  browser,
}) => {
  await login(page);
  const sam = await createUser(page, ['images.view']);

  // Create.
  const name = `Trees ${Date.now().toString(36)}`;
  await page.goto('/admin/images/');
  await page.getByTestId('images-new-collection').click();
  await page.getByLabel('Name').fill(name);
  await page.getByRole('button', { name: 'Create collection' }).click();
  await page.waitForURL(/\/admin\/images\/[0-9a-f-]{36}$/);
  const collectionUrl = new URL(page.url()).pathname;
  await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible();
  await expect(page.getByText('This collection has no images yet.')).toBeVisible();

  // Upload two JPEGs; the default pipeline (exif, renditions) makes the thumbnails.
  await page.getByTestId('images-upload-input').setInputFiles(JPEGS);
  await thumbsLoaded(page, 2);
  await expect(page.getByText('2 images')).toBeVisible();

  // Open the viewer: the display copy, the original on request, metadata.
  await page.getByTestId('images-gallery-tile').first().click();
  await page.waitForURL(/\/admin\/images\/images\//);
  const viewer = page.getByTestId('images-viewer-image');
  await expect(viewer).toHaveAttribute('data-source', 'display');
  await expect
    .poll(() => viewer.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0))
    .toBe(true);
  await page.getByTestId('images-original-toggle').click();
  await expect(viewer).toHaveAttribute('data-source', 'original');
  await expect
    .poll(() => viewer.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0))
    .toBe(true);
  await expect(page.getByTestId('images-meta')).toContainText('.jpg');

  // Share with the second user.
  await page.goto(collectionUrl);
  await page.getByTestId('images-share').click();
  const dialog = page.getByTestId('images-share-dialog');
  await dialog.getByLabel('Find a person').fill(sam.email);
  const candidate = dialog.getByTestId('images-share-candidate').filter({ hasText: sam.email });
  await expect(candidate).toBeVisible();
  await candidate.getByRole('button', { name: 'Share' }).click();
  await expect(dialog.getByTestId('images-share-row')).toContainText(sam.email);
  await expect(candidate).toHaveCount(0);

  // The second user opens the collection and sees both thumbnails; has no
  // upload, share or delete controls.
  const other = await (await browser.newContext()).newPage();
  try {
    await login(other, sam);
    await other.goto('/admin/images/');
    await other.getByTestId('images-collection-filter-shared').click();
    await expect(
      other.getByTestId('images-collection-card').filter({ hasText: name }),
    ).toBeVisible();
    await other.goto(collectionUrl);
    await thumbsLoaded(other, 2);
    await expect(other.getByTestId('images-upload')).toHaveCount(0);
    await expect(other.getByTestId('images-share')).toHaveCount(0);

    // Revoke: the second user can no longer open it.
    await dialog.getByRole('button', { name: /Remove access/ }).click();
    await expect(dialog.getByTestId('images-share-row')).toHaveCount(0);
    const gone = await other.goto(collectionUrl);
    expect(gone?.status()).toBe(404);
  } finally {
    await other.context().close();
  }
});
