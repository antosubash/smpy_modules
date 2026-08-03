import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * The feed is the reason the block registry exists.
 *
 * pagebuilder must not import news, so the block reaches the palette by
 * registration at app start instead — and if that wiring breaks, a page holding
 * a NewsFeed block renders nothing at all with every other suite still green.
 */

async function publishArticle(page: Page, category: string): Promise<string> {
  const headers = await csrfHeader(page);
  const slug = uniqueSlug('e2e-article');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title: `Article ${slug}`,
      slug,
      meta_description: 'The excerpt.',
      draft_data: {
        root: { props: { title: 'Article', width: 'full' } },
        content: [
          { type: 'Heading', props: { id: 'h', text: 'Body', level: 'h1', align: 'left' } },
        ],
        zones: {},
      },
    },
  });
  expect(created.ok()).toBeTruthy();
  const { id } = await created.json();
  await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
    headers,
    data: { note: 'article' },
  });
  const attached = await page.request.post('/api/news/articles', {
    headers,
    data: { page_id: id, category, published_at: '2026-02-01T00:00:00Z' },
  });
  expect(attached.status(), await attached.text()).toBe(201);
  return slug;
}

async function publishFeedPage(page: Page, category: string): Promise<string> {
  const headers = await csrfHeader(page);
  const slug = uniqueSlug('e2e-feed');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title: 'Newsroom',
      slug,
      draft_data: {
        root: { props: { title: 'Newsroom', width: 'full' } },
        content: [
          {
            type: 'NewsFeed',
            props: {
              id: 'feed',
              title: 'Latest',
              category,
              limit: 4,
              columns: '4',
              viewAllLabel: '',
              viewAllHref: '',
            },
          },
        ],
        zones: {},
      },
    },
  });
  expect(created.ok()).toBeTruthy();
  const { id } = await created.json();
  await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
    headers,
    data: { note: 'feed' },
  });
  return slug;
}

test.describe('News feed block', () => {
  test.describe.configure({ mode: 'serial' });

  test('is offered in the page palette', async ({ page }) => {
    await login(page);
    await page.goto('/pagebuilder/new');
    await expect(
      page.locator('[class*="DrawerItem-name"]').filter({ hasText: 'News feed' }).first(),
      'the block reaches the palette only through registration at app start',
    ).toBeAttached();
  });

  test('is not offered in the site-layout palette', async ({ page }) => {
    // A news grid in the header or footer would repeat on every page.
    await login(page);
    await page.goto('/pagebuilder/layout');
    await expect(
      page.locator('[class*="DrawerItem-name"]').filter({ hasText: 'News feed' }),
    ).toHaveCount(0);
  });

  test('renders live articles on a published page', async ({ page }) => {
    await login(page);
    const articleSlug = await publishArticle(page, 'Updates');
    const feedSlug = await publishFeedPage(page, '');

    await page.goto(`/p/${feedSlug}`);
    const card = page.getByRole('link', { name: new RegExp(`Article ${articleSlug}`) });
    await expect(card).toBeVisible();
    // An article *is* a page, so the card links at the page's own URL.
    await expect(card).toHaveAttribute('href', `/p/${articleSlug}`);
    await expect(card).toContainText('The excerpt.');
    await expect(card).toContainText('Feb 1, 2026');
  });

  test('honours the category filter', async ({ page }) => {
    await login(page);
    const wanted = await publishArticle(page, 'Events');
    const other = await publishArticle(page, 'Releases');
    const feedSlug = await publishFeedPage(page, 'Events');

    await page.goto(`/p/${feedSlug}`);
    await expect(page.getByRole('link', { name: new RegExp(`Article ${wanted}`) })).toBeVisible();
    await expect(page.getByRole('link', { name: new RegExp(`Article ${other}`) })).toHaveCount(0);
  });

  test('renders nothing rather than an empty section when no article matches', async ({ page }) => {
    await login(page);
    const feedSlug = await publishFeedPage(page, 'NoSuchCategory');

    await page.goto(`/p/${feedSlug}`);
    // Not even the heading: a title over an empty grid reads as broken.
    await expect(page.getByRole('heading', { name: 'Latest' })).toHaveCount(0);
  });

  test('an anonymous visitor sees the feed', async ({ browser }) => {
    // The whole point of the public read routes — the block runs with no
    // session on a published page.
    const admin = await browser.newPage();
    await login(admin);
    const articleSlug = await publishArticle(admin, 'Updates');
    const feedSlug = await publishFeedPage(admin, '');
    await admin.close();

    const anon = await browser.newPage();
    await anon.goto(`/p/${feedSlug}`);
    await expect(
      anon.getByRole('link', { name: new RegExp(`Article ${articleSlug}`) }),
    ).toBeVisible();
    await anon.close();
  });
});
