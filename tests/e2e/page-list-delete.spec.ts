import { expect, type Page, test } from '@playwright/test';

import { login, makePage, uniqueSlug } from './helpers';

/**
 * Deleting a page from the list view asks for what the board card asks for: a
 * published page demands its slug typed, a draft keeps the one-click confirm.
 *
 * A protection only one of two doors honours is not a protection.
 */

test.describe('deleting a published page from the list view', () => {
  test('demands the slug typed, exactly as the board card does', async ({ page }) => {
    await login(page);
    const slug = uniqueSlug('qa-published-del');
    await makePage(page, { slug, publish: true });

    await page.goto(`/pagebuilder/?view=list&search=${slug}`);
    const row = page.locator('tr', { hasText: slug });
    await expect(row).toBeVisible();
    await row.getByRole('button', { name: /^delete$/i }).click();

    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();
    // Locked until the slug is typed — the live URL going dark is the design's
    // high blast radius wherever it is triggered from.
    await expect(dialog.getByRole('button', { name: /^delete$/i })).toBeDisabled();

    await dialog.locator('#confirm-dialog-phrase').fill('not-the-slug');
    await expect(dialog.getByRole('button', { name: /^delete$/i })).toBeDisabled();

    await dialog.locator('#confirm-dialog-phrase').fill(slug);
    await expect(dialog.getByRole('button', { name: /^delete$/i })).toBeEnabled();
  });

  test('a draft keeps the one-click confirm', async ({ page }) => {
    await login(page);
    const slug = uniqueSlug('qa-draft-del');
    await makePage(page, { slug });

    await page.goto(`/pagebuilder/?view=list&search=${slug}`);
    await page
      .locator('tr', { hasText: slug })
      .getByRole('button', { name: /^delete$/i })
      .click();

    const dialog = page.getByRole('alertdialog');
    await expect(dialog.locator('#confirm-dialog-phrase')).toHaveCount(0);
    await expect(dialog.getByRole('button', { name: /^delete$/i })).toBeEnabled();
    // And it says where the page actually goes, rather than "for good".
    await expect(dialog).toContainText(/trash for 30 days/i);
  });
});
