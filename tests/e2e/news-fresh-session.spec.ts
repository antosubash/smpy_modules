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
 * Creating an article posts to pagebuilder's CSRF-protected page API. A user
 * who clicks News in the sidebar and then "New article" has never requested a
 * pagebuilder path, so the cookie is unset and the POST used to come back 403
 * with no page and no article — the module's documented primary flow, broken
 * on a fresh login.
 */
test.describe('News — first visit of a session', () => {
  test('creates an article without having visited Pages first', async ({ page }) => {
    await login(page);

    // Straight to News. Nothing above may request a /pagebuilder path, or the
    // cookie gets primed and this test stops testing anything.
    await page.goto('/news/');
    await expect(page.getByRole('heading', { name: 'News' })).toBeVisible();

    const cookieBefore = (await page.context().cookies()).find(
      (c) => c.name === 'pagebuilder_csrf',
    );
    expect(cookieBefore, 'precondition: the CSRF cookie must not be primed yet').toBeUndefined();

    const title = `Fresh session ${Date.now().toString(36)}`;
    page.once('dialog', (dialog) => {
      expect(dialog.type()).toBe('prompt');
      dialog.accept(title);
    });
    await page.getByRole('button', { name: 'New article' }).click();

    // Success is landing in the editor for the page that was just created.
    await page.waitForURL(/\/pagebuilder\/\d+$/, { timeout: 15_000 });

    // And the article row exists, rather than a page with no metadata attached.
    await page.goto('/news/');
    await expect(page.getByRole('row', { name: new RegExp(title) })).toBeVisible();
  });

  test('shows a readable message when a write fails, not an HTML document', async ({ page }) => {
    // `write()` used to throw `response.text()` verbatim and the page renders
    // it, so an auth/CSRF failure painted the whole Inertia document —
    // including the i18n catalogue and the user's resolved permissions — into
    // the DOM as text.
    await login(page);
    await page.goto('/news/');

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
