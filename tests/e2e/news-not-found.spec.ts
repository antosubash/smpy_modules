import { expect, type Page, test } from '@playwright/test';

import { paragraphBody, seedArticle } from './article-helpers';
import { login, moduleCsrfHeader, uniqueSlug } from './helpers';

/**
 * A news address with nothing to show (#248): a missing, draft or deleted
 * article answers with the site's own branded 404 — pagebuilder's
 * `PublicNotFound`, inside the site header and footer — in the address's
 * language, never cached, and identical for every cause. Standalone: it seeds
 * its own layout and articles, and resets the layout afterwards.
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
        logoAlt: 'News 404 site',
        homeHref: '/',
        utilityLinks: [],
        navItems: [{ label: 'News 404 nav', href: '/', children: [] }],
        ctaLabel: 'News 404 CTA',
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
        logoAlt: 'News 404 site',
        homeHref: '/',
        links: [{ label: 'News 404 footer link', href: '#' }],
        note: 'News 404 small print.',
      },
    },
  ],
};

const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
];

const EN = "This page doesn't exist";
const DE = 'Diese Seite gibt es nicht';

async function putLayout(page: Page, header: unknown, footer: unknown) {
  const response = await page.request.put('/api/pagebuilder/layout', {
    headers: await moduleCsrfHeader(page, '/pagebuilder/'),
    data: { header_data: header, footer_data: footer, note: 'e2e news 404' },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
}

async function germanDraft(page: Page): Promise<string> {
  const slug = uniqueSlug('e2e-entwurf');
  const response = await page.request.post('/api/news/articles', {
    headers: await moduleCsrfHeader(page),
    data: { title: slug, slug, locale: 'de' },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return slug;
}

test.describe('News — the site 404', () => {
  // The layout is one shared record; keep this file's tests in order.
  test.describe.configure({ mode: 'serial' });

  const cases: { path: string; heading: string }[] = [];

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await login(page);
    await putLayout(page, HEADER, FOOTER);
    const draft = await seedArticle(page, { prefix: 'e2e-404-draft', body: paragraphBody('x') });
    const deleted = await seedArticle(page, {
      prefix: 'e2e-404-gone',
      body: paragraphBody('gone'),
      publish: true,
    });
    const removed = await page.request.delete(`/api/news/articles/${deleted.articleId}`, {
      headers: await moduleCsrfHeader(page),
    });
    expect(removed.status()).toBe(204);
    cases.push(
      { path: `/news/${uniqueSlug('missing')}`, heading: EN },
      { path: draft.url, heading: EN },
      { path: deleted.url, heading: EN },
      { path: `/de/news/${uniqueSlug('fehlt')}`, heading: DE },
      { path: `/de/news/${await germanDraft(page)}`, heading: DE },
    );
    await page.close();
  });

  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    await login(page);
    await putLayout(page, {}, {});
    await page.close();
  });

  test('a missing or unpublished article gets the branded 404, in en and de', async ({
    browser,
  }) => {
    // Anonymous: what a reader following a dead link sees.
    const context = await browser.newContext();
    const page = await context.newPage();
    const texts = new Map<string, Set<string>>();
    for (const viewport of VIEWPORTS) {
      await page.setViewportSize(viewport);
      for (const { path, heading } of cases) {
        const response = await page.goto(path);
        expect(response?.status(), path).toBe(404);
        expect(response?.headers()['cache-control']).toBe('no-store');
        const block = page.getByTestId('public-not-found');
        await expect(block.getByRole('heading', { level: 1 })).toHaveText(heading);
        await expect(page.locator('html')).toHaveAttribute('lang', heading === DE ? 'de' : 'en');
        await expect(page.getByTestId('site-header')).toBeVisible();
        await expect(page.getByTestId('site-footer')).toBeVisible();
        await expect(block.getByRole('link')).toHaveAttribute('href', '/');
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        );
        expect(overflow, `${path} at ${viewport.width}`).toBeLessThanOrEqual(0);
        const seen = texts.get(heading) ?? new Set<string>();
        seen.add((await block.textContent()) ?? '');
        texts.set(heading, seen);
      }
    }
    // No oracle: a draft, a deleted article and a typo read exactly alike.
    for (const seen of texts.values()) expect(seen.size).toBe(1);
    await context.close();
  });
});
