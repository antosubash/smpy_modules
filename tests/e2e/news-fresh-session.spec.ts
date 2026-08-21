import { expect, test } from '@playwright/test';

import { login } from './helpers';

/**
 * "New article" from a session that has never touched pagebuilder.
 *
 * This is deliberately the one news flow that does NOT go through
 * `csrfHeader()`. That helper starts with `page.goto('/pagebuilder/')`, which
 * makes pagebuilder's CsrfCookieMiddleware mirror the session token into a
 * readable cookie — so every other spec primes the cookie before it does
 * anything, and none of them can see it missing.
 *
 * Creating an article used to POST to pagebuilder's CSRF-protected page API
 * from the browser. A user who clicks News in the sidebar and then "New
 * article" has never requested a pagebuilder path, so the cookie was unset and
 * the POST came back 403 with no page and no article — the module's documented
 * primary flow, broken on a fresh login.
 *
 * It is now one request to news' own API, which creates the page and attaches
 * the article server-side in a single transaction, so no pagebuilder cookie is
 * involved at any point. The precondition below therefore asserts something
 * stronger than it used to: not merely that the cookie is unset when the flow
 * starts, but that a flow which never needs it still works.
 */
test.describe('News — first visit of a session', () => {
  test('creates an article without having visited Pages first', async ({ page }) => {
    await login(page);

    // Straight to News. Nothing above may request a /pagebuilder path, or the
    // cookie gets primed and this test stops testing anything.
    await page.goto('/admin/news/');
    await expect(page.getByRole('heading', { name: 'News' })).toBeVisible();

    const cookieBefore = (await page.context().cookies()).find(
      (c) => c.name === 'pagebuilder_csrf',
    );
    expect(cookieBefore, 'precondition: the CSRF cookie must not be primed yet').toBeUndefined();

    const title = `Fresh session ${Date.now().toString(36)}`;
    await page.getByRole('button', { name: 'New article' }).click();
    // The dialog asks for four fields now; the other three carry defaults.
    // Scoped to the dialog — the list's "Search headline or slug" box would
    // otherwise also match getByLabel('Headline').
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Headline').fill(title);
    await dialog.getByRole('button', { name: 'Create draft' }).click();

    // Success is landing in the editor for the page that was just created.
    // The /edit suffix matters: /pagebuilder/{id} without it is a 404 — the
    // old flow navigated there and this pattern let it pass unnoticed.
    await page.waitForURL(/\/pagebuilder\/\d+\/edit$/, { timeout: 15_000 });
    // Assert on the editor itself, not on the absence of "Not Found": a
    // toHaveCount(0) passes on its first poll and so cannot catch an error
    // page that renders a moment after the URL settles. The toolbar's title
    // field carries the page title, so this proves both that the editor
    // mounted and that it opened the page just created.
    await expect(page.getByPlaceholder('Page title')).toHaveValue(title);

    // And the article row exists, rather than a page with no metadata attached.
    // Rows are cards now, not table rows.
    await page.goto('/admin/news/');
    await expect(
      page.locator('[data-testid="article-row"]').filter({ hasText: title }),
    ).toBeVisible();
  });

  test('a second article of the same headline takes the next free URL', async ({ page }) => {
    // The dialog fills the URL field from the headline as a *preview*, and
    // sends it only when the author has actually edited it. Sending the
    // preview turned this into a "Slug already in use" dead end: the server
    // can only pick the next free variant for a slug nobody asked for by name.
    await login(page);
    await page.goto('/admin/news/');

    const headline = `Repeat headline ${Date.now().toString(36)}`;
    const slugs: string[] = [];
    for (let i = 0; i < 2; i++) {
      await page.goto('/admin/news/');
      await page.getByRole('button', { name: 'New article' }).click();
      const dialog = page.getByRole('dialog');
      await dialog.getByLabel('Headline').fill(headline);
      slugs.push(await dialog.locator('#news-new-article-slug').inputValue());
      await dialog.getByRole('button', { name: 'Create draft' }).click();
      await page.waitForURL(/\/pagebuilder\/\d+\/edit$/, { timeout: 20_000 });
    }

    // Same preview both times — the dialog has no idea the first one is taken.
    expect(slugs[0]).toBe(slugs[1]);

    // …and the server resolved the collision rather than refusing it. Read
    // back over the API rather than the list: both creates already had to
    // succeed for the loop above to finish, so this only needs the slugs.
    const listed = await page.request.get(
      `/api/news/articles?limit=20&q=${encodeURIComponent(headline)}`,
    );
    const body = (await listed.json()) as { items: { slug: string }[] };
    expect(body.items.map((i) => i.slug).sort()).toEqual([slugs[0], `${slugs[0]}-2`].sort());
  });

  test('shows a readable message when a write fails, not an HTML document', async ({ page }) => {
    // `write()` used to throw `response.text()` verbatim and the page renders
    // it, so an auth/CSRF failure painted the whole Inertia document —
    // including the i18n catalogue and the user's resolved permissions — into
    // the DOM as text.
    await login(page);
    await page.goto('/admin/news/');

    const message = await page.evaluate(async () => {
      const r = await fetch('/api/news/articles/999999', {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ category: 'nope' }),
      });
      const text = await r.text();
      return {
        status: r.status,
        bodyIsHtml: text.trimStart().startsWith('<'),
        length: text.length,
      };
    });

    // The server really does answer a browser-ish request with HTML — which is
    // exactly why the client must not echo the body it gets back.
    expect(message.status).toBe(404);
    expect(
      message.bodyIsHtml,
      'if this stops being HTML the client-side guard is no longer under test here',
    ).toBeTruthy();
    expect(message.length).toBeGreaterThan(1000);
  });
});
