import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * The design pack is a branding setting, not a page property: one site, one
 * look. It used to be a radio on the page root, which meant the site's identity
 * was scattered across every page's stored content and the header and footer —
 * rendered outside the page root — never got it at all.
 *
 * These pin the replacement: what Settings → Branding selects is what the
 * public site wears, without touching page content.
 */

async function setPack(page: Page, pack: string) {
  await page.goto('/branding/');
  const response = await page.request.put('/api/branding/', { data: { design_pack: pack } });
  expect(response.ok(), `branding PUT design_pack=${pack}`).toBeTruthy();
}

test.describe('Design pack comes from branding', () => {
  // Branding is one global setting — parallel specs would fight over it.
  test.describe.configure({ mode: 'serial' });

  let publicPath: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await login(page);
    const slug = uniqueSlug('e2e-pack');
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers: await csrfHeader(page),
      data: {
        title: 'Pack',
        slug,
        draft_data: {
          // No designPack here — that is the whole point.
          root: { props: { title: 'Pack', width: 'full' } },
          content: [
            { type: 'Heading', props: { id: 'h', text: 'Pack body', level: 'h1', align: 'left' } },
          ],
          zones: {},
        },
      },
    });
    expect(created.ok()).toBeTruthy();
    const { id } = await created.json();
    const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
      headers: await csrfHeader(page),
      data: { note: 'pack' },
    });
    expect(published.ok()).toBeTruthy();
    publicPath = `/p/${slug}`;
    await page.close();
  });

  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    await login(page);
    await setPack(page, 'gca');
    await page.close();
  });

  test('selecting a pack wraps the whole public document in its root class', async ({ page }) => {
    await login(page);
    await setPack(page, 'gca');
    // Cache-busted: the public page ships `max-age=60`, so re-visiting the
    // same URL after a settings change can be served from the browser cache.
    await page.goto(`${publicPath}?cb=on`);

    await expect(page.locator('.gca-root')).toHaveCount(1);
    // Around everything, not just the body — this is what lets the header and
    // footer adopt the pack.
    await expect(page.locator('.gca-root main')).toHaveCount(1);
  });

  test('clearing the pack returns the site to the base tokens', async ({ page }) => {
    await login(page);
    await setPack(page, '');
    await page.goto(`${publicPath}?cb=off`);

    await expect(page.getByRole('heading', { name: 'Pack body' })).toBeVisible();
    await expect(page.locator('.gca-root')).toHaveCount(0);
  });

  test('the pack survives in the page content across a re-theme', async ({ page }) => {
    // Switching the pack must not rewrite stored page data — that was the
    // failure mode of holding it on the page root.
    await login(page);
    await setPack(page, 'gca');
    const listed = await page.request.get('/api/pagebuilder/pages', {
      headers: { Accept: 'application/json' },
    });
    const slug = publicPath.replace('/p/', '');
    const match = (await listed.json()).items.find((item: { slug: string }) => item.slug === slug);
    const detail = await page.request.get(`/api/pagebuilder/pages/${match.id}`, {
      headers: { Accept: 'application/json' },
    });
    const root = (await detail.json()).draft_data.root.props;
    expect(root).not.toHaveProperty('designPack');
    expect(root.width).toBe('full');
  });

  test('the branding page offers the installed packs', async ({ page }) => {
    await login(page);
    await page.goto('/branding/');
    const select = page.locator('#design_pack');
    await expect(select).toBeVisible();
    // canopy_atlas registers this one; the empty option is the base look.
    await expect(select.locator('option')).toHaveText([/None/, 'Canopy Atlas']);
  });
});
