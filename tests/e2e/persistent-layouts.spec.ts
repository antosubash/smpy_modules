import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import { apiListRecords, recordField, seedTextType } from './records-helpers';

/**
 * Every module admin page declares an Inertia v3 persistent layout
 * (`Page.layout = [AuthenticatedLayout]`, records' `[RecordsLayout]`) instead
 * of wrapping itself in the shell at render time. Two things follow, and both
 * are invisible to a unit test: each page renders inside exactly one shell —
 * a page that both wraps itself and declares a layout would show two — and
 * moving between pages that share a layout keeps the shell mounted, so the
 * sidebar is not torn down and rebuilt on every click.
 */

const SHELLED_PAGES = [
  '/admin/news/',
  '/admin/news/categories',
  '/admin/news/trash',
  '/admin/search',
  '/pagebuilder/',
  '/pagebuilder/media',
  '/pagebuilder/pending',
  '/pagebuilder/trash',
  '/pagebuilder/content',
  '/ai/',
  '/admin/records/',
  '/admin/billing/plans',
];

/** The shell is `SidebarLayout`: its fixed `<aside>` sidebar beside one `<main>`.
 *  Matched by the sidebar's own classes — pages render `<aside>` panels of
 *  their own (the media library's folder list, for one). */
const SIDEBAR = 'aside.fixed.inset-y-0';

async function expectOneShell(page: Page) {
  await expect(page.locator('main')).toHaveCount(1);
  await expect(page.locator(SIDEBAR)).toHaveCount(1);
  await expect(page.locator('main h1').first()).toBeVisible();
}

test.describe('Persistent layouts', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('every module admin page renders inside exactly one shell', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    for (const url of SHELLED_PAGES) {
      await page.goto(url);
      await expectOneShell(page);
    }
    expect(errors).toEqual([]);
  });

  test('records: one shell, the layout toaster, and one record per burst of Saves', async ({
    page,
  }) => {
    const key = await seedTextType(page, 'layout', { label: 'Layout check' });
    await page.goto(`/admin/records/${key}/new`);
    await expectOneShell(page);
    await recordField(page, 'title').fill('Burst');

    // QA found five quick clicks created two records: `pending` disabled the
    // button a render late. The toast proves `RecordsLayout` mounts the
    // toaster `AdminLayout` lacks.
    const save = page.getByRole('button', { name: 'Save', exact: true });
    await save.click({ clickCount: 5, delay: 0 });
    await expect(page.getByText('Record created')).toBeVisible();
    await expectOneShell(page);
    expect((await apiListRecords(page, key)).total).toBe(1);
  });

  test('sidebar navigation between modules keeps the shell mounted', async ({ page }) => {
    await page.goto('/admin/news/');
    await expectOneShell(page);
    // Tag the live sidebar node. A client-side visit that keeps the layout
    // mounted keeps this exact node; a remount (or a full page load) loses it.
    await page.evaluate((selector) => {
      const aside = document.querySelector(selector);
      if (aside instanceof HTMLElement) aside.dataset.e2eKept = 'yes';
    }, SIDEBAR);

    for (const href of [
      '/admin/news/categories',
      '/pagebuilder/',
      '/pagebuilder/media',
      '/pagebuilder/content',
      '/ai/',
    ]) {
      await page.locator(`${SIDEBAR} a[href="${href}"]`).first().click();
      await expect(page).toHaveURL(new RegExp(`${href.replace(/\//g, '\\/')}$`));
      await expectOneShell(page);
      await expect(page.locator(`${SIDEBAR}[data-e2e-kept="yes"]`)).toHaveCount(1);
    }
  });
});
