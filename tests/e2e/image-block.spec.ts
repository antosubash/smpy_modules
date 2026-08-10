/**
 * E2E coverage for the Image block + media picker.
 *
 * Page + block scaffolding goes through the JSON admin API to keep
 * tests independent of Puck's drag-and-drop, which is implemented with
 * dnd-kit and flaky under Playwright. The picker UI itself is driven
 * through the real React surface.
 */

import { fileURLToPath } from 'node:url';

import { expect, type Page, test } from '@playwright/test';

import { clickAndConfirm, csrfHeader, login, publishWithNote, uniqueSlug } from './helpers';

const FIXTURE_PATH = fileURLToPath(new URL('./fixtures/hero-1024x768.png', import.meta.url));

async function createPageWithImage(page: Page, title: string, slug: string): Promise<number> {
  const headers = await csrfHeader(page);
  // Empty-src Image block — picker will be exercised by the test.
  const draftData = {
    root: { props: { title } },
    content: [
      {
        type: 'Image',
        props: {
          id: 'Image-test',
          src: '',
          alt: '',
          altKind: 'meaningful',
          width: null,
          height: null,
          objectFit: 'cover',
          srcset: '',
          sizes: '',
        },
      },
    ],
  };
  const res = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: { title, slug, draft_data: draftData },
  });
  expect(res.status(), await res.text()).toBe(201);
  const body = await res.json();
  return body.id as number;
}

/**
 * Select a block so the inspector renders its fields.
 *
 * Puck 0.21 put the outline behind a left-hand navigation rail, so the block
 * palette and the outline no longer render at the same time. Clicking a block
 * name without switching first lands on the palette entry of the same name,
 * which selects nothing and leaves the inspector showing the page root.
 */
async function selectBlockFromOutline(page: Page, name: string): Promise<void> {
  await page.getByRole('navigation').getByText('Outline', { exact: true }).click();
  await page.getByRole('button', { name }).last().click();
}

/**
 * Wipe every page + media asset before each test so flakiness from a
 * previously-failed run doesn't cascade.
 */
async function clearPagebuilderState(page: Page): Promise<void> {
  const headers = await csrfHeader(page);
  const [pages, uploads] = await Promise.all([
    page.request.get('/api/pagebuilder/pages').then((r) => r.json()),
    page.request.get('/api/pagebuilder/uploads').then((r) => r.json()),
  ]);
  await Promise.all([
    ...(pages.items as Array<{ id: number }>).map((p) =>
      page.request.delete(`/api/pagebuilder/pages/${p.id}`, { headers }),
    ),
    ...(uploads.items as Array<{ id: number }>).map((a) =>
      page.request.delete(`/api/pagebuilder/uploads/${a.id}`, { headers }),
    ),
  ]);
}

test.describe('Image block + media picker', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await clearPagebuilderState(page);
  });

  test('Media library shows dimensions and Copy URL after upload', async ({ page }) => {
    await page.goto('/pagebuilder/media');
    await expect(page.getByRole('heading', { name: 'Media library' })).toBeVisible();

    await page.setInputFiles('input[type="file"]', FIXTURE_PATH);

    const card = page.locator('li', { hasText: 'hero-1024x768.png' });
    await expect(card).toBeVisible();
    await expect(card.getByText('1024×768')).toBeVisible();
    await expect(card.getByRole('button', { name: /copy url/i })).toBeVisible();
    await expect(card.getByRole('button', { name: /^delete$/i })).toBeVisible();

    // Confirm the API now reports the variants this card is built from.
    const list = await page.request.get('/api/pagebuilder/uploads');
    expect(list.ok()).toBeTruthy();
    const { items } = await list.json();
    const asset = items.find(
      (a: { original_filename: string }) => a.original_filename === 'hero-1024x768.png',
    );
    expect(asset).toBeTruthy();
    expect(asset.width).toBe(1024);
    expect(asset.height).toBe(768);
    // 1024px source → only 320 / 640 webp thumbnails fit "below source"
    // (1280 / 1920 would be upscales and our pipeline skips those).
    expect(Object.keys(asset.variants).sort()).toEqual(['w320', 'w640']);

    // Cleanup so we leave a clean slate.
    await clickAndConfirm(page, card.getByRole('button', { name: /^delete$/i }));
    await expect(card).toHaveCount(0);
  });

  test('picker auto-fills src, srcset, width, height on selection', async ({ page }) => {
    const slug = uniqueSlug('img-picker');

    // 1) Seed an asset via the upload UI.
    await page.goto('/pagebuilder/media');
    await page.setInputFiles('input[type="file"]', FIXTURE_PATH);
    await expect(page.locator('li', { hasText: 'hero-1024x768.png' })).toBeVisible();

    // 2) Create a page that already contains an empty Image block so we
    //    skip the brittle drag-and-drop step.
    const pageId = await createPageWithImage(page, `Picker page ${slug}`, slug);

    // 3) Open the editor and select the Image from the outline so the
    //    inspector renders the custom picker field.
    await page.goto(`/pagebuilder/${pageId}/edit`);
    await selectBlockFromOutline(page, 'Image');

    const srcInput = page.getByRole('textbox', { name: 'Pick from library or paste a URL' });
    await expect(srcInput).toBeVisible();
    await expect(srcInput).toHaveValue('');
    // Derived fields are empty before the pick.
    await expect(page.getByRole('spinbutton', { name: 'width' })).toHaveValue('');
    await expect(page.getByRole('textbox', { name: 'srcset' })).toHaveValue('');

    // 4) Open picker and click the asset.
    await page.getByRole('button', { name: /browse media/i }).click();
    const dialog = page.getByRole('dialog', { name: /media library picker/i });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: /hero-1024x768\.png/ }).click();

    // 5) Dialog closes; resolveData back-fills metadata.
    await expect(dialog).toHaveCount(0);
    await expect(srcInput).toHaveValue(/\/media\/pagebuilder\/.+\.png$/);
    await expect(page.getByRole('spinbutton', { name: 'width' })).toHaveValue('1024');
    await expect(page.getByRole('spinbutton', { name: 'height' })).toHaveValue('768');

    const srcset = page.getByRole('textbox', { name: 'srcset' });
    await expect(srcset).toContainText('320w');
    await expect(srcset).toContainText('640w');
    await expect(srcset).toContainText('.webp');

    await expect(page.getByRole('textbox', { name: 'sizes' })).toHaveValue(/.+/);
    // Default alt seeded from filename stem when empty.
    await expect(page.getByRole('textbox', { name: 'alt' })).toHaveValue('hero-1024x768');

    // 6) Save + publish so the public viewer carries the same metadata.
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page.getByText('Draft saved.')).toBeVisible();
    await publishWithNote(page);
    await expect(page.getByText('Published.')).toBeVisible();

    // 7) Public view: assert the rendered `<img>` has every responsive
    //    attribute we care about and the browser actually loaded a
    //    variant (currentSrc points at a `.webp`).
    await page.goto(`/p/${slug}`);
    // Scoped to <main>: a bare `img` locator also matches the site layout's
    // header logo, footer logo and partner strip, which every published page
    // carries once a layout is seeded.
    const img = page.locator('main img');
    await expect(img).toBeVisible();
    await expect(img).toHaveAttribute('loading', 'lazy');
    await expect(img).toHaveAttribute('decoding', 'async');
    await expect(img).toHaveAttribute('width', '1024');
    await expect(img).toHaveAttribute('height', '768');
    await expect(img).toHaveAttribute('srcset', /\.webp \d+w/);
    const currentSrc = await img.evaluate((el) => (el as HTMLImageElement).currentSrc);
    expect(currentSrc).toMatch(/\.webp$/);

    // 8) Cleanup.
    await page.goto('/pagebuilder/');
    await clickAndConfirm(
      page,
      page
        .locator('tr', { hasText: `Picker page ${slug}` })
        .getByRole('button', { name: /^delete$/i }),
    );
    await page.goto('/pagebuilder/media');
    await clickAndConfirm(
      page,
      page
        .locator('li', { hasText: 'hero-1024x768.png' })
        .getByRole('button', { name: /^delete$/i }),
    );
  });

  test('a caption typed in the inspector reaches the published page', async ({ page }) => {
    const slug = uniqueSlug('img-caption');
    const pageId = await createPageWithImage(page, `Caption page ${slug}`, slug);

    await page.goto(`/pagebuilder/${pageId}/edit`);
    await selectBlockFromOutline(page, 'Image');

    // An external URL keeps this test off the upload pipeline — the caption
    // is what's under test, and it renders whatever the src resolves to.
    await page
      .getByRole('textbox', { name: 'Pick from library or paste a URL' })
      .fill('https://example.com/external.png');
    await page.getByRole('textbox', { name: 'alt' }).fill('An external image');
    await page.getByRole('textbox', { name: 'Caption' }).fill('Caption goes here');
    // Blur so the last field commits into Puck state before saving.
    await page.getByRole('textbox', { name: 'alt' }).click();

    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page.getByText('Draft saved.')).toBeVisible();
    await publishWithNote(page);
    await expect(page.getByText('Published.')).toBeVisible();

    await page.goto(`/p/${slug}`);
    await expect(page.locator('main figure figcaption')).toHaveText('Caption goes here');
    // alt describes the image to a screen reader, caption is visible prose —
    // neither may stand in for the other.
    await expect(page.locator('main figure img')).toHaveAttribute('alt', 'An external image');

    // Cleanup.
    await page.goto('/pagebuilder/');
    await clickAndConfirm(
      page,
      page
        .locator('tr', { hasText: `Caption page ${slug}` })
        .getByRole('button', { name: /^delete$/i }),
    );
  });

  test('picker fallback: manually typed URLs are accepted without auto-fill', async ({ page }) => {
    const slug = uniqueSlug('img-manual');
    const pageId = await createPageWithImage(page, `Manual page ${slug}`, slug);

    await page.goto(`/pagebuilder/${pageId}/edit`);
    await selectBlockFromOutline(page, 'Image');

    // Type an arbitrary external URL — picker should respect it and
    // `resolveData` must NOT clobber siblings since the URL doesn't
    // match a /media/pagebuilder/ asset.
    const srcInput = page.getByRole('textbox', { name: 'Pick from library or paste a URL' });
    await srcInput.fill('https://example.com/external.png');
    // Blur to commit the value into Puck state.
    await page.getByRole('textbox', { name: 'alt' }).click();
    await page.getByRole('textbox', { name: 'alt' }).fill('External image');

    await expect(srcInput).toHaveValue('https://example.com/external.png');
    await expect(page.getByRole('spinbutton', { name: 'width' })).toHaveValue('');
    await expect(page.getByRole('textbox', { name: 'srcset' })).toHaveValue('');

    // Cleanup.
    await page.goto('/pagebuilder/');
    await clickAndConfirm(
      page,
      page
        .locator('tr', { hasText: `Manual page ${slug}` })
        .getByRole('button', { name: /^delete$/i }),
    );
  });
});
