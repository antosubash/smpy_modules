import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * Cross-section search — screen 2g.
 *
 * The point of the screen is that one query reaches things that live in
 * different tables, so the assertions check *which section* a hit lands in as
 * well as that it was found. A search that returned everything in one flat list
 * would pass a weaker test and be a worse screen.
 */

const SEARCH = '/admin/search';

async function makePage(page: Page, title: string, body = '') {
  const headers = await csrfHeader(page);
  const slug = uniqueSlug('srch');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title,
      slug,
      draft_data: {
        root: { props: { title, width: 'full' } },
        content: body ? [{ type: 'Heading', props: { id: 'h1', text: body } }] : [],
        zones: {},
      },
    },
  });
  const { id } = (await created.json()) as { id: number };
  return { id, slug, headers };
}

async function makeArticle(page: Page, title: string, category: string) {
  const { id, slug, headers } = await makePage(page, title);
  await page.request.post(`/api/pagebuilder/pages/${id}/publish`, { headers, data: {} });
  const newsCsrf = (await page.context().cookies()).find((c) => c.name === 'news_csrf')?.value;
  await page.request.post('/api/news/articles', {
    headers: newsCsrf ? { 'X-CSRF-Token': decodeURIComponent(newsCsrf) } : {},
    data: { page_id: id, category, published_at: null },
  });
  return { id, slug };
}

const section = (page: Page, label: string) =>
  page.locator(`[data-testid="search-section"][data-section="${label}"]`);

test.describe('Admin search', () => {
  test('says what it is for before anything is typed', async ({ page }) => {
    await login(page);
    await page.goto(SEARCH);

    await expect(page.getByRole('heading', { name: 'Search', level: 1 })).toBeVisible();
    await expect(page.getByText('Type to search')).toBeVisible();
  });

  test('finds an article and a page in their own sections', async ({ page }) => {
    await login(page);
    const term = `zeph${Date.now().toString(36)}`;
    await makeArticle(page, `Article about ${term}`, 'Research');
    await makePage(page, `Page about ${term}`);

    await page.goto(`${SEARCH}?q=${term}`);

    await expect(section(page, 'Articles')).toContainText(`Article about ${term}`);
    await expect(section(page, 'Pages')).toContainText(`Page about ${term}`);
    // An article is a page underneath, but it must not be counted twice —
    // the section totals would then exceed what the archive holds.
    await expect(section(page, 'Pages')).not.toContainText(`Article about ${term}`);
  });

  test('searches body text, not just titles', async ({ page }) => {
    await login(page);
    const term = `bodyterm${Date.now().toString(36)}`;
    await makePage(page, 'A page with an unrelated title', `Something about ${term} inside`);

    await page.goto(`${SEARCH}?q=${term}`);

    const hit = section(page, 'Pages').getByTestId('search-hit').first();
    await expect(hit).toContainText('unrelated title');
    // And it shows the surrounding sentence, which is the whole reason to
    // search bodies rather than just titles.
    await expect(hit).toContainText(term);
  });

  test('a category matches its articles', async ({ page }) => {
    await login(page);
    const category = `Cat${Date.now().toString(36)}`;
    await makeArticle(page, 'Titled nothing like the category', category);

    await page.goto(`${SEARCH}?q=${category}`);

    await expect(section(page, 'Articles')).toContainText('Titled nothing like the category');
  });

  test('the section filters narrow to one kind', async ({ page }) => {
    await login(page);
    const term = `filt${Date.now().toString(36)}`;
    await makeArticle(page, `Article ${term}`, 'Research');
    await makePage(page, `Page ${term}`);

    await page.goto(`${SEARCH}?q=${term}`);
    await expect(section(page, 'Pages')).toBeVisible();

    await page.getByRole('button', { name: /^Articles \d+$/ }).click();
    await expect(section(page, 'Articles')).toBeVisible();
    await expect(section(page, 'Pages')).toHaveCount(0);
  });

  test('a search that matches nothing says so', async ({ page }) => {
    await login(page);
    await page.goto(`${SEARCH}?q=zzz-nothing-matches-zzz`);

    await expect(page.getByText(/Nothing matches/)).toBeVisible();
  });

  test('the query lives in the URL, so a search is linkable', async ({ page }) => {
    await login(page);
    const term = `link${Date.now().toString(36)}`;
    await makePage(page, `Linkable ${term}`);

    await page.goto(SEARCH);
    await page.getByLabel('Search everything').fill(term);
    await expect(section(page, 'Pages')).toContainText(`Linkable ${term}`);
    await expect(page).toHaveURL(new RegExp(`[?&]q=${term}`));

    await page.reload();
    await expect(section(page, 'Pages')).toContainText(`Linkable ${term}`);
  });

  test('is reachable from the sidebar', async ({ page }) => {
    await login(page);
    await page.goto('/dashboard/');

    await page.getByRole('link', { name: 'Search everything' }).click();

    await expect(page).toHaveURL(/\/admin\/search$/);
  });
});
