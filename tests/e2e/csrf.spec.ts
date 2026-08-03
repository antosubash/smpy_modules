import { expect, test } from '@playwright/test';

import { login, uniqueSlug } from './helpers';

/**
 * Issue #10 — CSRF protection.
 *
 * The token is per-session and surfaced two ways:
 *  - Inertia shared prop ``csrf.token`` on every admin Inertia view.
 *  - Non-``HttpOnly`` cookie ``pagebuilder_csrf`` (``SameSite=Strict``,
 *    ``Path=/``) that ``utils/api.ts`` reads via ``document.cookie`` and
 *    sends as ``X-CSRF-Token`` on every mutating request.
 *
 * These tests assert the cookie metadata, the prop ↔ cookie pairing,
 * the 403 path when the header is missing/wrong, and the end-to-end
 * flow through the UI's own ``fetch`` wrapper.
 */
test.describe('CSRF protection', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('admin view sets the pagebuilder_csrf cookie with safe defaults', async ({
    page,
    context,
  }) => {
    await page.goto('/pagebuilder/');
    const cookies = await context.cookies();
    const csrf = cookies.find((c) => c.name === 'pagebuilder_csrf');
    expect(csrf, 'pagebuilder_csrf cookie missing on admin view').toBeDefined();
    // SameSite=Strict prevents the cookie from leaking on cross-site nav.
    expect(csrf!.sameSite).toBe('Strict');
    // Must be readable by JS — that's the whole point: utils/api.ts reads
    // it via document.cookie. HttpOnly would defeat the design.
    expect(csrf!.httpOnly).toBe(false);
    expect(csrf!.path).toBe('/');
    expect(csrf!.value.length).toBeGreaterThan(20);
  });

  test('cookie value matches the csrf.token Inertia shared prop', async ({ page, context }) => {
    await page.goto('/pagebuilder/');
    const inertiaToken = await page.evaluate(() => {
      const el = document.getElementById('app');
      const raw = el?.getAttribute('data-page') ?? '{}';
      const data = JSON.parse(raw) as { props?: { csrf?: { token?: string } } };
      return data.props?.csrf?.token ?? null;
    });
    const cookies = await context.cookies();
    const cookieToken = cookies.find((c) => c.name === 'pagebuilder_csrf')?.value;
    expect(inertiaToken).toBeTruthy();
    expect(cookieToken).toBe(inertiaToken);
  });

  test('POST without X-CSRF-Token is rejected with 403', async ({ page }) => {
    await page.goto('/pagebuilder/');
    // ``page.request`` shares the auth cookie + session cookie but lets
    // us craft the request manually so we can omit the CSRF header.
    const response = await page.request.post('/api/pagebuilder/pages', {
      data: { title: 'no-csrf', slug: uniqueSlug('no-csrf'), draft_data: {} },
      headers: { 'content-type': 'application/json' },
    });
    expect(response.status()).toBe(403);
    expect(await response.text()).toContain('CSRF');
  });

  test('POST with a wrong X-CSRF-Token is rejected with 403', async ({ page }) => {
    await page.goto('/pagebuilder/');
    const response = await page.request.post('/api/pagebuilder/pages', {
      data: { title: 'wrong', slug: uniqueSlug('wrong'), draft_data: {} },
      headers: {
        'content-type': 'application/json',
        'x-csrf-token': 'definitely-not-the-real-token',
      },
    });
    expect(response.status()).toBe(403);
  });

  test('POST with the cookie token succeeds (constant-time match)', async ({ page, context }) => {
    await page.goto('/pagebuilder/');
    const token = (await context.cookies()).find((c) => c.name === 'pagebuilder_csrf')!.value;
    const slug = uniqueSlug('csrf-ok');
    const response = await page.request.post('/api/pagebuilder/pages', {
      data: { title: 'csrf ok', slug, draft_data: {} },
      headers: {
        'content-type': 'application/json',
        'x-csrf-token': token,
      },
    });
    expect(response.status()).toBe(201);
    // Clean up the page so the test is idempotent.
    const created = (await response.json()) as { id: number };
    const del = await page.request.delete(`/api/pagebuilder/pages/${created.id}`, {
      headers: { 'x-csrf-token': token },
    });
    expect(del.status()).toBe(204);
  });

  test('the editor UI sends the token automatically (full save round-trip)', async ({ page }) => {
    // The whole point of the cookie route: utils/api.ts reads
    // document.cookie and attaches X-CSRF-Token to every fetch. If that
    // wiring breaks, "Save draft" 403s and the editor never reaches
    // /pagebuilder/<id>/edit. The pagebuilder.spec.ts CRUD test
    // already exercises this implicitly; here we assert it explicitly
    // with an isolated, minimal flow so a regression is easier to bisect.
    const slug = uniqueSlug('csrf-ui');
    await page.goto('/pagebuilder/new');
    await page.getByPlaceholder('Page title').fill(`CSRF UI ${slug}`);
    await page.getByPlaceholder('slug').fill(slug);
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/, { timeout: 15_000 });

    // Clean up.
    await page.goto('/pagebuilder/');
    page.once('dialog', (dialog) => dialog.accept());
    await page
      .locator('tr', { hasText: `CSRF UI ${slug}` })
      .getByRole('button', { name: /^delete$/i })
      .click();
  });
});
