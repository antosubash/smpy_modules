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

  test('published /p/{slug} emits ETag, Cache-Control, and CSP', async ({ page }) => {
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

    const etag = headers['etag'];
    expect(etag, 'ETag header missing').toBeTruthy();
    expect(etag).toMatch(/^W\/".+"$/);

    const cacheControl = headers['cache-control'];
    expect(cacheControl).toContain('public');
    expect(cacheControl).toMatch(/max-age=\d+/);
    expect(cacheControl).toMatch(/stale-while-revalidate=\d+/);

    // CSP header is injected for every published response; the host
    // overrides the default in dev to widen connect-src for Vite, so we
    // only assert the baseline restrictive directives are present.
    const csp = headers['content-security-policy'];
    expect(csp, 'CSP header missing').toBeTruthy();
    expect(csp).toContain("default-src 'self'");

    // Cleanup.
    // Teardown deletes through the table, so ask for it —
    // the board is the default view now.
    await page.goto('/pagebuilder/?view=list');
    await clickAndConfirm(
      page,
      page.locator('tr', { hasText: `Headers ${slug}` }).getByRole('button', { name: /^delete$/i }),
    );
  });

  test('conditional GET with If-None-Match returns 304', async ({ page }) => {
    const slug = uniqueSlug('304');
    await page.goto('/pagebuilder/new');
    await page.getByPlaceholder('Page title').fill(`Cond ${slug}`);
    await page.getByPlaceholder('slug').fill(slug);
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/, { timeout: 15_000 });
    await publishWithNote(page);
    await expect(page.getByText('Published.')).toBeVisible();

    const first = await page.request.get(`/p/${slug}`);
    expect(first.status()).toBe(200);
    const etag = first.headers()['etag'];
    expect(etag).toBeTruthy();

    const second = await page.request.get(`/p/${slug}`, {
      headers: { 'if-none-match': etag },
    });
    expect(second.status()).toBe(304);
    // ETag must round-trip on the 304 so caches can keep their entry.
    expect(second.headers()['etag']).toBe(etag);

    // Cleanup.
    // Teardown deletes through the table, so ask for it —
    // the board is the default view now.
    await page.goto('/pagebuilder/?view=list');
    await clickAndConfirm(
      page,
      page.locator('tr', { hasText: `Cond ${slug}` }).getByRole('button', { name: /^delete$/i }),
    );
  });
});
