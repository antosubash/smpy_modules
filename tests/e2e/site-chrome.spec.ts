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

  test('a page flagged for the nav joins the header and footer', async ({ page }) => {
    await login(page);
    await putLayout(page, HEADER, FOOTER);
    const slug = uniqueSlug('e2e-flagged');
    const title = `Flagged ${slug.slice(-6)}`;
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers: await csrfHeader(page),
      data: {
        title,
        slug,
        meta_title: `${title} | Search title`,
        show_in_header_nav: true,
        show_in_footer: true,
        draft_data: { root: { props: {} }, content: [], zones: {} },
      },
    });
    expect(created.ok()).toBeTruthy();
    const { id } = await created.json();
    const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
      headers: await csrfHeader(page),
      data: {},
    });
    expect(published.ok()).toBeTruthy();

    try {
      await page.goto(`${publicPath}?cb=${slug}`);
      // After the layout's own entries, linking to the page's public address.
      const headerLink = page
        .getByTestId('site-header')
        .getByRole('navigation')
        .first()
        .getByRole('link', { name: title });
      await expect(headerLink).toHaveAttribute('href', `/p/${slug}`);
      await expect(
        page.getByTestId('site-footer').getByRole('link', { name: title }),
      ).toBeVisible();

      // Its own page is titled with the SEO title, not the page title.
      await page.goto(`/p/${slug}`);
      await expect(page).toHaveTitle(new RegExp(`^${title} \\| Search title`));
    } finally {
      await page.request.delete(`/api/pagebuilder/pages/${id}`, {
        headers: await csrfHeader(page),
      });
    }
  });

  test('the mobile menu closes on Escape and both header controls have 44px targets', async ({
    page,
  }) => {
    await login(page);
    const headerWithSwitcher = structuredClone(HEADER);
    headerWithSwitcher.content[0].props.showLocaleSwitcher = true;
    await putLayout(page, headerWithSwitcher, FOOTER);
    try {
      for (const width of [390, 320]) {
        await page.setViewportSize({ width, height: 800 });
        await page.goto(`${publicPath}?cb=mobile-${width}`);
        const header = page.getByTestId('site-header');
        const menu = header.locator('button[aria-controls]');
        const locale = header.getByRole('button', { name: 'Change language' });
        for (const control of [menu, locale]) {
          const box = await control.boundingBox();
          expect(box?.width).toBeGreaterThanOrEqual(44);
          expect(box?.height).toBeGreaterThanOrEqual(44);
        }

        await menu.click();
        const mobileNav = header.getByRole('navigation', { name: 'Main' });
        await expect(menu).toHaveAttribute('aria-expanded', 'true');
        await mobileNav.getByRole('link', { name: 'Atlas' }).focus();
        await page.keyboard.press('Escape');
        await expect(mobileNav).toHaveCount(0);
        await expect(menu).toHaveAttribute('aria-expanded', 'false');
        await expect(menu).toBeFocused();
      }
    } finally {
      await putLayout(page, HEADER, FOOTER);
    }
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
