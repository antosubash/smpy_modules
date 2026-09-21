import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateRecord,
  apiCreateType,
  applyFilter,
  rowTitles,
  uniqueTypeKey,
} from './records-helpers';

/**
 * The record list's ordinary path, as the 2026-09-20 UX review found it:
 * an empty result that claimed the type was empty (R1), an Enter key the
 * filter bar swallowed (R2), a Back button that left the list instead of
 * undoing the last refinement (R3), a table whose action column sat past the
 * right edge of a phone (R4), a Title column printed twice and two filter
 * options both called "Status" (R5), a delete that never mentioned the Trash
 * it used (R8), and a footer of two buttons and a sentence (R18).
 *
 * Everything here seeds through the JSON API under a per-run type key, the
 * way the rest of the `records-*` suite does.
 */

const PHONE = { width: 390, height: 844 };

/** The display titles on a type's list screen, having navigated to it and
 *  waited for the rows the type is known to have. */
async function rowTitlesFor(page: Page, key: string, count: number): Promise<string[]> {
  await page.goto(`/admin/records/${key}`);
  await expect(page.getByTestId('records-record-row')).toHaveCount(count);
  return rowTitles(page);
}

async function seedUxType(page: Page, records = 3): Promise<string> {
  const key = uniqueTypeKey('uxlist');
  await apiCreateType(page, {
    key,
    label: 'UX thing',
    label_plural: 'UX things',
    fields: [
      { key: 'name', type: 'text', label: 'Name', indexed: true },
      { key: 'city', type: 'text', label: 'City', indexed: true },
      // Deliberately labelled "Status", like the seeded `order` type's own
      // `order_status`: the fixed record status carries the same label, and
      // the two were indistinguishable in the field dropdown (R5b).
      {
        key: 'order_status',
        type: 'select',
        label: 'Status',
        indexed: true,
        options: { choices: [{ value: 'open', label: 'Open' }] },
      },
    ],
    display_field: 'name',
  });
  for (let i = 0; i < records; i += 1) {
    await apiCreateRecord(page, key, {
      data: { name: `UX Row ${i}`, city: `City ${i}`, order_status: 'open' },
      position: 0,
    });
  }
  return key;
}

test.describe('Records — list UX', () => {
  test('a filter that matches nothing says so and offers to clear itself (R1)', async ({
    page,
  }) => {
    await login(page);
    const key = await seedUxType(page);
    await page.goto(`/admin/records/${key}`);

    await applyFilter(page, 'name', 'eq', 'zzzznotfound');
    const empty = page.getByTestId('records-empty-state');
    await expect(empty).toContainText('No records match this filter.');
    await expect(empty).not.toContainText('No records yet');

    // The box carries the recovery, for the reader who arrived on a shared
    // deep link and has no filter-bar context in their head.
    await empty.getByRole('button', { name: 'Clear' }).click();
    await expect(page).not.toHaveURL(/filter=/);
    await expect.poll(() => rowTitles(page)).toHaveLength(3);
  });

  test('a genuinely empty type offers the New record call to action (R1)', async ({ page }) => {
    await login(page);
    const key = await seedUxType(page, 0);
    await page.goto(`/admin/records/${key}`);

    const empty = page.getByTestId('records-empty-state');
    await expect(empty).toContainText('No records yet');
    await empty.getByRole('link', { name: 'New record' }).click();
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}/new$`));
  });

  test('Enter in the filter value applies the filter (R2)', async ({ page }) => {
    await login(page);
    const key = await seedUxType(page);
    await page.goto(`/admin/records/${key}`);

    await page.locator('#records-filter-field').selectOption('name');
    await page.locator('#records-filter-op').selectOption('eq');
    await page.locator('#records-filter-value').fill('UX Row 1');
    await page.locator('#records-filter-value').press('Enter');

    await expect(page).toHaveURL(/filter=name/);
    await expect.poll(() => rowTitles(page)).toEqual(['UX Row 1']);
  });

  test('Back undoes a filter and then a sort instead of leaving the list (R3)', async ({
    page,
  }) => {
    await login(page);
    const key = await seedUxType(page);
    await page.goto(`/admin/records/${key}`);

    await page.getByRole('columnheader', { name: 'City' }).getByRole('button').click();
    await expect(page).toHaveURL(/sort=city/);
    await applyFilter(page, 'name', 'eq', 'UX Row 1');
    await expect(page).toHaveURL(/filter=name/);
    await expect.poll(() => rowTitles(page)).toEqual(['UX Row 1']);

    await page.goBack();
    await expect(page).not.toHaveURL(/filter=/);
    await expect(page).toHaveURL(/sort=city/);
    // The bar remounts against the URL it went back to, rather than keeping
    // the filter it no longer has.
    await expect(page.getByRole('button', { name: 'Clear' })).toHaveCount(0);
    await expect.poll(() => rowTitles(page)).toHaveLength(3);

    await page.goBack();
    await expect(page).not.toHaveURL(/sort=/);
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}$`));
  });

  test('drops the display-field column and disambiguates duplicate filter labels (R5)', async ({
    page,
  }) => {
    await login(page);
    const key = await seedUxType(page);
    await page.goto(`/admin/records/${key}`);

    // "Title" already prints `name` on every row; the column for `name`
    // itself is gone, and `city` takes the slot.
    await expect(page.getByTestId('records-record-row')).toHaveCount(3);
    const headers = await page.getByRole('columnheader').allTextContents();
    const trimmed = headers.map((text) => text.trim());
    expect(trimmed).toContain('Title');
    expect(trimmed).toContain('City');
    expect(trimmed).not.toContain('Name');

    const options = await page.locator('#records-filter-field option').allTextContents();
    expect(options).toContain('Status (order_status)');
    expect(options).toContain('Status (status)');
    expect(options).not.toContain('Status');
  });

  test('deleting from the list says Trash and undoes itself (R8a)', async ({ page }) => {
    await login(page);
    const key = await seedUxType(page);
    await page.goto(`/admin/records/${key}`);

    const row = page.getByTestId('records-record-row').first();
    await row.getByRole('button', { name: 'Delete' }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toContainText('Move this record to the Trash?');
    await dialog.getByRole('button', { name: 'Delete' }).click();
    await expect(dialog).toHaveCount(0);

    await expect(page.getByText('Moved to the Trash')).toBeVisible();
    await expect(page.getByRole('link', { name: 'View trash' })).toBeVisible();
    await expect.poll(() => rowTitles(page)).toHaveLength(2);

    await page.getByRole('button', { name: 'Undo' }).click();
    await expect(page.getByText('Record restored')).toBeVisible();
    await expect.poll(() => rowTitles(page)).toHaveLength(3);
  });

  test('deleting from the editor says the same thing (R8a)', async ({ page }) => {
    await login(page);
    const key = await seedUxType(page, 1);
    const listed = await rowTitlesFor(page, key, 1);

    await page.getByRole('link', { name: listed[0] }).click();
    // Wait for the editor before reaching for "Delete": the list's own row
    // action carries the same label, and clicking it mid-navigation opens a
    // dialog the arriving page then unmounts.
    await expect(page).toHaveURL(/\/[0-9a-f]{32}$/);
    await expect(page.getByRole('heading', { name: listed[0], level: 1 })).toBeVisible();
    await page.getByRole('button', { name: 'Delete' }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toContainText('Move this record to the Trash?');
    await dialog.getByRole('button', { name: 'Delete' }).click();

    // The toast survives the visit back to the list the delete triggers —
    // `RecordsToaster` is mounted by the layout both screens share.
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}`));
    await expect(page.getByText('Moved to the Trash')).toBeVisible();
    await page.getByRole('button', { name: 'Undo' }).click();
    await expect(page.getByText('Record restored')).toBeVisible();
    await expect.poll(() => rowTitles(page)).toEqual(listed);
  });

  test('pages with First/Last, a page number and a page size (R18, R15)', async ({ page }) => {
    test.setTimeout(180_000);
    await login(page);
    const key = uniqueTypeKey('uxpage');
    await apiCreateType(page, {
      key,
      label: 'UX paged',
      label_plural: 'UX paged things',
      fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
      display_field: 'name',
    });
    for (let i = 0; i < 30; i += 1) {
      await apiCreateRecord(page, key, {
        data: { name: `page-${String(i).padStart(2, '0')}` },
        position: i,
      });
    }

    await page.goto(`/admin/records/${key}?sort=name`);
    await expect(page.getByTestId('records-page-position')).toHaveText('Page 1 of 2');
    await expect(page.getByRole('button', { name: 'First' })).toBeDisabled();

    await page.getByRole('button', { name: 'Last' }).click();
    await expect(page).toHaveURL(/page=2/);
    await expect(page.getByTestId('records-page-position')).toHaveText('Page 2 of 2');
    // The live region tells a screen reader the page became another page.
    await expect(page.getByTestId('records-list-status')).toHaveText('5 records, page 2 of 2');
    await expect(page.getByRole('button', { name: 'Last' })).toBeDisabled();

    await page.getByRole('button', { name: 'First' }).click();
    await expect(page).not.toHaveURL(/page=2/);
    await expect((await rowTitles(page))[0]).toBe('page-00');

    // A longer page is one select away, and rides in the URL like every
    // other piece of this screen's state.
    await page.locator('#records-page-size').selectOption('50');
    await expect(page).toHaveURL(/page_size=50/);
    await expect(page.getByTestId('records-record-row')).toHaveCount(30);
    await expect(page.getByTestId('records-page-position')).toHaveText('Page 1 of 1');
  });

  test('on a phone the list stacks into cards and nothing scrolls sideways (R4)', async ({
    page,
  }) => {
    await login(page);
    const key = await seedUxType(page);
    await page.setViewportSize(PHONE);
    await page.goto(`/admin/records/${key}`);

    await expect(page.getByTestId('records-record-card')).toHaveCount(3);
    // The table is not merely hidden — it is not rendered at this width.
    await expect(page.getByTestId('records-record-row')).toHaveCount(0);
    // The row action is on screen rather than past the right edge.
    await expect(
      page.getByTestId('records-record-card').first().getByRole('button', { name: 'Delete' }),
    ).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      PHONE.width,
    );

    // The hub the sidebar's "Records" opens pays the same rule.
    await page.goto('/admin/records');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      PHONE.width,
    );
  });
});
