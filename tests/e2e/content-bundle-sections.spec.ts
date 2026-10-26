import { type Browser, expect, type Page, test } from '@playwright/test';

import { seedArticle } from './article-helpers';
import { login, moduleCsrfHeader } from './helpers';

/**
 * Contributed bundle sections (#80): news' articles ride a content snapshot.
 *
 * What the browser proves is what an operator reads. The section's card on
 * the review screen is built from news' own keys by a pagebuilder that knows
 * nothing about news; the approve result says what it wrote; and someone who
 * may run Import / Export but not edit articles sees counts and a reason,
 * never the articles' titles, and cannot restore them.
 *
 * Stands alone (CI shards by file): it seeds its own articles and snapshots,
 * and clears the site-wide pending import before each test.
 */

const CONTENT = '/pagebuilder/content';
const REVIEW = '/pagebuilder/content/review';
const PAGEBUILDER_ONLY = ['pagebuilder.edit', 'pagebuilder.publish', 'pagebuilder.approve'];

async function clearPendingImport(page: Page) {
  const headers = await moduleCsrfHeader(page, '/pagebuilder/');
  const pending = await (await page.request.get('/api/pagebuilder/imports/pending')).json();
  if (pending) {
    await page.request.post(`/api/pagebuilder/imports/${pending.id}/reject`, {
      headers,
      data: { note: 'clearing before e2e' },
    });
  }
  return headers;
}

async function articleTitle(page: Page, id: number): Promise<string> {
  const response = await page.request.get(`/api/news/articles/${id}/detail`);
  expect(response.status()).toBe(200);
  return (await response.json()).title;
}

async function takeSnapshot(page: Page, headers: Record<string, string>, note: string) {
  const response = await page.request.post('/api/pagebuilder/snapshots', {
    headers,
    data: { note },
  });
  expect(response.status(), await response.text()).toBe(201);
  return (await response.json()) as { id: number };
}

/** A second user holding every pagebuilder permission and no news one. */
async function pagebuilderOnlyUser(admin: Page, browser: Browser): Promise<Page> {
  const email = `bundle-e2e-${Date.now().toString(36)}@example.com`;
  const password = 'changeme1';
  const created = await admin.request.post('/api/users/admin', {
    headers: { 'content-type': 'application/json' },
    data: { email, password, role_names: [] },
  });
  expect(created.status(), await created.text()).toBe(201);
  const users = (await (await admin.request.get('/api/users/admin?per_page=100')).json()) as {
    id: string;
    email: string;
  }[];
  const id = users.find((u) => u.email === email)?.id;
  expect(id, 'the user just created should be listed').toBeTruthy();
  const granted = await admin.request.put(`/api/permissions/users/${id}`, {
    headers: { 'content-type': 'application/json' },
    data: { permissions: PAGEBUILDER_ONLY },
  });
  expect(granted.status()).toBe(200);

  const context = await browser.newContext();
  const page = await context.newPage();
  await login(page, { email, password });
  return page;
}

test.describe('Content bundle — contributed sections', () => {
  test('news rides the snapshot, shows in the review, and is restored on approval', async ({
    page,
  }) => {
    await login(page);
    await clearPendingImport(page);
    const article = await seedArticle(page, { prefix: 'bundle', titlePrefix: 'Kept' });
    const newsHeaders = await moduleCsrfHeader(page);

    await page.goto(CONTENT);
    await page.getByRole('button', { name: 'Take snapshot' }).click();
    // The row names news' counts by news' own labels.
    await expect(page.getByText(/^News — Articles: \d+/).first()).toBeVisible();

    const edited = await page.request.put(`/api/news/articles/${article.articleId}`, {
      headers: newsHeaders,
      data: { title: 'Edited after the snapshot' },
    });
    expect(edited.status(), await edited.text()).toBe(200);

    await page.goto(CONTENT);
    await page.getByRole('button', { name: 'Restore…' }).first().click();
    await expect(page).toHaveURL(new RegExp(`${REVIEW}$`));

    const card = page.getByTestId('plan-section-news');
    await expect(card.getByRole('heading', { name: 'News', exact: true })).toBeVisible();
    await expect(card.getByText('Articles overwritten (1)')).toBeVisible();
    await expect(card.getByText(article.slug)).toBeVisible();
    // The article's overwrite reaches the headline, though no page is at stake.
    await expect(page.getByText(/item.? will be overwritten/)).toBeVisible();
    expect(await articleTitle(page, article.articleId)).toBe('Edited after the snapshot');

    await page.getByRole('button', { name: /approve & apply/i }).click();
    await page
      .getByRole('alertdialog')
      .getByRole('button', { name: /^apply$/i })
      .click();
    await expect(page).toHaveURL(new RegExp(`${CONTENT}$`));
    await expect(page.getByText(/News: .*Articles overwritten: 1/)).toBeVisible();

    expect(await articleTitle(page, article.articleId)).toBe(article.title);
    await page.request.delete(`/api/news/articles/${article.articleId}`, { headers: newsHeaders });
  });

  test('without news.edit, a pagebuilder user sees counts and reasons, never articles', async ({
    page,
    browser,
  }) => {
    await login(page);
    const headers = await clearPendingImport(page);
    const article = await seedArticle(page, { prefix: 'bundle-hidden', titlePrefix: 'Secret' });
    const snapshot = await takeSnapshot(page, headers, 'with news');
    const other = await pagebuilderOnlyUser(page, browser);

    try {
      // Staged by them: news is not planned at all, and says why.
      await other.goto(CONTENT);
      await other.getByRole('button', { name: 'Restore…' }).first().click();
      await expect(other).toHaveURL(new RegExp(`${REVIEW}$`));
      await expect(
        other.getByText(
          'News is left out of this restore: restoring it needs news.edit, news.publish. The pages restore as usual.',
        ),
      ).toBeVisible();
      await expect(other.getByTestId('plan-section-news')).toHaveCount(0);
      await clearPendingImport(other);

      // Staged by an admin: they see the card's counts, not its rows.
      const staged = await page.request.post(`/api/pagebuilder/snapshots/${snapshot.id}/restore`, {
        headers,
      });
      expect(staged.status(), await staged.text()).toBe(201);
      await other.goto(REVIEW);
      const card = other.getByTestId('plan-section-news');
      await expect(card.getByTestId('plan-section-marker')).toHaveText(
        'News: only the counts are shown here. Seeing the details needs news.edit.',
      );
      await expect(card.getByText(/Unchanged articles \(\d+\)/)).toBeVisible();
      await expect(other.getByText(article.title)).toHaveCount(0);
      await expect(other.getByText(article.slug)).toHaveCount(0);
      await clearPendingImport(page);

      // Taken by them: the snapshot says news was left out, and why.
      await other.goto(CONTENT);
      await other.getByRole('button', { name: 'Take snapshot' }).click();
      await expect(
        other
          .getByText('News is not in this snapshot: whoever took it did not hold news.edit.')
          .first(),
      ).toBeVisible();
    } finally {
      await other.context().close();
      await page.request.delete(`/api/news/articles/${article.articleId}`, {
        headers: await moduleCsrfHeader(page),
      });
    }
  });
});
