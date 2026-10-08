import { expect, test } from '@playwright/test';

import { seedArticle } from './article-helpers';
import { csrfHeader, login } from './helpers';

/**
 * The admin list is where an article's category and date are set.
 *
 * They used to be the *only* things news owned — the rest of an article was a
 * pagebuilder page, and the page editor knew nothing about either. The list has
 * not changed much; what changed is that there is no second document behind it.
 */
test.describe('News admin', () => {
  test.describe.configure({ mode: 'serial' });

  test('is reachable from the sidebar', async ({ page }) => {
    await login(page);
    await page.goto('/dashboard/');
    // "News" is the sidebar *group* now, holding Articles and Categories —
    // the rail splits by section rather than lumping both modules under
    // "Content". The link to click is therefore the leaf, not the group.
    // Each leaf draws its icon. NavIcon renders a name it does not know as an
    // empty box, which is how News once shipped three blank icons.
    for (const name of ['Articles', 'Categories', 'Search everything']) {
      await expect(page.getByRole('link', { name, exact: true }).locator('svg')).toHaveCount(1);
    }
    await page.getByRole('link', { name: 'Articles', exact: true }).click();
    await expect(page).toHaveURL(/\/news\/?$/);
    await expect(page.getByRole('heading', { name: 'News', level: 1 })).toBeVisible();
  });

  test('lists an article with its public URL and lets its category be edited', async ({ page }) => {
    await login(page);
    const { slug } = await seedArticle(page, {
      prefix: 'e2e-admin',
      titlePrefix: 'Admin',
      category: 'Before',
      publish: true,
    });

    await page.goto('/admin/news/');
    // Rows are cards now, not table rows — located by the slug they carry so
    // the locator does not depend on which strings the card happens to render.
    const row = page.locator(`[data-testid="article-row"][data-slug="${slug}"]`);
    await expect(row).toContainText(`/news/${slug}`);

    // Category and date edit in place, but behind a click: the chip is the
    // affordance, and the inputs only appear once it is pressed.
    // The chip's accessible name starts with the category it shows, so this
    // asserts the visible value and the affordance in one locator.
    const chip = row.getByRole('button', { name: /^Before — edit category and date$/ });
    await expect(chip).toBeVisible();
    await chip.click();

    const category = row.getByLabel(`Category for Admin ${slug}`);
    await expect(category).toHaveValue('Before');

    // Save is disabled until something actually changes, so the row never
    // fires a no-op PUT.
    await expect(row.getByRole('button', { name: 'Save' })).toBeDisabled();
    await category.fill('After');
    await row.getByRole('button', { name: 'Save' }).click();

    await expect
      .poll(async () => {
        const body = await (
          await page.request.get('/api/news/articles', { headers: { Accept: 'application/json' } })
        ).json();
        return body.items.find((i: { slug: string }) => i.slug === slug)?.category;
      })
      .toBe('After');
  });

  test('the category filter is in the URL and survives a reload', async ({ page }) => {
    await login(page);
    // Two articles in different categories, so a filter has something to hide.
    const made: Record<string, string> = {};
    for (const category of ['Alpha', 'Beta']) {
      const { slug } = await seedArticle(page, {
        prefix: `filt-${category.toLowerCase()}`,
        titlePrefix: category,
        category,
        publish: true,
      });
      made[category] = slug;
    }

    const card = (slug: string) => page.locator(`[data-testid="article-row"][data-slug="${slug}"]`);

    await page.goto('/admin/news/');
    await expect(card(made.Alpha)).toBeVisible();

    // The category filter is a select now — there can be far more categories
    // than fit in a pill row once they are administered rather than typed.
    await page.getByLabel('Filter by category').selectOption('Alpha');
    await expect(card(made.Beta)).toHaveCount(0);
    await expect(page).toHaveURL(/[?&]category=Alpha/);

    // The point of putting it in the URL: reloading keeps the filter instead
    // of silently dropping the user back into the unfiltered list.
    await page.reload();
    await expect(card(made.Alpha)).toBeVisible();
    await expect(card(made.Beta)).toHaveCount(0);

    // And it is linkable, not just sticky.
    await page.goto('/admin/news/?category=Beta');
    await expect(card(made.Beta)).toBeVisible();
    await expect(card(made.Alpha)).toHaveCount(0);
  });
});

test.describe('Article lifecycle', () => {
  test('deleting an article removes it, body and all', async ({ page }) => {
    // This test used to delete the *page* behind an article and then wait for
    // news to notice. That was not tidiness: `page_id` was an unenforceable
    // pointer into another module's table, and SQLite reuses a deleted row's
    // id — so a leftover article re-attached to the next page created and the
    // feed showed one article's title under another's metadata. A real bug
    // this suite caught, and one the schema no longer permits.
    //
    // An article is one row now, so what is left to check is that deleting it
    // actually deletes it.
    await login(page);
    const { articleId, slug } = await seedArticle(page, {
      prefix: 'e2e-doomed',
      titlePrefix: 'Doomed',
      category: 'Temp',
      publish: true,
    });

    // It is there, and it serves.
    expect((await page.request.get(`/news/${slug}`)).status()).toBe(200);

    const headers = await csrfHeader(page);
    const deleted = await page.request.delete(`/api/news/articles/${articleId}`, { headers });
    expect(deleted.status(), await deleted.text()).toBe(204);

    await expect
      .poll(async () => {
        const body = await (
          await page.request.get('/api/news/articles?limit=100', {
            headers: { Accept: 'application/json' },
          })
        ).json();
        return body.items.filter((i: { id: number }) => i.id === articleId).length;
      })
      .toBe(0);

    // And its public address stops answering, rather than serving a document
    // whose row is gone.
    expect((await page.request.get(`/news/${slug}`)).status()).toBe(404);
  });
});
