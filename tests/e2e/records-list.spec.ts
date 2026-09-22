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
 * The generic record list (design §12's `RecordList.tsx`): the filter bar,
 * which only ever offers indexed fields plus the three fixed columns (§7.2),
 * the sortable headers, the refusal notice for a filter the index layer
 * won't build, and paging.
 */

const FIELDS = [
  { key: 'name', type: 'text', label: 'Name', indexed: true },
  { key: 'qty', type: 'integer', label: 'Quantity', indexed: true },
  { key: 'flag', type: 'boolean', label: 'Flag', indexed: true },
  // Deliberately unindexed: the filter bar must not offer it, and a
  // hand-written URL naming it must be refused out loud.
  { key: 'note', type: 'text', label: 'Note' },
];

async function seedListType(page: Page): Promise<string> {
  const key = uniqueTypeKey('list');
  await apiCreateType(page, {
    key,
    label: 'Listed',
    label_plural: 'Listed things',
    fields: FIELDS,
    display_field: 'name',
  });
  const rows = [
    { name: 'alpha', qty: 1, flag: true },
    { name: 'beta', qty: 2, flag: true },
    { name: 'gamma', qty: 3, flag: false },
    { name: 'delta', flag: false },
  ];
  for (const [index, data] of rows.entries()) {
    await apiCreateRecord(page, key, {
      data,
      position: index,
      status: index === 0 ? 'published' : 'draft',
    });
  }
  return key;
}

test.describe('Records — list, filter, sort, page', () => {
  test('offers only indexed fields and the three fixed columns as filters', async ({ page }) => {
    await login(page);
    const key = await seedListType(page);
    await page.goto(`/admin/records/${key}`);

    const fieldSelect = page.locator('#records-filter-field');
    await expect(fieldSelect.locator('option')).toHaveText([
      'Name',
      'Quantity',
      'Flag',
      'Title',
      'Status',
      'Invalid',
    ]);

    // Per-kind operator sets, minus `in` (the wire format joins on a bare
    // comma) and plus `is_null`, which the index layer answers uniformly.
    // `starts with` is the index-backed prefix match of F9 — a range, not a
    // `LIKE`, and therefore case-sensitive where `contains` is not.
    await fieldSelect.selectOption('name');
    await expect(page.locator('#records-filter-op').locator('option')).toHaveText([
      'is',
      'is not',
      'contains',
      'starts with',
      'is empty',
    ]);
    await fieldSelect.selectOption('qty');
    await expect(page.locator('#records-filter-op').locator('option')).toHaveText([
      'is',
      'is not',
      '>',
      '>=',
      '<',
      '<=',
      'is empty',
    ]);
    await fieldSelect.selectOption('flag');
    await expect(page.locator('#records-filter-op').locator('option')).toHaveText([
      'is',
      'is not',
      'is empty',
    ]);
  });

  test('applies every operator the bar offers on an indexed field', async ({ page }) => {
    test.setTimeout(120_000);
    await login(page);
    const key = await seedListType(page);
    const listUrl = `/admin/records/${key}`;

    const cases: [string, string, string | undefined, string[]][] = [
      ['name', 'eq', 'beta', ['beta']],
      ['name', 'ne', 'beta', ['alpha', 'gamma', 'delta']],
      ['name', 'contains', 'lph', ['alpha']],
      ['name', 'is_null', undefined, []],
      ['qty', 'eq', '2', ['beta']],
      // A record with no value at all satisfies "is not 2" — `ne` negates
      // rather than requiring an index row, unlike the ordered operators.
      ['qty', 'ne', '2', ['alpha', 'gamma', 'delta']],
      ['qty', 'gt', '2', ['gamma']],
      ['qty', 'gte', '2', ['beta', 'gamma']],
      ['qty', 'lt', '2', ['alpha']],
      ['qty', 'lte', '2', ['alpha', 'beta']],
      ['qty', 'is_null', undefined, ['delta']],
      ['flag', 'eq', 'true', ['alpha', 'beta']],
      ['flag', 'ne', 'true', ['gamma', 'delta']],
      ['display_title', 'contains', 'mm', ['gamma']],
      ['status', 'eq', 'published', ['alpha']],
    ];

    for (const [field, op, value, expected] of cases) {
      await page.goto(listUrl);
      await applyFilter(page, field, op, value);
      await expect
        .poll(() => rowTitles(page), { message: `${field}:${op}:${value}` })
        .toEqual(expected);
      await expect(page.getByTestId('records-filter-error')).toHaveCount(0);
    }
  });

  test('keeps the filter in the URL and clears it again', async ({ page }) => {
    await login(page);
    const key = await seedListType(page);
    await page.goto(`/admin/records/${key}`);
    await applyFilter(page, 'name', 'eq', 'beta');
    await expect(page).toHaveURL(/filter=name%3Aeq%3Abeta/);

    // A shared/bookmarked link renders the same state server-side.
    await page.goto(`/admin/records/${key}?filter=name:eq:beta`);
    await expect.poll(() => rowTitles(page)).toEqual(['beta']);

    await page.getByRole('button', { name: 'Clear' }).click();
    await expect(page).not.toHaveURL(/filter=/);
    await expect.poll(() => rowTitles(page)).toHaveLength(4);
  });

  test('explains a filter the index layer refuses', async ({ page }) => {
    await login(page);
    const key = await seedListType(page);

    await page.goto(`/admin/records/${key}?filter=note:eq:x`);
    await expect(page.getByTestId('records-filter-error')).toContainText(
      "That field isn't indexed",
    );
    await expect(page.getByTestId('records-record-row')).toHaveCount(0);

    await page.goto(`/admin/records/${key}?filter=nosuchfield:eq:x`);
    await expect(page.getByTestId('records-filter-error')).toContainText(
      "That field doesn't exist on this record type",
    );

    await page.goto(`/admin/records/${key}?filter=qty:eq:not-a-number`);
    await expect(page.getByTestId('records-filter-error')).toContainText(
      "That value isn't valid for this field",
    );

    // …and a clean filter afterwards takes the notice away again.
    await page.goto(`/admin/records/${key}?filter=name:eq:beta`);
    await expect(page.getByTestId('records-filter-error')).toHaveCount(0);
  });

  test('sorts by a column header through none → asc → desc', async ({ page }) => {
    await login(page);
    const key = await seedListType(page);
    await page.goto(`/admin/records/${key}`);

    const header = page.getByRole('columnheader', { name: 'Quantity' });
    await header.getByRole('button').click();
    await expect(page).toHaveURL(/sort=qty/);
    await expect(header).toHaveAttribute('aria-sort', 'ascending');
    // `delta` has no `qty` at all; it keeps its row and sorts last.
    await expect.poll(() => rowTitles(page)).toEqual(['alpha', 'beta', 'gamma', 'delta']);

    await header.getByRole('button').click();
    await expect(page).toHaveURL(/sort=-qty/);
    await expect(header).toHaveAttribute('aria-sort', 'descending');
    await expect
      .poll(async () => (await rowTitles(page)).slice(0, 3))
      .toEqual(['gamma', 'beta', 'alpha']);

    await header.getByRole('button').click();
    await expect(page).not.toHaveURL(/sort=/);
    await expect(header).toHaveAttribute('aria-sort', 'none');
    await expect.poll(() => rowTitles(page)).toHaveLength(4);
  });

  test('pages through more records than fit on one page', async ({ page }) => {
    test.setTimeout(180_000);
    await login(page);
    const key = uniqueTypeKey('paged');
    await apiCreateType(page, {
      key,
      label: 'Paged',
      label_plural: 'Paged things',
      fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
      display_field: 'name',
    });
    // Seeded over the API rather than the form: 30 records is about paging,
    // not about the editor, which `records-crud.spec.ts` already covers.
    const total = 30;
    for (let i = 0; i < total; i += 1) {
      await apiCreateRecord(page, key, {
        data: { name: `row-${String(i).padStart(2, '0')}` },
        position: i,
      });
    }

    await page.goto(`/admin/records/${key}?sort=name`);
    await expect(page.getByTestId('records-record-row')).toHaveCount(25);
    await expect(page.getByRole('button', { name: 'Previous' })).toBeDisabled();

    const next = page.getByRole('button', { name: 'Next' });
    await expect(next).toBeEnabled();
    await next.click();
    await expect(page).toHaveURL(/page=2/);
    await expect(page.getByTestId('records-record-row')).toHaveCount(total - 25);
    await expect(next).toBeDisabled();
    await expect((await rowTitles(page))[0]).toBe('row-25');

    await page.getByRole('button', { name: 'Previous' }).click();
    await expect(page.getByTestId('records-record-row')).toHaveCount(25);
    await expect((await rowTitles(page))[0]).toBe('row-00');
  });
});
