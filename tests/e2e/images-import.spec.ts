import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';

import { login } from './helpers';

/**
 * The import wizard, end to end: a GeoJSON of three features that embed their
 * images as base64 is previewed, mapped from the suggestions and imported; the
 * job ends `completed` and the collection holds three located images.
 *
 * Standalone: it creates its own collection and relies on no settings beyond
 * the suite's (`start-test-server.sh`); the import runs eagerly in e2e.
 */

const fixture = (name: string) =>
  readFileSync(
    fileURLToPath(new URL(`../../modules/images/tests/fixtures/${name}`, import.meta.url)),
  ).toString('base64');

const FEATURES = ['rotated.jpg', 'geotagged.jpg', 'zero_gps.jpg'].map((name, i) => ({
  type: 'Feature',
  properties: { image: fixture(name), site: `P${i + 1}` },
  geometry: { type: 'Point', coordinates: [8.5 + i * 0.01, 47.3 + i * 0.01] },
}));
const GEOJSON = JSON.stringify({ type: 'FeatureCollection', features: FEATURES });

test('import three embedded images from a GeoJSON file', async ({ page }) => {
  await login(page);

  const name = `Import ${Date.now().toString(36)}`;
  await page.goto('/admin/images/');
  await page.getByTestId('images-new-collection').click();
  await page.getByLabel('Name').fill(name);
  await page.getByRole('button', { name: 'Create collection' }).click();
  await page.waitForURL(/\/admin\/images\/[0-9a-f-]{36}$/);
  const collectionId = new URL(page.url()).pathname.split('/').pop();

  await page.getByTestId('images-tab-imports').click();
  await expect(page.getByTestId('images-imports-empty')).toBeVisible();
  await page.getByTestId('images-import-new').click();
  await page.getByTestId('images-import-file').setInputFiles({
    name: 'trees.geojson',
    mimeType: 'application/geo+json',
    buffer: Buffer.from(GEOJSON),
  });

  // The preview counts the features and suggests the image property.
  await expect(page.getByTestId('images-import-preview')).toContainText('3 features');
  await expect(page.getByTestId('images-import-kind')).toHaveValue('geojson_base64');
  await expect(page.getByTestId('images-map-image_prop')).toHaveValue('image');
  await page.getByTestId('images-import-submit').click();

  const job = page.getByTestId('images-import-job');
  await expect(job).toHaveCount(1);
  await expect(job.getByTestId('images-import-status')).toHaveText('Completed', {
    timeout: 30_000,
  });
  await expect(job.getByTestId('images-import-progress')).toContainText(
    '3 added, 0 duplicates, 0 failed',
  );

  // Three images, each located from its feature's geometry.
  const listed = await page.request.get(
    `/api/images/collections/${collectionId}/images?has_location=true`,
  );
  expect(listed.status()).toBe(200);
  const body = (await listed.json()) as { items: { lat: number | null; lng: number | null }[] };
  expect(body.items).toHaveLength(3);
  for (const item of body.items) {
    expect(item.lat).not.toBeNull();
    expect(item.lng).not.toBeNull();
  }

  await page.getByTestId('images-tab-gallery').click();
  await expect(page.getByTestId('images-gallery-tile')).toHaveCount(3);
});
