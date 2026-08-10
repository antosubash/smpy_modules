/**
 * Exercises the publish-note dialog + History "Compare" diff toggle
 * landed for issue #16. Drives the real editor through two publishes
 * with a metadata change between them so the diff has something to
 * report without us needing to interact with the Puck canvas.
 */

import { expect, test } from '@playwright/test';

import { cancelPublish, login, publishWithNote, uniqueSlug } from './helpers';

test.describe('Revisions: notes + compare diff', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('publish-with-note round-trip + Compare shows metadata diff', async ({ page }) => {
    const slug = uniqueSlug('rev');
    const titleA = `E2E rev ${slug} v1`;
    const titleB = `E2E rev ${slug} v2`;

    // ── Create + first publish (no note) ──────────────────────
    await page.goto('/pagebuilder/new');
    await page.getByPlaceholder('Page title').fill(titleA);
    await page.getByPlaceholder('slug').fill(slug);
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/, {
      timeout: 15_000,
    });

    // Publish without a note (empty textarea → no note recorded).
    await publishWithNote(page);
    await expect(page.getByText('Published.')).toBeVisible();

    // ── Rename + second publish (with note) ───────────────────
    await page.getByPlaceholder('Page title').fill(titleB);
    await publishWithNote(page, 'Rename v1 → v2');
    await expect(page.getByText('Published.')).toBeVisible();

    // ── History panel surfaces note ───────────────────────────
    await page.getByRole('button', { name: /history \(\d+\)/i }).click();
    await expect(page.getByText('Note: Rename v1 → v2')).toBeVisible();

    // ── Compare with previous revision ────────────────────────
    // The newest revision is the first <li>; click its Compare button.
    await page
      .getByRole('button', { name: /^compare$/i })
      .first()
      .click();

    const diffSummary = page.getByTestId('diff-summary');
    await expect(diffSummary).toBeVisible();
    await expect(diffSummary.getByText('Metadata')).toBeVisible();
    // Renamed title shows up in the metadata delta.
    await expect(diffSummary.locator('text=title').first()).toBeVisible();
    await expect(diffSummary.getByText(titleA, { exact: false })).toBeVisible();
    await expect(diffSummary.getByText(titleB, { exact: false })).toBeVisible();

    // ── Toggle: button flips to "Hide diff", clicking again closes ──
    const hideButton = page.getByRole('button', { name: /^hide diff$/i }).first();
    await expect(hideButton).toBeVisible();
    await hideButton.click();
    await expect(diffSummary).toHaveCount(0);
  });

  test('publish dialog Cancel aborts (no new revision)', async ({ page }) => {
    const slug = uniqueSlug('rev-cancel');
    await page.goto('/pagebuilder/new');
    await page.getByPlaceholder('Page title').fill(`Cancel ${slug}`);
    await page.getByPlaceholder('slug').fill(slug);
    await page.getByRole('button', { name: /save draft/i }).click();
    await expect(page).toHaveURL(/\/pagebuilder\/\d+\/edit$/, {
      timeout: 15_000,
    });

    // Snapshot revision count via the History button label, which
    // shows "History (N)" — should be 0 before publish.
    await expect(page.getByRole('button', { name: /history \(0\)/i })).toBeVisible();

    // Back out of the publish dialog → no publish happens.
    await cancelPublish(page);

    // Still 0 revisions, and no "Published." flash.
    await expect(page.getByRole('button', { name: /history \(0\)/i })).toBeVisible();
    await expect(page.getByText('Published.')).toHaveCount(0);
  });
});
