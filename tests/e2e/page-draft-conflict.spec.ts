import { expect, test } from '@playwright/test';

import { login, moduleCsrfHeader, uniqueSlug } from './helpers';

test('stale draft autosave pauses, Reload discards and Overwrite deliberately saves', async ({
  page,
}) => {
  await login(page);
  const headers = await moduleCsrfHeader(page, '/pagebuilder/');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: { title: 'Original', slug: uniqueSlug('draft-conflict'), draft_data: { content: [] } },
  });
  expect(created.status(), await created.text()).toBe(201);
  const { id, updated_at: loadedVersion } = await created.json();
  const path = `/api/pagebuilder/pages/${id}`;
  await page.goto(`/pagebuilder/${id}/edit`);
  const title = page.getByPlaceholder('Page title');
  await expect(title).toHaveValue('Original');

  // A second editor writes after this screen loaded its base.
  const other = await page.request.put(path, {
    headers,
    data: { title: 'Other editor', expected_updated_at: loadedVersion },
  });
  expect(other.ok(), await other.text()).toBe(true);
  const conflict = page.waitForResponse(
    (r) => r.url().endsWith(`/pages/${id}`) && r.status() === 409,
  );
  await title.fill('Local draft');
  expect((await conflict).status()).toBe(409);
  const banner = page.getByRole('alert').filter({ hasText: 'This page was changed elsewhere' });
  await expect(banner).toBeVisible();
  await title.fill('Still editing locally');
  // Past the debounce: the stale client must leave the other editor's work alone.
  await page.waitForTimeout(2500);
  expect((await (await page.request.get(path)).json()).title).toBe('Other editor');

  await banner.getByRole('button', { name: 'Reload', exact: true }).click();
  await expect(title).toHaveValue('Other editor');
  await expect(banner).toHaveCount(0);

  await page.request.put(path, { headers, data: { title: 'Another external edit' } });
  await title.fill('Keep mine deliberately');
  await expect(banner).toBeVisible();
  const overwritten = page.waitForResponse(
    (r) => r.url().endsWith(`/pages/${id}`) && r.request().method() === 'PUT' && r.ok(),
  );
  await banner.getByRole('button', { name: 'Overwrite', exact: true }).click();
  const saved = await overwritten;
  expect(saved.request().postDataJSON()).not.toHaveProperty('expected_updated_at');
  await expect(banner).toHaveCount(0);
  expect((await (await page.request.get(path)).json()).title).toBe('Keep mine deliberately');

  const resumed = page.waitForResponse(
    (r) => r.url().endsWith(`/pages/${id}`) && r.request().method() === 'PUT' && r.ok(),
  );
  await title.fill('After overwrite');
  const guarded = await resumed;
  expect(guarded.request().postDataJSON().expected_updated_at).toBe(
    (await saved.json()).updated_at,
  );
});
