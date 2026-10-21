import { expect, test } from '@playwright/test';

import { login, moduleCsrfHeader } from './helpers';

/**
 * #126 — the AI settings API checks the framework's `RequiresCsrf`, like
 * every other module. Its writes are the settings save and the two slot
 * probes. The settings page shares the token as the `csrf_token` prop and
 * `utils/api.ts` sends it; the `sm_ai_csrf` cookie it used to read is gone.
 */
test.describe('CSRF protection — ai', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  for (const [method, path, data] of [
    ['PUT', '/api/ai/settings', {}],
    ['POST', '/api/ai/test', { slot: 'chat' }],
    ['POST', '/api/ai/models', { slot: 'chat' }],
  ] as const) {
    test(`${method} ${path} without the token is refused with 403`, async ({ page }) => {
      const response = await page.request.fetch(path, { method, data });
      expect(response.status()).toBe(403);
      expect(await response.text()).toContain('CSRF');
    });
  }

  test("a wrong token is refused, and the screen's token is accepted", async ({
    page,
    context,
  }) => {
    const wrong = await page.request.put('/api/ai/settings', {
      data: {},
      headers: { 'X-CSRF-Token': 'definitely-not-the-real-token' },
    });
    expect(wrong.status()).toBe(403);
    // An empty update changes nothing, so the shared database is left alone.
    const ok = await page.request.put('/api/ai/settings', {
      data: {},
      headers: await moduleCsrfHeader(page, '/ai/'),
    });
    expect(ok.status(), await ok.text()).toBe(200);
    expect((await context.cookies()).map((c) => c.name)).not.toContain('sm_ai_csrf');
  });

  test('a stale token on save reads as "reload"', async ({ page }) => {
    await page.goto('/ai/');
    await expect(page.getByRole('heading', { name: 'AI' })).toBeVisible();
    // What a session that changed under an open tab looks like to the server.
    await page.route('**/api/ai/settings', (route) =>
      route.request().method() === 'PUT'
        ? route.continue({ headers: { ...route.request().headers(), 'x-csrf-token': 'stale' } })
        : route.continue(),
    );
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText(/security token is out of date/)).toBeVisible();
  });
});
