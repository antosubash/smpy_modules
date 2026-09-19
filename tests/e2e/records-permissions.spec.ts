import { type Browser, expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import { apiCreateType, uniqueTypeKey } from './records-helpers';

/**
 * Who may reach the Records admin.
 *
 * `sm_records/deps.py` guards the whole view router with `records.view` and
 * every schema route with `records.manage_types` (design §10's three static
 * permissions).
 *
 * **A narrower role could not be built from the browser.** This host seeds
 * exactly one role row (`admin`); `PUT /api/users/admin/{id}/roles` only
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
    const key = uniqueTypeKey('perm');
    await apiCreateType(page, {
      key,
      label: 'Guarded',
      fields: [{ key: 'title', type: 'text', label: 'Title', indexed: true }],
      display_field: 'title',
    });
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
        await expect(other.getByRole('heading', { name: '403' })).toBeVisible();
        await expect(other.getByText('Permission required: records.')).toBeVisible();
      }

      // …and the JSON API refuses the same session, so the screens are not
      // the only thing standing in the way.
      const listed = await other.request.get('/api/records/types');
      expect(listed.status()).toBe(403);
      const created = await other.request.post('/api/records/types', {
        headers: { 'content-type': 'application/json' },
        data: { key: uniqueTypeKey('nope'), label: 'Nope' },
      });
      expect(created.status()).toBe(403);
    } finally {
      await other.context().close();
    }
  });

  test('the Records entry is absent from that user’s admin sidebar', async ({ page, browser }) => {
    await login(page);
    const who = await createPlainUser(page);

    const other = await asUser(browser, who);
    try {
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

  test('admin, holding every permission, reaches the schema editor', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('adm');
    await apiCreateType(page, {
      key,
      label: 'Reachable',
      fields: [{ key: 'title', type: 'text', label: 'Title', indexed: true }],
      display_field: 'title',
    });
    await page.goto(`/admin/records/types/${key}`);
    await expect(page.getByRole('heading', { name: 'Reachable' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Delete this type' })).toBeVisible();
  });
});
