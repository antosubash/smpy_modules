import { expect, test } from '@playwright/test';

import { clickAndConfirm, csrfHeader, login, publishWithNote, uniqueSlug } from './helpers';

test.describe('PageBuilder admin', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('lists pages and shows the empty state when none exist', async ({ page }) => {
    await page.goto('/pagebuilder/');
    await expect(page.getByRole('heading', { name: 'Pages' })).toBeVisible();
    await expect(page.getByRole('button', { name: /new page/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /media library/i })).toBeVisible();
  });

  test('creates, saves, publishes, views, and deletes a page', async ({ page }) => {
    const slug = uniqueSlug();
    const title = `E2E page ${slug}`;

    // ── Create ────────────────────────────────────────────────
    // "New page" opens the create dialog now — that flow has its own spec in
    // create-flows.spec.ts. This case is about the editor's own
    // create-and-save path, so it goes straight to the blank-editor route.
    await page.goto('/pagebuilder/new');

    // PageEditor's title field has no associated label — it's an
    // <input placeholder="Page title">. Match by placeholder.
    const titleInput = page.getByPlaceholder('Page title');
    await expect(titleInput).toBeVisible();
    await titleInput.fill(title);
    await page.getByPlaceholder('slug').fill(slug);

    // Save draft. The first save creates the page server-side and the
    // SPA navigates to /pagebuilder/<id>/edit via Inertia.
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/, { timeout: 15_000 });

    // Save again now that an id exists — confirms the "Draft saved" path.
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page.getByText('Draft saved.')).toBeVisible();

    // ── Publish ───────────────────────────────────────────────
    // Publish opens a dialog asking for an optional revision note; submit it
    // empty for the equivalent of the pre-#16 behaviour.
    await publishWithNote(page);
    await expect(page.getByText('Published.')).toBeVisible();
    // After publishing, an "Unpublish" button + "View" link both appear.
    await expect(page.getByRole('button', { name: /unpublish/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /^view$/i })).toBeVisible();

    // ── Public viewer ─────────────────────────────────────────
    const publicResponse = await page.request.get(`/p/${slug}`);
    expect(publicResponse.ok()).toBeTruthy();

    // ── List shows the published page ─────────────────────────
    // The board is the default view now; these assertions are about the
    // table, which is what `view=list` selects.
    await page.goto('/pagebuilder/?view=list');
    const row = page.locator('tr', { hasText: title });
    await expect(row).toBeVisible();
    await expect(row.getByText('published', { exact: true })).toBeVisible();

    // ── Edit round-trip ───────────────────────────────────────
    await row.getByRole('button', { name: /^edit$/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/);
    await expect(page.getByPlaceholder('Page title')).toHaveValue(title);
    await expect(page.getByPlaceholder('slug')).toHaveValue(slug);

    // ── Unpublish ─────────────────────────────────────────────
    await page.getByRole('button', { name: /unpublish/i }).click();
    await expect(page.getByText('Unpublished.')).toBeVisible();

    // After unpublishing, the public viewer returns 404.
    const after404 = await page.request.get(`/p/${slug}`);
    expect(after404.status()).toBe(404);

    // ── Delete ────────────────────────────────────────────────
    // The board is the default view now; these assertions are about the
    // table, which is what `view=list` selects.
    await page.goto('/pagebuilder/?view=list');
    await clickAndConfirm(
      page,
      page.locator('tr', { hasText: title }).getByRole('button', { name: /^delete$/i }),
    );
    await expect(page.locator('tr', { hasText: title })).toHaveCount(0);
  });

  test('SEO panel toggles meta description and OG image inputs', async ({ page }) => {
    const slug = uniqueSlug('seo');
    await page.goto('/pagebuilder/new');
    await page.getByPlaceholder('Page title').fill(`SEO page ${slug}`);
    await page.getByPlaceholder('slug').fill(slug);

    // Panel is collapsed by default — fields not in the DOM yet.
    await expect(page.getByPlaceholder(/Shown in search results/i)).toHaveCount(0);

    await page.getByRole('button', { name: /^seo$/i }).click();
    const metaDesc = page.getByPlaceholder(/Shown in search results/i);
    const ogImage = page.getByPlaceholder(/https:\/\/.*media\/pagebuilder/i);
    await expect(metaDesc).toBeVisible();
    await expect(ogImage).toBeVisible();
    await metaDesc.fill('A page assembled by the e2e suite.');
    await ogImage.fill('/media/pagebuilder/example.png');

    // Save and confirm we navigated into the edit URL — proves the
    // SEO fields were accepted server-side.
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/, { timeout: 15_000 });

    // Clean up so this test doesn't leave a draft behind.
    // The board is the default view now; these assertions are about the
    // table, which is what `view=list` selects.
    await page.goto('/pagebuilder/?view=list');
    await clickAndConfirm(
      page,
      page
        .locator('tr', { hasText: `SEO page ${slug}` })
        .getByRole('button', { name: /^delete$/i }),
    );
  });

  test('media library page is reachable from the page list', async ({ page }) => {
    await page.goto('/pagebuilder/');
    await page.getByRole('button', { name: /media library/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/media$/);
  });

  test('search and status filter narrow the list, and survive a reload', async ({ page }) => {
    const tag = uniqueSlug('filter');
    const headers = await csrfHeader(page);
    const created: number[] = [];
    for (const name of ['Alpha', 'Beta']) {
      const res = await page.request.post('/api/pagebuilder/pages', {
        headers,
        data: {
          title: `${name} ${tag}`,
          slug: `${name.toLowerCase()}-${tag}`,
          draft_data: { content: [] },
        },
      });
      expect(res.status(), await res.text()).toBe(201);
      created.push((await res.json()).id as number);
    }
    // Publish Alpha so the two differ by status as well as by title.
    await page.request.post(`/api/pagebuilder/pages/${created[0]}/publish`, { headers, data: {} });

    // The board is the default view now; these assertions are about the
    // table, which is what `view=list` selects.
    await page.goto('/pagebuilder/?view=list');
    await expect(page.locator('tr', { hasText: `Alpha ${tag}` })).toBeVisible();
    await expect(page.locator('tr', { hasText: `Beta ${tag}` })).toBeVisible();

    // ── Search narrows to one row ─────────────────────────────
    await page.getByRole('searchbox', { name: /search pages/i }).fill(`Beta ${tag}`);
    await expect(page.locator('tr', { hasText: `Beta ${tag}` })).toBeVisible();
    await expect(page.locator('tr', { hasText: `Alpha ${tag}` })).toHaveCount(0);

    // The filter is in the URL, so reloading keeps it rather than resetting.
    await expect(page).toHaveURL(/[?&]search=Beta/);
    await page.reload();
    await expect(page.getByRole('searchbox', { name: /search pages/i })).toHaveValue(`Beta ${tag}`);
    await expect(page.locator('tr', { hasText: `Alpha ${tag}` })).toHaveCount(0);

    // ── Status pills filter independently ─────────────────────
    // The board is the default view now; these assertions are about the
    // table, which is what `view=list` selects.
    await page.goto('/pagebuilder/?view=list');
    await page.getByRole('button', { name: 'Published' }).click();
    await expect(page.locator('tr', { hasText: `Alpha ${tag}` })).toBeVisible();
    await expect(page.locator('tr', { hasText: `Beta ${tag}` })).toHaveCount(0);

    // ── A filter matching nothing offers a way out ────────────
    await page.getByRole('searchbox', { name: /search pages/i }).fill('no-such-page-anywhere');
    await expect(page.getByText(/no pages match this filter/i)).toBeVisible();
    await page.getByRole('button', { name: /clear filters/i }).click();
    await expect(page.locator('tr', { hasText: `Beta ${tag}` })).toBeVisible();

    for (const id of created) {
      await page.request.delete(`/api/pagebuilder/pages/${id}`, { headers });
    }
  });
});
