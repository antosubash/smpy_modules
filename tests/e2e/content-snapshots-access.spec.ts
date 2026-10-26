import { type Browser, expect, type Page, test } from '@playwright/test';

import { login, moduleCsrfHeader } from './helpers';

/**
 * Who reaches Import / Export.
 *
 * A snapshot's note, creator and manifest are for whoever may stage or approve
 * a restore, so the screen, its API and its sidebar entry all ask for
 * `pagebuilder.publish` or `pagebuilder.approve`. An approver without publish
 * sees the list and the staged restore, and none of the publish controls.
 *
 * Stands alone (CI shards by file): it creates its own users and snapshot, and
 * clears the site-wide pending import first.
 */

const CONTENT = '/pagebuilder/content';

async function userWith(admin: Page, browser: Browser, permissions: string[]): Promise<Page> {
  const email = `snap-access-${Date.now().toString(36)}-${permissions.length}@example.com`;
  const password = 'changeme1';
  const created = await admin.request.post('/api/users/admin', {
    headers: { 'content-type': 'application/json' },
    data: { email, password, role_names: [] },
  });
  expect(created.status(), await created.text()).toBe(201);
  const users = (await (await admin.request.get('/api/users/admin?per_page=100')).json()) as {
    id: string;
    email: string;
  }[];
  const id = users.find((u) => u.email === email)?.id;
  expect(id, 'the user just created should be listed').toBeTruthy();
  const granted = await admin.request.put(`/api/permissions/users/${id}`, {
    headers: { 'content-type': 'application/json' },
    data: { permissions },
  });
  expect(granted.status()).toBe(200);

  const page = await (await browser.newContext()).newPage();
  await login(page, { email, password });
  return page;
}

async function stageRestore(admin: Page, note: string) {
  const headers = await moduleCsrfHeader(admin, '/pagebuilder/');
  const pending = await (await admin.request.get('/api/pagebuilder/imports/pending')).json();
  if (pending) {
    await admin.request.post(`/api/pagebuilder/imports/${pending.id}/reject`, {
      headers,
      data: { note: 'clearing before e2e' },
    });
  }
  const taken = await admin.request.post('/api/pagebuilder/snapshots', {
    headers,
    data: { note },
  });
  expect(taken.status(), await taken.text()).toBe(201);
  const { id } = (await taken.json()) as { id: number };
  const staged = await admin.request.post(`/api/pagebuilder/snapshots/${id}/restore`, { headers });
  expect(staged.status(), await staged.text()).toBe(201);
}

test.describe('Import / Export access', () => {
  test('a user without publish or approve is not offered it and cannot open it', async ({
    page,
    browser,
  }) => {
    await login(page);
    const reader = await userWith(page, browser, ['pagebuilder.edit']);

    await reader.goto('/pagebuilder/');
    const sidebar = reader.getByRole('complementary');
    await expect(sidebar.getByRole('link', { name: 'Pages', exact: true })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Import / Export', exact: true })).toHaveCount(
      0,
    );

    const screen = await reader.goto(CONTENT);
    expect(screen?.status()).toBe(403);
    const api = await reader.request.get('/api/pagebuilder/snapshots');
    expect(api.status()).toBe(403);
  });

  test('an approver sees the list and the staged restore, but no publish controls', async ({
    page,
    browser,
  }) => {
    await login(page);
    const note = `access-e2e-${Date.now().toString(36)}`;
    await stageRestore(page, note);
    const approver = await userWith(page, browser, ['pagebuilder.approve']);

    await approver.goto('/pagebuilder/');
    await approver
      .getByRole('complementary')
      .getByRole('link', { name: 'Import / Export', exact: true })
      .click();
    await expect(approver).toHaveURL(new RegExp(`${CONTENT}$`));
    await expect(approver.getByText(note)).toBeVisible();
    await expect(approver.getByRole('link', { name: 'Review it' })).toBeVisible();
    for (const name of ['Take snapshot', 'Upload bundle…', 'Restore…', 'Delete', 'Download']) {
      await expect(approver.getByRole('button', { name, exact: true })).toHaveCount(0);
      await expect(approver.getByRole('link', { name, exact: true })).toHaveCount(0);
    }

    // The admin, holding both, still has every control.
    await page.goto(CONTENT);
    await expect(page.getByRole('button', { name: 'Take snapshot' })).toBeVisible();
  });
});
