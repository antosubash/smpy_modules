import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * The header and footer are one site-wide record, not per-page content, so
 * nothing on a page can assert they exist — a published page rendered fine
 * with no chrome at all, which is exactly how they went missing.
 *
 * These specs pin the layout round-trip: what the layout API stores is what
 * /p/{slug} renders around the page.
 */

const HEADER = {
  root: { props: {} },
  zones: {},
  content: [
    {
      type: 'SiteHeader',
      props: {
        id: 'hdr',
        logoUrl: '',
        logoAlt: 'E2E Site',
        homeHref: '/p/home',
        utilityLinks: [{ label: 'Mailing list', href: '/p/contact', icon: '' }],
        navItems: [
          { label: 'Atlas', href: '/p/atlas', children: [] },
          {
            label: 'The project',
            href: '',
            children: [{ label: 'Our process', href: '/p/our-process' }],
          },
        ],
        ctaLabel: 'Contact us',
        ctaHref: '/p/contact',
        sticky: true,
      },
    },
  ],
};

const FOOTER = {
  root: { props: {} },
  zones: {},
  content: [
    {
      type: 'SiteFooter',
      props: {
        id: 'ftr',
        logoUrl: '',
        logoAlt: 'E2E Site',
        homeHref: '/p/home',
        links: [{ label: 'Privacy notice', href: '/p/privacy' }],
        note: 'A small print line.',
      },
    },
  ],
};

async function putLayout(page: Page, header: unknown, footer: unknown) {
  const response = await page.request.put('/api/pagebuilder/layout', {
    headers: await csrfHeader(page),
    data: { header_data: header, footer_data: footer, note: 'e2e chrome' },
  });
  expect(response.ok(), 'layout PUT').toBeTruthy();
}

/** Publish a trivial page and return its public path. */
async function publishPage(page: Page): Promise<string> {
  const slug = uniqueSlug('e2e-chrome');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers: await csrfHeader(page),
    data: {
      title: 'Chrome',
      slug,
      draft_data: {
        root: { props: { title: 'Chrome', width: 'full' } },
        content: [
          { type: 'Heading', props: { id: 'h', text: 'Page body', level: 'h1', align: 'left' } },
        ],
        zones: {},
      },
    },
  });
  expect(created.ok()).toBeTruthy();
  const { id } = await created.json();
  const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
    headers: await csrfHeader(page),
    data: { note: 'chrome' },
  });
  expect(published.ok()).toBeTruthy();
  return `/p/${slug}`;
}

test.describe('Site header and footer', () => {
  // The layout is a single shared record — parallel specs would overwrite
  // each other's header mid-assertion.
  test.describe.configure({ mode: 'serial' });

  let publicPath: string;

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await login(page);
    // The pack is site-wide now, so the "pack reaches the chrome" spec below
    // needs branding to have selected one.
    await page.goto('/admin/branding/');
    await page.request.put('/api/branding/', { data: { design_pack: 'gca' } });
    publicPath = await publishPage(page);
    await page.close();
  });

  test('a published page renders the layout header and footer', async ({ page }) => {
    await login(page);
    await putLayout(page, HEADER, FOOTER);
    await page.goto(publicPath);

    const header = page.getByTestId('site-header');
    const footer = page.getByTestId('site-footer');
    await expect(header).toBeVisible();
    await expect(footer).toBeVisible();

    await expect(header.getByRole('link', { name: 'Atlas' })).toBeVisible();
    await expect(header.getByRole('link', { name: 'Contact us' })).toBeVisible();
    await expect(header.getByRole('link', { name: 'Mailing list' })).toBeVisible();
    await expect(footer.getByRole('link', { name: 'Privacy notice' })).toBeVisible();
    await expect(footer.getByText('A small print line.')).toBeVisible();

    // The page's own body still renders between them.
    await expect(page.getByRole('heading', { name: 'Page body' })).toBeVisible();
  });

  test('a nav group opens its dropdown on hover', async ({ page }) => {
    await login(page);
    await putLayout(page, HEADER, FOOTER);
    await page.goto(publicPath);

    // Located by CSS, not by role: the closed panel is `visibility: hidden`, so
    // its links are out of the accessibility tree and getByRole can't see them
    // until it opens — which is the state this asserts on either side of.
    const child = page.locator('[data-testid="site-header"] a', { hasText: 'Our process' });
    await expect(child).toBeAttached();
    await expect(child).toBeHidden();

    await page.getByRole('button', { name: 'The project' }).hover();
    await expect(child).toBeVisible();
  });

  test('the header sticks to the top of the page when asked', async ({ page }) => {
    await login(page);
    await putLayout(page, HEADER, FOOTER);
    await page.goto(publicPath);

    // The widget can't be the sticky element — its wrapper is — so this asserts
    // on the wrapper, which is what the widgets-base `:has()` rule targets.
    await expect(page.getByTestId('site-header')).toHaveCSS('position', 'sticky');

    const off = JSON.parse(JSON.stringify(HEADER));
    off.content[0].props.sticky = false;
    await putLayout(page, off, FOOTER);
    // Cache-busted: the public page ships `max-age=60`, so re-visiting the same
    // URL inside a test run is served from the browser cache without ever
    // asking the server — the ETag covers the layout, but nothing revalidates
    // it. A real visitor sees the change once the TTL lapses.
    await page.goto(`${publicPath}?cb=sticky-off`);
    await expect(page.getByTestId('site-header')).toHaveCSS('position', 'static');
  });

  test('the design pack reaches the chrome, not just the page body', async ({ page }) => {
    await login(page);
    await putLayout(page, HEADER, FOOTER);
    await page.goto(publicPath);

    // The pack's CSS is scoped to its root class, which the *page* root renders
    // inside <main>. Without hoisting it the chrome would silently fall back to
    // the base tokens and read as a different site.
    await expect(
      page.getByTestId('site-header').locator('xpath=ancestor::*[@class="gca-root"]'),
    ).toHaveCount(1);
  });

  test('the site chrome widgets are offered in the layout editor only', async ({ page }) => {
    await login(page);

    await page.goto('/pagebuilder/layout');
    const chrome = page.locator('[class*="DrawerItem-name"]').filter({ hasText: 'Site header' });
    await expect(chrome.first()).toBeAttached();

    // A nav bar dropped mid-page would render a second one under the real
    // header, so it must not be in the page palette.
    await page.goto('/pagebuilder/new');
    await expect(
      page.locator('[class*="DrawerItem-name"]').filter({ hasText: 'Site header' }),
    ).toHaveCount(0);
  });
});
