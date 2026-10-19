import { expect, test } from '@playwright/test';

import { clickAndConfirm, login, publishWithNote, uniqueSlug } from './helpers';

/**
 * Issues #6 (CSP) + #26 (Cache-Control + ETag) — exercised end-to-end
 * against the running host. The Python unit tests cover header values
 * in isolation; this file rounds it out with a real HTTP round-trip,
 * including the ``If-None-Match`` → 304 short-circuit.
 *
 * Each test creates its own page so the suite can run in any order and
 * cleanup is self-contained.
 */
test.describe('Public viewer headers', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('published /p/{slug} emits ETag, Cache-Control, and CSP', async ({ browser, page }) => {
    const slug = uniqueSlug('hdr');
    await page.goto('/pagebuilder/new');
    await page.getByPlaceholder('Page title').fill(`Headers ${slug}`);
    await page.getByPlaceholder('slug').fill(slug);
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/, { timeout: 15_000 });
    await publishWithNote(page);
    await expect(page.getByText('Published.')).toBeVisible();

    const response = await page.request.get(`/p/${slug}`);
    expect(response.status()).toBe(200);
    const headers = response.headers();

    // Signed in: the page carries this user, so it is kept nowhere (#94).
    expect(headers['cache-control']).toBe('private, no-store');
    expect(headers['etag']).toBeUndefined();

    // Anonymous: shared-cacheable, keyed on what picks the language and the session.
    const anon = await browser.newContext();
    const anonymous = await anon.request.get(new URL(`/p/${slug}`, page.url()).toString());
    expect(anonymous.status()).toBe(200);
    expect(anonymous.headers().etag, 'ETag header missing').toMatch(/^W\/".+"$/);
    const cacheControl = anonymous.headers()['cache-control'];
    expect(cacheControl).toContain('public');
    expect(cacheControl).toMatch(/max-age=\d+/);
    expect(cacheControl).toMatch(/stale-while-revalidate=\d+/);
    expect(anonymous.headers().vary).toMatch(/Cookie/);
    expect(anonymous.headers().vary).toMatch(/Accept-Language/);
    await anon.close();

    // CSP header is injected for every published response; the host
    // overrides the default in dev to widen connect-src for Vite, so we
    // only assert the baseline restrictive directives are present.
    const csp = headers['content-security-policy'];
    expect(csp, 'CSP header missing').toBeTruthy();
    expect(csp).toContain("default-src 'self'");

    // Cleanup.
    // Teardown deletes through the table, so ask for it —
    // the board is the default view now.
    // Search for it: the table pages at 20 rows, so on a database with any
    // history the row would not be on the first page.
    await page.goto(`/pagebuilder/?view=list&search=${slug}`);
    await clickAndConfirm(
      page,
      page.locator('tr', { hasText: `Headers ${slug}` }).getByRole('button', { name: /^delete$/i }),
    );
  });

  test('conditional GET with If-None-Match returns 304', async ({ browser, page }) => {
    const slug = uniqueSlug('304');
    await page.goto('/pagebuilder/new');
    await page.getByPlaceholder('Page title').fill(`Cond ${slug}`);
    await page.getByPlaceholder('slug').fill(slug);
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/, { timeout: 15_000 });
    await publishWithNote(page);
    await expect(page.getByText('Published.')).toBeVisible();

    // A visitor: only an anonymous copy carries a validator (#94).
    const anon = await browser.newContext();
    const url = new URL(`/p/${slug}`, page.url()).toString();
    const first = await anon.request.get(url);
    expect(first.status()).toBe(200);
    const etag = first.headers()['etag'];
    expect(etag).toBeTruthy();

    const second = await anon.request.get(url, { headers: { 'if-none-match': etag } });
    expect(second.status()).toBe(304);
    // ETag must round-trip on the 304 so caches can keep their entry.
    expect(second.headers()['etag']).toBe(etag);
    await anon.close();

    // Cleanup.
    // Teardown deletes through the table, so ask for it —
    // the board is the default view now.
    // Search for it: the table pages at 20 rows, so on a database with any
    // history the row would not be on the first page.
    await page.goto(`/pagebuilder/?view=list&search=${slug}`);
    await clickAndConfirm(
      page,
      page.locator('tr', { hasText: `Cond ${slug}` }).getByRole('button', { name: /^delete$/i }),
    );
  });
});
