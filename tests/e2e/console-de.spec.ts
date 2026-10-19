import { expect, test } from '@playwright/test';

import { login } from './helpers';
import { apiCreateRecord, apiDeleteType, seedTextType } from './records-helpers';

/**
 * The console in German. Every module ships a `de.json` beside its `en.json`;
 * the framework picks the catalogue from the `locale` cookie, layered over
 * English, so a German admin sees each module's screens in German.
 *
 * The cookie is set after login, not before: the sign-in screen is the
 * framework's, which ships English only, and this spec is about the modules.
 */

test.describe('Console in German', () => {
  test.beforeEach(async ({ page, context }) => {
    await login(page);
    await context.addCookies([
      { name: 'locale', value: 'de', url: new URL('/', page.url()).toString() },
    ]);
  });

  test('pagebuilder, records and ai screens read German', async ({ page }) => {
    await page.goto('/pagebuilder/');
    await expect(page.getByRole('heading', { name: 'Seiten', exact: true })).toBeVisible();

    await page.goto('/admin/records');
    await expect(page.getByText('Datensatztypen', { exact: true }).first()).toBeVisible();

    await page.goto('/ai/');
    await expect(page.getByRole('heading', { name: 'KI', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Verbindung testen' }).first()).toBeVisible();
  });

  test('the records filter operators read German', async ({ page }) => {
    // Records call `t(keys.records…)` with no English `defaultValue` (#78),
    // so a missing German entry would show English or the dotted key here.
    const key = await seedTextType(page, 'deops', { field: 'name' });
    // An empty list shows its empty state in place of the filter bar.
    await apiCreateRecord(page, key, { data: { name: 'eins' } });
    await page.goto(`/admin/records/${key}`);
    await page.locator('#records-filter-field').selectOption('name');
    await expect(page.locator('#records-filter-op').locator('option')).toHaveText([
      'ist',
      'ist nicht',
      'enthält',
      'beginnt mit',
      'ist leer',
    ]);
    await apiDeleteType(page, key, 1);
  });

  test('a block palette label in the page editor reads German', async ({ page }) => {
    await page.goto('/pagebuilder/new');
    // Labels hold catalogue keys and are resolved at render (localizeConfig),
    // so this proves the German catalogue reaches Puck's palette too.
    await expect(
      page
        .locator('[class*="DrawerItem-name"]')
        .filter({ hasText: /^Überschrift$/ })
        .first(),
    ).toBeVisible();
  });

  test('the console chrome reads German too', async ({ page }) => {
    // The chrome is the framework's `ui` namespace, translated by the host's
    // `host/locales/overrides/de.json`: a key missing there renders raw.
    await page.goto('/admin/records');
    // Tab only once the page has rendered, or it lands before the link exists.
    await expect(page.getByText('Datensatztypen', { exact: true }).first()).toBeVisible();
    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: 'Zum Inhalt springen' })).toBeFocused();
    await expect(page.getByText('Zugriff', { exact: true }).first()).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/\bui\.[a-z_]+\.[a-z_]+/);
  });

  test('switching back to English restores the English screens', async ({ page, context }) => {
    await context.addCookies([
      { name: 'locale', value: 'en', url: new URL('/', page.url()).toString() },
    ]);
    await page.goto('/pagebuilder/');
    await expect(page.getByRole('heading', { name: 'Pages', exact: true })).toBeVisible();
  });
  test('the header language switcher changes the console language', async ({ page, context }) => {
    // Start from English: the beforeEach cookie is German.
    await context.addCookies([
      { name: 'locale', value: 'en', url: new URL('/', page.url()).toString() },
    ]);
    await page.goto('/pagebuilder/');
    await expect(page.getByRole('heading', { name: 'Pages', exact: true })).toBeVisible();

    await page.getByRole('button', { name: 'Change language' }).first().click();
    await page.getByRole('menuitem', { name: /Deutsch/ }).click();

    // Back on the same screen, now in German — and it stays German.
    await expect(page).toHaveURL(/\/pagebuilder\/$/);
    await expect(page.getByRole('heading', { name: 'Seiten', exact: true })).toBeVisible();
    await page.goto('/ai/');
    await expect(page.getByRole('heading', { name: 'KI', exact: true })).toBeVisible();
  });
});
