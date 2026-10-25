import { expect, type Page, test } from '@playwright/test';

import { login, moduleCsrfHeader, uniqueSlug } from './helpers';

/**
 * The public viewer's frame around the happy path (#89): the branded 404 for
 * every address a visitor cannot see, the draft preview's bar, the skip link,
 * a footer that stays at the bottom of a short page, and a printout without
 * the site chrome. Standalone: it seeds its own layout and pages.
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
        logoAlt: 'Chrome site',
        homeHref: '/',
        utilityLinks: [],
        navItems: [{ label: 'Chrome nav', href: '/', children: [] }],
        ctaLabel: 'Chrome CTA',
        ctaHref: '#',
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
        logoAlt: 'Chrome site',
        homeHref: '/',
        links: [{ label: 'Chrome footer link', href: '#' }],
        note: 'Chrome small print.',
      },
    },
  ],
};

const LONG = {
  root: { props: { title: 'Long', width: 'full' } },
  zones: {},
  content: [
    { type: 'Heading', props: { id: 'h', text: 'Long page body', level: 'h1', align: 'left' } },
    ...Array.from({ length: 12 }, (_, i) => ({
      type: 'Heading',
      props: { id: `h${i}`, text: `Section ${i}`, level: 'h2', align: 'left' },
    })),
  ],
};

const EMPTY = { root: { props: { title: 'Empty' } }, content: [], zones: {} };

const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
];

async function api(page: Page, method: string, path: string, data?: unknown) {
  const response = await page.request.fetch(path, {
    method,
    headers: await moduleCsrfHeader(page, '/pagebuilder/'),
    data,
  });
  expect(response.ok(), `${method} ${path}: ${await response.text()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

async function createPage(
  page: Page,
  draft: unknown,
  { publish = true, locale }: { publish?: boolean; locale?: string } = {},
): Promise<{ id: number; slug: string }> {
  const slug = uniqueSlug('e2e-viewer');
  const { id } = await api(page, 'POST', '/api/pagebuilder/pages', {
    title: slug,
    slug,
    draft_data: draft,
    ...(locale ? { locale } : {}),
  });
  if (publish) await api(page, 'POST', `/api/pagebuilder/pages/${id}/publish`, { note: 'e2e' });
  return { id, slug };
}

test.describe('Public viewer chrome', () => {
  // The layout is one shared record; keep this file's tests in order.
  test.describe.configure({ mode: 'serial' });

  let long: { id: number; slug: string };
  let empty: { id: number; slug: string };
  let draft: { id: number; slug: string };
  let trashed: { id: number; slug: string };
  let germanDraft: { id: number; slug: string };

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await login(page);
    await api(page, 'PUT', '/api/pagebuilder/layout', {
      header_data: HEADER,
      footer_data: FOOTER,
      note: 'e2e viewer chrome',
    });
    long = await createPage(page, LONG);
    empty = await createPage(page, EMPTY);
    draft = await createPage(page, LONG, { publish: false });
    trashed = await createPage(page, LONG);
    await api(page, 'DELETE', `/api/pagebuilder/pages/${trashed.id}`);
    germanDraft = await createPage(page, LONG, { publish: false, locale: 'de' });
    await page.close();
  });

  test.afterAll(async ({ browser }) => {
    // Leave the shard's site without this file's header and footer.
    const page = await browser.newPage();
    await login(page);
    await api(page, 'PUT', '/api/pagebuilder/layout', {
      header_data: {},
      footer_data: {},
      note: 'e2e viewer chrome: reset',
    });
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('every unseen address gets the same branded 404 in the site frame', async ({ page }) => {
    const cases = [
      { path: `/p/${uniqueSlug('missing')}`, heading: "This page doesn't exist" },
      { path: `/p/${draft.slug}`, heading: "This page doesn't exist" },
      { path: `/p/${trashed.slug}`, heading: "This page doesn't exist" },
      { path: `/de/p/${uniqueSlug('fehlt')}`, heading: 'Diese Seite gibt es nicht' },
      { path: `/de/p/${germanDraft.slug}`, heading: 'Diese Seite gibt es nicht' },
    ];
    const texts = new Map<string, Set<string>>();
    for (const viewport of VIEWPORTS) {
      await page.setViewportSize(viewport);
      for (const { path, heading } of cases) {
        const response = await page.goto(path);
        expect(response?.status(), path).toBe(404);
        expect(response?.headers()['cache-control']).toContain('no-store');
        const block = page.getByTestId('public-not-found');
        await expect(block.getByRole('heading', { level: 1 })).toHaveText(heading);
        await expect(page.getByTestId('site-header')).toBeVisible();
        await expect(page.getByTestId('site-footer')).toBeVisible();
        await expect(block.getByRole('link')).toHaveAttribute('href', '/');
        // Nothing wider than the screen.
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        );
        expect(overflow, `${path} at ${viewport.width}`).toBeLessThanOrEqual(0);
        const seen = texts.get(heading) ?? new Set<string>();
        seen.add((await block.textContent()) ?? '');
        texts.set(heading, seen);
      }
    }
    // No oracle: a draft, a trashed page and a typo read exactly alike.
    for (const seen of texts.values()) expect(seen.size).toBe(1);
  });

  test('the first Tab reaches the skip link, and Enter moves into main', async ({ page }) => {
    for (const viewport of VIEWPORTS) {
      await page.setViewportSize(viewport);
      await page.goto(`/p/${long.slug}`);
      await expect(page.getByRole('heading', { name: 'Long page body' })).toBeVisible();
      await page.keyboard.press('Tab');
      const skip = page.getByRole('link', { name: 'Skip to content' });
      await expect(skip).toBeFocused();
      await expect(skip).toBeInViewport();
      await page.keyboard.press('Enter');
      await expect(page.locator('main#main')).toBeFocused();
    }
  });

  test('the footer sits at the bottom of an empty page', async ({ page }) => {
    for (const viewport of VIEWPORTS) {
      await page.setViewportSize(viewport);
      await page.goto(`/p/${empty.slug}`);
      const footer = page.getByTestId('site-footer');
      await expect(footer).toBeVisible();
      const box = await footer.boundingBox();
      expect((box?.y ?? 0) + (box?.height ?? 0)).toBeGreaterThanOrEqual(viewport.height - 1);
    }
  });

  test('a long page keeps its header, main and footer flush', async ({ page }) => {
    await page.setViewportSize(VIEWPORTS[0]);
    await page.goto(`/p/${long.slug}`);
    await expect(page.getByRole('heading', { name: 'Long page body' })).toBeVisible();
    const [header, main, footer] = await page.evaluate(() =>
      ['[data-testid="site-header"]', 'main', '[data-testid="site-footer"]'].map((s) => {
        const r = document.querySelector(s)?.getBoundingClientRect();
        return { top: r?.top ?? -1, bottom: r?.bottom ?? -1 };
      }),
    );
    // The frame adds no gaps: the column is exactly the three slots.
    expect(header.top).toBe(0);
    expect(Math.abs(main.top - header.bottom)).toBeLessThanOrEqual(1);
    expect(Math.abs(footer.top - main.bottom)).toBeLessThanOrEqual(1);
  });

  test('printing drops the site chrome', async ({ page }) => {
    await page.goto(`/p/${long.slug}`);
    await expect(page.getByTestId('site-header')).toBeVisible();
    await page.emulateMedia({ media: 'print' });
    await expect(page.getByTestId('site-header')).toBeHidden();
    await expect(page.getByTestId('site-footer')).toBeHidden();
    await expect(page.getByRole('heading', { name: 'Long page body' })).toBeVisible();
    await page.emulateMedia({ media: 'screen' });
    await expect(page.getByTestId('site-header')).toBeVisible();
  });

  test('the draft preview says so and links back to the editor', async ({ page }) => {
    await page.goto(`/p/${long.slug}`);
    await expect(page.getByRole('heading', { name: 'Long page body' })).toBeVisible();
    await expect(page.getByTestId('preview-bar')).toHaveCount(0);

    await page.goto(`/pagebuilder/${draft.id}/preview`);
    const bar = page.getByTestId('preview-bar');
    await expect(bar).toContainText('Preview — this draft is not published');
    await expect(page.getByTestId('site-header')).toBeVisible();
    await bar.getByRole('link', { name: 'Back to editor' }).click();
    await expect(page).toHaveURL(new RegExp(`/pagebuilder/${draft.id}/edit$`));
  });
});
