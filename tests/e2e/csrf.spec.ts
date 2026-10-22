import { expect, test } from '@playwright/test';

import { clickAndConfirm, login, moduleCsrfHeader, uniqueSlug } from './helpers';

/** 1×1 transparent PNG — the upload endpoint sniffs content, not the name. */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
);

/**
 * Issue #10, #126 — pagebuilder's CSRF protection.
 *
 * The check is the framework's `RequiresCsrf`, the one every module uses
 * since #126. Every pagebuilder screen shares the session's token as the
 * `csrf_token` Inertia prop; `utils/csrf.ts` keeps it and the fetch and
 * upload helpers send it as `X-CSRF-Token`. The `pagebuilder_csrf` cookie and
 * the middleware that mirrored it are gone. The AI module's half is in
 * `csrf-ai.spec.ts`.
 */
test.describe('CSRF protection — pagebuilder', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('the screen shares the token as a prop, and no cookie mirrors it', async ({
    page,
    context,
  }) => {
    await page.goto('/pagebuilder/');
    const prop = await page.evaluate(() => {
      const raw = document.querySelector('script[data-page="app"]')?.textContent ?? '{}';
      return (JSON.parse(raw) as { props?: { csrf_token?: string } }).props?.csrf_token ?? '';
    });
    expect(prop.length).toBeGreaterThan(20);
    const names = (await context.cookies()).map((c) => c.name);
    expect(names).not.toContain('pagebuilder_csrf');
  });

  test('a write without the token is refused with 403 and creates nothing', async ({ page }) => {
    const slug = uniqueSlug('no-csrf');
    const response = await page.request.post('/api/pagebuilder/pages', {
      data: { title: 'no-csrf', slug, draft_data: {} },
    });
    expect(response.status()).toBe(403);
    expect(await response.text()).toContain('CSRF');
    const listed = await page.request.get(`/api/pagebuilder/pages?search=${slug}`);
    expect(((await listed.json()) as { items: unknown[] }).items).toEqual([]);
  });

  test('a wrong token is refused with 403', async ({ page }) => {
    const response = await page.request.post('/api/pagebuilder/pages', {
      data: { title: 'wrong', slug: uniqueSlug('wrong'), draft_data: {} },
      headers: { 'X-CSRF-Token': 'definitely-not-the-real-token' },
    });
    expect(response.status()).toBe(403);
  });

  test('a media upload needs the token too', async ({ page }) => {
    const file = { name: `${uniqueSlug('csrf')}.png`, mimeType: 'image/png', buffer: PNG };
    const refused = await page.request.post('/api/pagebuilder/uploads', { multipart: { file } });
    expect(refused.status()).toBe(403);

    const headers = await moduleCsrfHeader(page, '/pagebuilder/');
    const accepted = await page.request.post('/api/pagebuilder/uploads', {
      multipart: { file },
      headers,
    });
    expect(accepted.status(), await accepted.text()).toBe(201);
    const { id } = (await accepted.json()) as { id: number };
    const removed = await page.request.delete(`/api/pagebuilder/uploads/${id}`, { headers });
    expect(removed.ok()).toBe(true);
  });

  test("the screen's token is accepted — and so is any module screen's", async ({ page }) => {
    // One framework token per session: the news screen's opens pagebuilder too.
    const headers = await moduleCsrfHeader(page, '/admin/news/');
    expect(headers).toEqual(await moduleCsrfHeader(page, '/pagebuilder/'));
    const response = await page.request.post('/api/pagebuilder/pages', {
      data: { title: 'csrf ok', slug: uniqueSlug('csrf-ok'), draft_data: {} },
      headers,
    });
    expect(response.status()).toBe(201);
    const created = (await response.json()) as { id: number };
    const del = await page.request.delete(`/api/pagebuilder/pages/${created.id}`, { headers });
    expect(del.status()).toBe(204);
  });

  test('the editor UI sends the token automatically (full save round-trip)', async ({ page }) => {
    // If the client stops sending the token, "Save draft" 403s and the editor
    // never reaches /pagebuilder/<id>/edit. Every UI-driven pagebuilder spec
    // exercises this implicitly; this one isolates it so a regression is easy
    // to bisect.
    const slug = uniqueSlug('csrf-ui');
    await page.goto('/pagebuilder/new');
    await page.getByPlaceholder('Page title').fill(`CSRF UI ${slug}`);
    await page.getByPlaceholder('slug').fill(slug);
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/, { timeout: 15_000 });

    // Clean up through the table (the board is the default view), searching
    // so the row is on the first page whatever else the database holds.
    await page.goto(`/pagebuilder/?view=list&search=${slug}`);
    await clickAndConfirm(
      page,
      page.locator('tr', { hasText: `CSRF UI ${slug}` }).getByRole('button', { name: /^delete$/i }),
    );
  });

  test('a stale token on an upload reads as "reload", not as a missing permission', async ({
    page,
  }) => {
    await page.goto('/pagebuilder/media');
    // What a session that changed under an open tab looks like to the server.
    await page.route('**/api/pagebuilder/uploads', (route) =>
      route.continue({ headers: { ...route.request().headers(), 'x-csrf-token': 'stale' } }),
    );
    await page
      .locator('input[type=file]')
      .first()
      .setInputFiles({ name: `${uniqueSlug('stale')}.png`, mimeType: 'image/png', buffer: PNG });
    await expect(
      page.locator('[data-sonner-toast]').getByText(/security token is out of date/),
    ).toBeVisible();
    await expect(page.getByText(/do not have permission to upload/)).toHaveCount(0);
  });
});

/**
 * #110, #111 — news' and records' admin APIs check the framework's
 * `RequiresCsrf`. Their screens share the token as the `csrf_token` Inertia
 * prop (`moduleCsrfHeader` reads it), and the console's own clients send it
 * back: the UI-driven news and records specs exercise that path on every save.
 */
const MODULE_WRITES = [
  {
    name: 'news',
    view: '/admin/news/' as const,
    create: () => ({
      url: '/api/news/articles',
      data: { title: 'CSRF news', slug: uniqueSlug('csrf-news') },
      remove: (body: { id: number }) => `/api/news/articles/${body.id}`,
    }),
  },
  {
    name: 'records',
    view: '/admin/records/' as const,
    create: () => {
      const key = uniqueSlug('csrf').replace(/-/g, '_').toLowerCase();
      return {
        url: '/api/records/types',
        data: { key, label: `CSRF ${key}`, fields: [{ key: 'title', type: 'text', label: 'T' }] },
        remove: () => `/api/records/types/${key}?confirm_record_count=0`,
      };
    },
  },
];

test.describe('CSRF protection — news and records', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  for (const mod of MODULE_WRITES) {
    test(`${mod.name}: a write without the token is refused with 403`, async ({ page }) => {
      await page.goto(mod.view);
      const { url, data } = mod.create();
      const response = await page.request.post(url, { data });
      expect(response.status()).toBe(403);
      expect(await response.text()).toContain('CSRF');
    });

    test(`${mod.name}: a wrong token is refused with 403`, async ({ page }) => {
      const { url, data } = mod.create();
      const response = await page.request.post(url, {
        data,
        headers: { 'X-CSRF-Token': 'definitely-not-the-real-token' },
      });
      expect(response.status()).toBe(403);
    });

    test(`${mod.name}: the screen's token is accepted, on create and delete`, async ({ page }) => {
      const headers = await moduleCsrfHeader(page, mod.view);
      const { url, data, remove } = mod.create();
      const created = await page.request.post(url, { data, headers });
      expect(created.status(), await created.text()).toBe(201);
      const target = remove(await created.json());
      expect((await page.request.delete(target)).status()).toBe(403);
      expect((await page.request.delete(target, { headers })).status()).toBe(204);
    });
  }
});
