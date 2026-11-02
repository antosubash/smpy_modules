import { type Browser, expect, type Page, test } from '@playwright/test';

import { paragraphBody, seedArticle } from './article-helpers';
import { login, moduleCsrfHeader, uniqueSlug } from './helpers';

/**
 * The NewsStats block: a live count of the articles a reader can open.
 *
 * Standalone: every test counts inside a category of its own, so the numbers do
 * not depend on whatever other spec files published. The assertions are on the
 * visible number, retried, because the block fetches it after the page loads.
 */

const BLOCK = 'Live article count';
const LABEL = 'Published';

async function seed(page: Page, category: string, publish: boolean) {
  await seedArticle(page, {
    prefix: 'e2e-stat',
    category,
    publish,
    publishedAt: '2020-01-01T00:00:00Z',
    body: paragraphBody('Body'),
  });
}

async function publishStatsPage(page: Page, category: string): Promise<string> {
  const headers = await moduleCsrfHeader(page, '/pagebuilder/');
  const slug = uniqueSlug('e2e-news-stats');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title: 'Newsroom numbers',
      slug,
      draft_data: {
        root: { props: { title: 'Newsroom numbers', width: 'full' } },
        content: [
          {
            type: 'NewsStats',
            props: {
              id: 'stats',
              title: 'In numbers',
              subtitle: '',
              surface: 'cards',
              items: [{ language: 'all', category, label: LABEL, prefix: '', suffix: '' }],
            },
          },
        ],
        zones: {},
      },
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const { id } = await created.json();
  const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
    headers,
    data: { note: 'stats' },
  });
  expect(published.ok(), await published.text()).toBeTruthy();
  return slug;
}

/** What a first-time anonymous visitor sees. The stats answer is public-cacheable
 *  for a minute (like the feed), so a returning browser may hold the old number
 *  by design; a fresh context has no cache, which is what a mutation is
 *  measured against. */
async function visitorSees(browser: Browser, slug: string): Promise<string> {
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await page.goto(`/p/${slug}`);
    const number = page.locator('dd').first();
    await expect(number).not.toHaveText('–');
    return (await number.textContent()) ?? '';
  } finally {
    await context.close();
  }
}

test.describe('News stats block', () => {
  test('is offered in the page palette', async ({ page }) => {
    await login(page);
    await page.goto('/pagebuilder/new');
    await expect(
      page.locator('[class*="DrawerItem-name"]').filter({ hasText: BLOCK }).first(),
    ).toBeAttached();
  });

  test('is not offered in the site-layout palette', async ({ page }) => {
    // A live number in the header or footer would repeat on every page.
    await login(page);
    await page.goto('/pagebuilder/layout');
    await expect(page.locator('[class*="DrawerItem-name"]').filter({ hasText: BLOCK })).toHaveCount(
      0,
    );
  });

  test('an anonymous visitor sees the count, and it follows a new article', async ({ browser }) => {
    const admin = await browser.newPage();
    await login(admin);
    const category = `Stats ${Date.now().toString(36)}`;
    await seed(admin, category, true);
    await seed(admin, category, true);
    const slug = await publishStatsPage(admin, category);

    const anon = await (await browser.newContext()).newPage();
    try {
      await anon.goto(`/p/${slug}`);
      await expect(anon.locator('dd').first()).toHaveText('2');
      await expect(anon.getByText(LABEL, { exact: true })).toBeVisible();
    } finally {
      await anon.context().close();
    }

    await seed(admin, category, true);
    await expect.poll(() => visitorSees(browser, slug), { timeout: 20_000 }).toBe('3');
    await admin.close();
  });

  test('a draft is not counted', async ({ browser }) => {
    const admin = await browser.newPage();
    await login(admin);
    const category = `Drafts ${Date.now().toString(36)}`;
    await seed(admin, category, true);
    await seed(admin, category, false);
    const slug = await publishStatsPage(admin, category);

    const anon = await (await browser.newContext()).newPage();
    try {
      await anon.goto(`/p/${slug}`);
      await expect(anon.locator('dd').first()).toHaveText('1');
    } finally {
      await anon.context().close();
      await admin.close();
    }
  });
});
