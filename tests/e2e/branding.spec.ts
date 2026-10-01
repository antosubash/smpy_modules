import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * The public page has no layout, so nothing mounts BrandingHead for it unless
 * PublicPage does. When it didn't, Settings → Branding stopped at the sign-in
 * wall: the admin shell re-themed and the public site kept the framework's
 * default colour. Nothing failed — the page just quietly ignored the brand.
 *
 * These specs pin the whole chain: the branding API writes `--primary` and the
 * widgets read it through `--pb-accent`.
 */

/**
 * Navigate to a public page and wait for the page body to render.
 *
 * Inertia renders client-side, so `goto` resolves before React has mounted
 * anything — reading a computed style straight after it hits a bare document
 * and throws. Every read below goes through here.
 */
let visit = 0;
async function gotoPublic(page: Page, path: string) {
  // Unique query per visit: the branding value is baked into the
  // server-rendered HTML and the public page ships `max-age=60`, so re-visiting
  // the same URL after a colour change can be served from cache.
  visit += 1;
  await page.goto(`${path}?cb=${visit}`);
  await page.getByRole('heading', { name: 'Tokens follow branding' }).waitFor();
}

/** Read a resolved custom property off the document root. */
async function rootVar(page: Page, name: string): Promise<string> {
  return page.evaluate(
    (prop) => getComputedStyle(document.documentElement).getPropertyValue(prop).trim(),
    name,
  );
}

async function setBrandColor(page: Page, color: string) {
  await page.goto('/branding');
  const cookies = await page.context().cookies();
  const token = cookies.find((c) => c.name === 'branding_csrf')?.value;
  const response = await page.request.put('/api/branding/', {
    headers: token ? { 'X-CSRF-Token': decodeURIComponent(token) } : {},
    data: { primary_color: color },
  });
  expect(response.ok(), `branding PUT ${color}`).toBeTruthy();
}

/** Publish a one-widget page and return its public path. */
async function seedPage(page: Page): Promise<string> {
  const slug = uniqueSlug('e2e-brand');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers: await csrfHeader(page),
    data: {
      title: 'Branding',
      slug,
      draft_data: {
        root: { props: { title: 'Branding', width: 'full' } },
        content: [
          {
            type: 'EyebrowSection',
            props: {
              id: 'es',
              eyebrow: 'Brand',
              heading: 'Tokens follow branding',
              body: 'Body copy.',
            },
          },
        ],
        zones: {},
      },
    },
  });
  expect(created.ok()).toBeTruthy();
  const { id } = await created.json();
  const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
    headers: await csrfHeader(page),
    data: { note: 'branding' },
  });
  expect(published.ok()).toBeTruthy();
  return `/p/${slug}`;
}

test.describe('Branding drives the widget tokens', () => {
  // Branding is a single global setting, so these must not run concurrently
  // against a shared host — one spec's colour would leak into another's read.
  test.describe.configure({ mode: 'serial' });

  let publicPath: string;
  let original: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await login(page);
    const current = await page.request.get('/api/branding/', {
      headers: { Accept: 'application/json' },
    });
    original = (await current.json()).primary_color ?? '';
    publicPath = await seedPage(page);
    await page.close();
  });

  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    await login(page);
    await setBrandColor(page, original);
    await page.close();
  });

  test('the configured colour reaches the public page', async ({ page }) => {
    await login(page);
    await setBrandColor(page, '#b3261e');
    await gotoPublic(page, publicPath);

    // BrandingHead writes the ramp inline on :root...
    await expect
      .poll(() => page.evaluate(() => document.documentElement.style.getPropertyValue('--primary')))
      .toBe('#b3261e');
    // ...and the widgets read it through the shared accent token.
    expect(await rootVar(page, '--pb-accent')).toBe('#b3261e');
  });

  test('re-branding re-themes an already-published page', async ({ page }) => {
    await login(page);
    await setBrandColor(page, '#4527a0');
    await gotoPublic(page, publicPath);

    await expect.poll(() => rootVar(page, '--pb-accent')).toBe('#4527a0');
  });
});
