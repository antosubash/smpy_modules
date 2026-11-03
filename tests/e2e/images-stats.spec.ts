import { fileURLToPath } from 'node:url';

import { type Browser, expect, type Page, test } from '@playwright/test';

import { login, moduleCsrfHeader, uniqueSlug } from './helpers';

/**
 * The ImageStats block: live counts of the images in public collections.
 *
 * Standalone: it seeds its own collections and pages. The per-collection count
 * is exact; the all-collections total also counts whatever other spec files
 * left public, so those assertions are relative to a reading taken first (the
 * suite runs one worker, so nothing moves it in between).
 */

const BLOCK = 'Live image numbers';
const LABEL = 'Photos';

const fixture = (name: string) =>
  fileURLToPath(new URL(`../../modules/images/tests/fixtures/${name}`, import.meta.url));

type Csrf = Record<string, string>;

async function createCollection(
  page: Page,
  csrf: Csrf,
  visibility: 'public' | 'private',
): Promise<{ id: string; slug: string }> {
  const created = await page.request.post('/api/images/collections', {
    headers: { ...csrf, 'content-type': 'application/json' },
    data: { name: `Stats ${uniqueSlug('c')}`, visibility },
  });
  expect(created.status(), await created.text()).toBe(201);
  return (await created.json()) as { id: string; slug: string };
}

/** Upload through the console (eager tasks process them inline) and wait for the tiles. */
async function upload(page: Page, id: string, files: string[], tiles: number) {
  await page.goto(`/admin/images/${id}`);
  await page.getByTestId('images-upload-input').setInputFiles(files);
  await expect(page.getByTestId('images-gallery-tile')).toHaveCount(tiles);
}

async function setVisibility(page: Page, csrf: Csrf, id: string, visibility: string) {
  const done = await page.request.put(`/api/images/collections/${id}/visibility`, {
    headers: { ...csrf, 'content-type': 'application/json' },
    data: { visibility },
  });
  expect(done.status(), await done.text()).toBe(200);
}

async function publicTotal(page: Page, metric: string): Promise<number> {
  const response = await page.request.get(`/api/images/public/stats?metric=${metric}`);
  expect(response.status(), await response.text()).toBe(200);
  return ((await response.json()) as { value: number }).value;
}

async function publishStatsPage(page: Page, collection: string): Promise<string> {
  const headers = await moduleCsrfHeader(page, '/pagebuilder/');
  const slug = uniqueSlug('e2e-images-stats');
  const item = (metric: string, label: string, coll: string) => ({
    metric,
    collection: coll,
    label,
    prefix: '',
    suffix: '',
  });
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title: 'Image numbers',
      slug,
      draft_data: {
        root: { props: { title: 'Image numbers', width: 'full' } },
        content: [
          {
            type: 'ImageStats',
            props: {
              id: 'ImageStats-test',
              title: 'In numbers',
              subtitle: '',
              surface: 'cards',
              items: [
                item('images', LABEL, collection),
                item('images', 'Everything', ''),
                item('collections', 'Galleries', ''),
              ],
            },
          },
        ],
      },
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  const { id } = (await created.json()) as { id: number };
  await expect
    .poll(async () => (await page.request.get(`/api/pagebuilder/pages/${id}`)).status())
    .toBe(200);
  const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, { headers });
  expect(published.status(), await published.text()).toBe(200);
  return slug;
}

/** The three numbers a first-time anonymous visitor sees. The public answers are
 *  cacheable, so a returning browser may hold old numbers by design; a fresh
 *  context has no cache, which is what a mutation is measured against. */
async function visitorSees(browser: Browser, slug: string): Promise<string[]> {
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await page.goto(`/p/${slug}`);
    const numbers = page.locator('dd');
    await expect(numbers).toHaveCount(3);
    // The dash is the loading state; wait for numbers to replace it.
    await expect(numbers.filter({ hasText: '–' })).toHaveCount(0);
    return (await numbers.allTextContents()).map((text) => text.trim());
  } finally {
    await context.close();
  }
}

test.describe('Image stats block', () => {
  test('is offered in the page palette', async ({ page }) => {
    await login(page);
    await page.goto('/pagebuilder/new');
    await expect(
      page.locator('[class*="DrawerItem-name"]').filter({ hasText: BLOCK }).first(),
    ).toBeAttached();
  });

  test('is not offered in the site-layout palette', async ({ page }) => {
    await login(page);
    await page.goto('/pagebuilder/layout');
    await expect(page.locator('[class*="DrawerItem-name"]').filter({ hasText: BLOCK })).toHaveCount(
      0,
    );
  });

  test('an anonymous visitor sees the counts, and they follow a new upload', async ({
    page,
    browser,
  }) => {
    await login(page);
    const csrf = await moduleCsrfHeader(page, '/admin/images/');
    const baseImages = await publicTotal(page, 'images');
    const baseCollections = await publicTotal(page, 'collections');

    const pub = await createCollection(page, csrf, 'public');
    await upload(page, pub.id, [fixture('rotated.jpg'), fixture('geotagged.jpg')], 2);
    const slug = await publishStatsPage(page, pub.slug);

    await expect
      .poll(() => visitorSees(browser, slug), { timeout: 20_000 })
      .toEqual(['2', String(baseImages + 2), String(baseCollections + 1)]);

    await upload(page, pub.id, [fixture('transparent.png')], 3);
    await expect
      .poll(() => visitorSees(browser, slug), { timeout: 20_000 })
      .toEqual(['3', String(baseImages + 3), String(baseCollections + 1)]);
  });

  test("a private collection's images are left out of the total", async ({ page, browser }) => {
    await login(page);
    const csrf = await moduleCsrfHeader(page, '/admin/images/');
    const pub = await createCollection(page, csrf, 'public');
    await upload(page, pub.id, [fixture('rotated.jpg')], 1);
    const slug = await publishStatsPage(page, pub.slug);

    const before = await visitorSees(browser, slug);
    const total = Number(before[1]);
    const galleries = Number(before[2]);
    expect(before[0]).toBe('1');

    const priv = await createCollection(page, csrf, 'private');
    await upload(page, priv.id, [fixture('geotagged.jpg'), fixture('zero_gps.jpg')], 2);
    await expect.poll(() => visitorSees(browser, slug), { timeout: 20_000 }).toEqual(before);

    // Once it is public its images join the total, which also proves the
    // numbers above were not stale.
    await setVisibility(page, csrf, priv.id, 'public');
    await expect
      .poll(() => visitorSees(browser, slug), { timeout: 20_000 })
      .toEqual(['1', String(total + 2), String(galleries + 1)]);
  });
});
