import { expect, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateType,
  apiDeleteType,
  apiGetType,
  apiUpdateType,
  saveType,
  type TypeRead,
  uniqueTypeKey,
} from './records-helpers';

// `show_in_menu` isn't on `records-helpers.ts::TypeRead` (that file sits
// right at the 300-line cap already) — this local extension avoids growing
// a shared helper every other `records-*.spec.ts` file also imports, for one
// field only this spec reads off the wire response.
type TypeReadWithSidebar = TypeRead & { show_in_menu: boolean };

/**
 * Per-type sidebar entries (design contract: "per-type sidebar entries"):
 * a Record Type with `show_in_menu` gets its own admin sidebar link, under
 * the "Records" group it shares with the hub — which U17 moved out of the
 * shared "Content" group and renamed "All record types", so the hub reads
 * as the way into every type rather than as a peer of another module's
 * screen — and the TypeEditor's own "Show in sidebar" switch that drives
 * it.
 *
 * The sidebar itself (`AdminLayout` -> `SidebarLayout`, `menuKey:
 * "adminSidebar"`) renders inside an `<aside>`, so every locator here is
 * scoped to it — the Types hub table below also renders each type's label,
 * and an unscoped `getByRole('link', { name: labelPlural })` would match
 * both.
 */
test.describe('Records — sidebar entries', () => {
  test('a type with show_in_menu on gets a sidebar link, and loses it when turned off', async ({
    page,
  }) => {
    await login(page);
    const key = uniqueTypeKey('sidebar');
    const labelPlural = `Sidebar things ${key}`;
    const created = await apiCreateType(page, {
      key,
      label: `Sidebar thing ${key}`,
      label_plural: labelPlural,
      fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
      display_field: 'name',
      show_in_menu: true,
    });

    await page.goto('/admin/records/');
    const sidebar = page.locator('aside');
    // One "Records" group header holds both the hub and the type
    // (SidebarLayout.tsx renders one per distinct `group`, in the order its
    // lowest-`order` item appears).
    const group = sidebar.locator('div.uppercase', { hasText: 'Records' });
    await expect(group).toBeVisible();
    const link = sidebar.getByRole('link', { name: labelPlural, exact: true });
    await expect(link).toBeVisible();

    // U17: the hub entry is still there, above its children, named for what
    // it is — both links coexist in the same group.
    const hub = sidebar.getByRole('link', { name: 'All record types', exact: true });
    await expect(hub).toBeVisible();
    await expect(hub).toHaveAttribute('href', '/admin/records/');
    // The hub is listed first (`MENU_ORDER` < `MENU_ORDER_TYPE`).
    const names = await sidebar.getByRole('link').allInnerTexts();
    expect(names.indexOf('All record types')).toBeLessThan(names.indexOf(labelPlural));

    await link.click();
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}$`));

    // Turning it off through the API (mirrors a PUT from the type editor)
    // removes the link — no restart, no stale entry left showing.
    await apiUpdateType(page, key, created.version, { show_in_menu: false });
    await page.goto('/admin/records/');
    await expect(
      page.locator('aside').getByRole('link', { name: labelPlural, exact: true }),
    ).toHaveCount(0);

    await apiDeleteType(page, key, 0);
  });

  test('the type editor’s "Show in sidebar" switch is off by default and persists through Save', async ({
    page,
  }) => {
    await login(page);
    const key = uniqueTypeKey('sidebarsw');
    const labelPlural = `Switch things ${key}`;
    await apiCreateType(page, {
      key,
      label: `Switch thing ${key}`,
      label_plural: labelPlural,
      fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
      display_field: 'name',
    });

    await page.goto(`/admin/records/types/${key}`);
    const toggle = page.locator('#type-editor-show-in-menu');
    await expect(toggle).not.toBeChecked();

    await toggle.click();
    await expect(toggle).toBeChecked();
    await saveType(page);
    await expect(page.getByRole('button', { name: 'Preview changes' })).toBeDisabled();

    await page.reload();
    await expect(page.locator('#type-editor-show-in-menu')).toBeChecked();

    const stored = (await apiGetType(page, key)) as TypeReadWithSidebar;
    expect(stored.show_in_menu).toBe(true);

    await apiDeleteType(page, key, 0);
  });

  test('a brand-new type defaults "Show in sidebar" to off', async ({ page }) => {
    await login(page);
    await page.goto('/admin/records/types/new');
    await expect(page.getByRole('heading', { name: 'New type' })).toBeVisible();
    await expect(page.locator('#type-editor-show-in-menu')).not.toBeChecked();
  });
});
