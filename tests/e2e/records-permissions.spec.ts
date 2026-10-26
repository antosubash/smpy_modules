import { type Browser, expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import { apiCreateType, seedTextType, uniqueTypeKey } from './records-helpers';

/**
 * Who may reach the Records admin.
 *
 * `sm_records/deps.py` guards the whole view router with `records.view` and
 * every schema route with `records.manage_types` (design §10's three static
 * permissions).
 *
 * **A narrower role could not be built from the browser.** This host seeds
 * two role rows (`admin`, and since framework 0.0.37 `user`, which holds no
 * records permission); `PUT /api/users/admin/{id}/roles` only
 * resolves role *names that already exist*, and nothing in the users or
 * permissions API creates one. So "a role with `records.view` but not
 * `records.manage_types`" is not constructible here, and the closest
 * reachable case — a real second user holding neither — is what these tests
 * drive, with the API-level expectations alongside the screens. See the
 * REPORT for the gap this leaves.
 */

type Credentials = { email: string; password: string };

async function createPlainUser(page: Page): Promise<Credentials> {
  const email = `records-e2e-${Date.now().toString(36)}@example.com`;
  const password = 'changeme1';
  const response = await page.request.post('/api/users/admin', {
    headers: { 'content-type': 'application/json' },
    data: { email, password, role_names: [] },
  });
  expect(response.status(), await response.text()).toBe(201);
  return { email, password };
}

async function asUser(browser: Browser, who: Credentials): Promise<Page> {
  const context = await browser.newContext();
  const page = await context.newPage();
  await login(page, who);
  return page;
}

test.describe('Records — permissions', () => {
  test('a user without records permissions is refused every records screen', async ({
    page,
    browser,
  }) => {
    await login(page);
    const key = await seedTextType(page, 'perm', { label: 'Guarded' });
    const who = await createPlainUser(page);

    const other = await asUser(browser, who);
    try {
      for (const path of [
        '/admin/records/',
        '/admin/records/types/new',
        `/admin/records/types/${key}`,
        `/admin/records/${key}`,
        `/admin/records/${key}/new`,
      ]) {
        await other.goto(path);
        // The framework's error page (the host's Error.tsx re-exports it, #89):
        // a "No access" heading naming the records permission the role lacks.
        await expect(other.getByRole('heading', { name: 'No access', level: 1 })).toBeVisible();
        await expect(other.locator('main code', { hasText: /^records\./ })).toBeVisible();
      }

      // …and the JSON API refuses the same session, so the screens are not
      // the only thing standing in the way. The write's 403 now comes from the
      // CSRF check (#111), which runs before the permission check: a user no
      // records screen will render for is never handed a token to send. That a
      // valid token still meets the permission check is proven in pytest
      // (modules/records/tests/test_csrf_permissions.py).
      const listed = await other.request.get('/api/records/types');
      expect(listed.status()).toBe(403);
      const created = await other.request.post('/api/records/types', {
        headers: { 'content-type': 'application/json' },
        data: { key: uniqueTypeKey('nope'), label: 'Nope' },
      });
      expect(created.status()).toBe(403);

      // Nor does the admin sidebar offer that user a way in.
      await other.goto('/dashboard/');
      await expect(other.getByRole('link', { name: 'Records', exact: true })).toHaveCount(0);
    } finally {
      await other.context().close();
    }
  });

  test('a direct records.view grant opens the module for that user', async ({ page, browser }) => {
    await login(page);
    const who = await createPlainUser(page);
    const listed = await page.request.get('/api/users/admin?per_page=100');
    const users = (await listed.json()) as { id: string; email: string }[];
    const id = users.find((u) => u.email === who.email)?.id;
    expect(id, 'the user just created should be listed').toBeTruthy();

    // The permissions screen writes exactly this: a per-user grant with no
    // role behind it.
    const granted = await page.request.put(`/api/permissions/users/${id}`, {
      headers: { 'content-type': 'application/json' },
      data: { permissions: ['records.view'] },
    });
    expect(granted.status()).toBe(200);

    const other = await asUser(browser, who);
    try {
      await other.goto('/admin/records/');
      await expect(other.getByRole('heading', { name: 'Record Types' })).toBeVisible();
    } finally {
      await other.context().close();
    }
  });

  test('a narrowed type is listed in the role editor, and its grant opens it', async ({
    page,
    browser,
  }) => {
    await login(page);
    const key = uniqueTypeKey('pertype');
    const plural = `Per-type things ${key}`;
    await apiCreateType(page, {
      key,
      label: `Per-type thing ${key}`,
      label_plural: plural,
      allowed_roles: ['admin'],
      show_in_menu: true,
    });

    // The role editor's own list (#92, upstream #334): the type's permission,
    // labelled with the narrowing it widens.
    const groups = (await (await page.request.get('/api/permissions/')).json()) as {
      name: string;
      permissions: string[];
      labels: Record<string, string>;
    }[];
    const records = groups.find((g) => g.name === 'records');
    const perm = `records.type.${key}`;
    expect(records?.permissions).toContain(perm);
    expect(records?.labels[perm]).toBe(`Records: ${plural} (restricted to admin)`);

    const who = await createPlainUser(page);
    const listed = await page.request.get('/api/users/admin?per_page=100');
    const users = (await listed.json()) as { id: string; email: string }[];
    const id = users.find((u) => u.email === who.email)?.id;
    expect(id).toBeTruthy();
    const grant = (permissions: string[]) =>
      page.request.put(`/api/permissions/users/${id}`, {
        headers: { 'content-type': 'application/json' },
        data: { permissions },
      });

    const other = await asUser(browser, who);
    try {
      // records.view alone: allowed_roles shuts them out, and no sidebar link.
      expect((await grant(['records.view'])).status()).toBe(200);
      const refused = await other.goto(`/admin/records/${key}`);
      expect(refused?.status()).toBe(403);
      await other.goto('/admin/records/');
      await expect(
        other.locator('aside').getByRole('link', { name: plural, exact: true }),
      ).toHaveCount(0);

      // Plus the per-type permission: the list opens and the entry appears.
      expect((await grant(['records.view', perm])).status()).toBe(200);
      await other.goto('/admin/records/');
      const link = other.locator('aside').getByRole('link', { name: plural, exact: true });
      await expect(link).toBeVisible();
      await link.click();
      await expect(other).toHaveURL(new RegExp(`/admin/records/${key}$`));
    } finally {
      await other.context().close();
    }
  });
});
