/**
 * The editor chrome a browser audit found wanting (#59): blank tab titles on
 * every pagebuilder screen, a page list wider than a phone, three save
 * controls on the layout editor, and seeded documents opening as "Untitled
 * page" because their stored document carries no root title.
 */

import { expect, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

test.describe('Pagebuilder editor chrome', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('every screen names its tab', async ({ page }) => {
    for (const [path, title] of [
      ['/pagebuilder/', 'Pages'],
      ['/pagebuilder/media', 'Media library'],
      ['/pagebuilder/layout', 'Site layout'],
      ['/pagebuilder/pending', 'Pending review'],
    ]) {
      await page.goto(path);
      await expect(page).toHaveTitle(new RegExp(`^${title}`));
    }
  });

  test('the page list fits a phone', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/pagebuilder/');
    await expect(page.getByRole('button', { name: /media library/i })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBe(0);
  });

  test('the layout editor has one save', async ({ page }) => {
    await page.goto('/pagebuilder/layout');
    await expect(page.getByRole('button', { name: 'Save layout' })).toHaveCount(1);
    await expect(page.getByTestId('layout-header-slot')).toBeVisible();
    // Puck renders its header Publish as a <span>, so match by text.
    await expect(page.getByText('Publish', { exact: true })).toHaveCount(0);
  });

  test('a document without a root title opens under the page title', async ({ page }) => {
    const title = `Seeded ${uniqueSlug('chrome')}`;
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers: await csrfHeader(page),
      data: { title, slug: uniqueSlug('chrome'), draft_data: { content: [], root: { props: {} } } },
    });
    expect(created.status(), await created.text()).toBe(201);
    const { id } = await created.json();

    await page.goto(`/pagebuilder/${id}/edit`);
    await expect(page).toHaveTitle(title);
    await expect(page.getByText('Untitled page')).toHaveCount(0);
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();

    // A title of only spaces falls back rather than going blank.
    await page.getByRole('textbox', { name: /title/i }).first().fill('   ');
    await expect(page).toHaveTitle('Untitled page');
  });
});
