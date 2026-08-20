import { expect, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * The admin list is the only place an article's category and date can be set —
 * the page editor knows nothing about either.
 */
test.describe('News admin', () => {
  test.describe.configure({ mode: 'serial' });

  test('is reachable from the sidebar', async ({ page }) => {
    await login(page);
    await page.goto('/dashboard/');
    // "News" is the sidebar *group* now, holding Articles and Categories —
    // the rail splits by section rather than lumping both modules under
    // "Content". The link to click is therefore the leaf, not the group.
    await page.getByRole('link', { name: 'Articles', exact: true }).click();
    await expect(page).toHaveURL(/\/news\/?$/);
    await expect(page.getByRole('heading', { name: 'News', level: 1 })).toBeVisible();
  });

  test('lists an article with its public URL and lets its category be edited', async ({ page }) => {
    await login(page);
    const headers = await csrfHeader(page);
    const slug = uniqueSlug('e2e-admin');
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers,
      data: {
        title: `Admin ${slug}`,
        slug,
        draft_data: { root: { props: { title: 'Admin', width: 'full' } }, content: [], zones: {} },
      },
    });
    const { id } = await created.json();
    await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
      headers,
      data: { note: 'admin' },
    });
    await page.request.post('/api/news/articles', {
      headers,
      data: { page_id: id, category: 'Before', published_at: null },
    });

    await page.goto('/news/');
    // Rows are cards now, not table rows — located by the slug they carry so
    // the locator does not depend on which strings the card happens to render.
    const row = page.locator(`[data-testid="article-row"][data-slug="${slug}"]`);
    await expect(row).toContainText(`/p/${slug}`);

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
    const headers = await csrfHeader(page);

    // Two articles in different categories, so a filter has something to hide.
    const made: Record<string, string> = {};
    for (const category of ['Alpha', 'Beta']) {
      const slug = uniqueSlug(`filt-${category.toLowerCase()}`);
      made[category] = slug;
      const created = await page.request.post('/api/pagebuilder/pages', {
        headers,
        data: { title: `${category} ${slug}`, slug, draft_data: { content: [] } },
      });
      const { id } = await created.json();
      await page.request.post(`/api/pagebuilder/pages/${id}/publish`, { headers, data: {} });
      await page.request.post('/api/news/articles', {
        headers,
        data: { page_id: id, category, published_at: null },
      });
    }

    const card = (slug: string) => page.locator(`[data-testid="article-row"][data-slug="${slug}"]`);

    await page.goto('/news/');
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
    await page.goto('/news/?category=Beta');
    await expect(card(made.Beta)).toBeVisible();
    await expect(card(made.Alpha)).toHaveCount(0);
  });
});

test.describe('Article lifecycle', () => {
  test('deleting the page removes its article', async ({ page }) => {
    // Not tidiness: there is no cross-module foreign key to cascade from, and
    // SQLite reuses a deleted page's id — so a leftover row re-attaches to the
    // next page created and the feed shows one article's title under
    // another's metadata. That is a real bug this suite caught.
    await login(page);
    const headers = await csrfHeader(page);
    const slug = uniqueSlug('e2e-doomed');
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers,
      data: {
        title: `Doomed ${slug}`,
        slug,
        draft_data: { root: { props: { title: 'Doomed', width: 'full' } }, content: [], zones: {} },
      },
    });
    const { id } = await created.json();
    const attached = await page.request.post('/api/news/articles', {
      headers,
      data: { page_id: id, category: 'Temp', published_at: null },
    });
    expect(attached.status()).toBe(201);

    const deleted = await page.request.delete(`/api/pagebuilder/pages/${id}`, { headers });
    expect(deleted.ok()).toBeTruthy();

    await expect
      .poll(async () => {
        const body = await (
          await page.request.get('/api/news/articles?limit=100', {
            headers: { Accept: 'application/json' },
          })
        ).json();
        return body.items.filter((i: { page_id: number }) => i.page_id === id).length;
      })
      .toBe(0);

    // And the page itself is gone, so attaching to that id is a 404 rather
    // than quietly creating a row that the next page to reuse the id inherits.
    const reattach = await page.request.post('/api/news/articles', {
      headers,
      data: { page_id: id, category: 'Fresh', published_at: null },
    });
    expect(reattach.status(), 'attaching to a deleted page must not succeed').toBe(404);
  });
});
