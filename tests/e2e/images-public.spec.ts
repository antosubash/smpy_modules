import { fileURLToPath } from 'node:url';

import { expect, type Page, test } from '@playwright/test';

import { login, moduleCsrfHeader } from './helpers';

/**
 * A public collection, end to end: create one with two geotagged images,
 * publish it, open `/images/c/<slug>` as an anonymous visitor (thumbnails load,
 * the map draws) and check the console's map tab draws the points too.
 *
 * Standalone: it seeds its own collection and relies on no settings beyond the
 * suite's (`start-test-server.sh`). The map falls back to the GeoJSON points
 * when no PMTiles archive has been built, so it does not depend on tippecanoe.
 */

const fixture = (name: string) =>
  fileURLToPath(new URL(`../../modules/images/tests/fixtures/${name}`, import.meta.url));
const JPEGS = [fixture('rotated.jpg'), fixture('geotagged.jpg')];

/** Console errors that name the map's worker or library. A map whose worker
 *  failed to start still draws an empty canvas, so the canvas alone proves
 *  nothing: this is asserted in dev and in bundle mode alike, next to a check
 *  that the seeded points are actually rendered (`data-map-features`).
 *
 *  Under `make dev` the page is on :8000 and Vite on :5050, and the dev CSP's
 *  `worker-src 'self' blob:` refuses a worker loaded from the Vite origin
 *  (Chromium: "csp" on `…/maplibre-gl-worker.mjs?worker_file&type=module`), so
 *  the module hands MapLibre a blob: worker instead. */
function mapErrors(page: Page): string[] {
  const seen: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && /worker|maplibre|pmtiles/i.test(msg.text()))
      seen.push(msg.text());
  });
  page.on('pageerror', (error) => {
    if (/worker|maplibre|pmtiles/i.test(error.message)) seen.push(error.message);
  });
  return seen;
}

/** The map drew our points: its worker ran, parsed the data and the layers rendered. */
async function drawsPoints(map: ReturnType<Page['locator']>) {
  await expect(map.locator('canvas')).toBeVisible({ timeout: 20_000 });
  await expect(map).toHaveAttribute('data-map-ready', /.+/, { timeout: 20_000 });
  await expect
    .poll(async () => Number(await map.getAttribute('data-map-features')), { timeout: 20_000 })
    .toBeGreaterThan(0);
}

async function loaded(img: ReturnType<Page['locator']>) {
  await expect(img).toBeVisible({ timeout: 20_000 });
  await expect
    .poll(() => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth > 0))
    .toBe(true);
}

test('a published collection is viewable anonymously, with thumbnails and a map', async ({
  page,
  browser,
}) => {
  await login(page);
  const csrf = await moduleCsrfHeader(page, '/admin/images/');

  // Create the collection and upload two images through the console.
  const name = `Public trees ${Date.now().toString(36)}`;
  await page.goto('/admin/images/');
  await page.getByTestId('images-new-collection').click();
  await page.getByLabel('Name').fill(name);
  await page.getByRole('button', { name: 'Create collection' }).click();
  await page.waitForURL(/\/admin\/images\/[0-9a-f-]{36}$/);
  const collectionUrl = new URL(page.url()).pathname;
  const collectionId = collectionUrl.split('/').pop() as string;
  await page.getByTestId('images-upload-input').setInputFiles(JPEGS);
  await expect(page.getByTestId('images-gallery-tile')).toHaveCount(2);

  // Both images get a location: the second one's EXIF is not relied upon.
  const listed = await page.request.get(`/api/images/collections/${collectionId}/images`);
  const items = ((await listed.json()) as { items: { id: string; lat: number | null }[] }).items;
  expect(items).toHaveLength(2);
  const places: [number, number][] = [
    [48.2, 16.37],
    [48.85, 2.35],
  ];
  for (const [i, image] of items.entries()) {
    const [lat, lng] = places[i] as [number, number];
    const moved = await page.request.patch(`/api/images/images/${image.id}`, {
      headers: { ...csrf, 'content-type': 'application/json' },
      data: { lat, lng },
    });
    expect(moved.status(), await moved.text()).toBe(200);
  }

  // Publish.
  const published = await page.request.put(`/api/images/collections/${collectionId}/visibility`, {
    headers: { ...csrf, 'content-type': 'application/json' },
    data: { visibility: 'public' },
  });
  expect(published.status(), await published.text()).toBe(200);
  const slug = ((await published.json()) as { slug: string }).slug;

  // An anonymous visitor: a fresh context with no session at all.
  const visitor = await (await browser.newContext()).newPage();
  const visitorErrors = mapErrors(visitor);
  try {
    await visitor.goto(`/images/c/${slug}`);
    await expect(visitor.getByRole('heading', { name, level: 1 })).toBeVisible();
    const tiles = visitor.getByTestId('images-public-tile');
    await expect(tiles).toHaveCount(2);
    for (let i = 0; i < 2; i++) await loaded(tiles.nth(i).locator('img'));
    // A thumbnail opens the display copy.
    await tiles.first().click();
    await loaded(visitor.getByTestId('images-lightbox-image'));
    await visitor.keyboard.press('Escape');
    await expect(visitor.getByTestId('images-lightbox')).toHaveCount(0);
    // The map draws.
    await drawsPoints(visitor.getByTestId('images-map'));
    expect(visitorErrors).toEqual([]);
  } finally {
    await visitor.context().close();
  }

  // The console's map tab draws a canvas, and a private collection is a 404 anonymously.
  const consoleErrors = mapErrors(page);
  await page.goto(collectionUrl);
  await page.getByTestId('images-tab-map').click();
  await drawsPoints(page.getByTestId('images-map'));
  expect(consoleErrors).toEqual([]);

  const hidden = await page.request.put(`/api/images/collections/${collectionId}/visibility`, {
    headers: { ...csrf, 'content-type': 'application/json' },
    data: { visibility: 'private' },
  });
  expect(hidden.status(), await hidden.text()).toBe(200);
  const gone = await (await browser.newContext()).newPage();
  try {
    expect((await gone.goto(`/images/c/${slug}`))?.status()).toBe(404);
  } finally {
    await gone.context().close();
  }
});
