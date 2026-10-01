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
 * Creating an article once POSTed to pagebuilder's CSRF-protected page API from
 * the browser. A user who clicked News in the sidebar and then "New article"
 * had never requested a pagebuilder path, so the cookie was unset and the POST
 * came back 403 with no page and no article — the module's documented primary
 * flow, broken on a fresh login. It then became one request to news' own API,
 * which created the page and attached the article server-side.
 *
 * There is no page in it at all now. The cookie assertion below is kept even so:
 * it is the cheapest possible statement that this flow touches nothing of
 * pagebuilder's, and it would fail the moment something reached back across.
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

    // Success is landing in the body canvas for the article just created —
    // news' own screen, where it used to be `/pagebuilder/{id}/edit`.
    await page.waitForURL(/\/admin\/news\/articles\/\d+\/body$/, { timeout: 15_000 });
    // Assert on the canvas itself, not on the absence of "Not Found": a
    // toHaveCount(0) passes on its first poll and so cannot catch an error
    // page that renders a moment after the URL settles. The toolbar carries
    // the article's title, so this proves both that the screen mounted and
    // that it opened the article just created.
    //
    // Located by test id rather than by text: Puck renders the document title
    // in its own header as well, so a text locator matches twice.
    await expect(page.getByTestId('article-body-title')).toHaveText(title);

    // And the article row exists. Rows are cards, not table rows.
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
      await page.waitForURL(/\/admin\/news\/articles\/\d+\/body$/, { timeout: 20_000 });
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
        headers: { Accept: 'text/html', 'Content-Type': 'application/json' },
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
    // exactly why the client must not echo the body it gets back. Since
    // framework 0.0.35 it answers `Accept: application/json` with JSON (#346),
    // so the request asks for HTML to keep the HTML body under test.
    expect(message.status).toBe(404);
    expect(
      message.bodyIsHtml,
      'if this stops being HTML the client-side guard is no longer under test here',
    ).toBeTruthy();
    expect(message.length).toBeGreaterThan(1000);
  });
});
