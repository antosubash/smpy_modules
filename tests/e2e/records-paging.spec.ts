import { expect, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateRecord,
  apiCreateType,
  apiListRecords,
  type RecordPage,
  rowTitles,
  uniqueTypeKey,
} from './records-helpers';

/**
 * Capped totals and the keyset cursor — Phase 5 §1, F4 and F11.
 *
 * `RecordsSettings.max_count` defaults to **10,000**, which no browser test
 * can seed. `tests/e2e/start-test-server.sh` lowers it to `MAX_COUNT` below
 * with `scripts/set_setting.py`, exactly the way it sets the two content
 * locales — the module reads its settings from the database, so this is the
 * only way to reach the ceiling at all. The value sits above every other
 * spec's fixtures (`records-list.spec.ts` pages through 30 records and
 * asserts an exact total), so lowering it changes nothing for them.
 *
 * Above the ceiling the API reports `total: max_count` with
 * `total_capped: true` and the list footer renders "of N+" rather than a
 * number that is not the number.
 */

/** Must match `start-test-server.sh`. */
const MAX_COUNT = 32;
const PAGE_SIZE = 25;
const SEEDED = MAX_COUNT + 1;

test.describe('Records — capped totals and cursor paging', () => {
  test.describe.configure({ timeout: 180_000 });

  test('past the ceiling the list says "N+" and still pages to the last page', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('capped');
    await apiCreateType(page, {
      key,
      label: 'Capped thing',
      label_plural: 'Capped things',
      fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
      display_field: 'name',
    });
    for (let i = 0; i < SEEDED; i += 1) {
      await apiCreateRecord(page, key, {
        data: { name: `row-${String(i).padStart(2, '0')}` },
        position: i,
      });
    }

    // The API first: one record over the ceiling is where `total` stops
    // being the count and starts being the cap.
    const listed = await apiListRecords(page, key, 'page_size=1');
    expect(listed.total).toBe(MAX_COUNT);
    expect(listed.total_capped).toBe(true);

    await page.goto(`/admin/records/${key}?sort=name`);
    await expect(page.getByTestId('records-record-row')).toHaveCount(PAGE_SIZE);
    // "10,000+" in production; here the same sentence about the same cap.
    await expect(page.getByText(`of ${MAX_COUNT}+`)).toBeVisible();
    await expect(page.getByText(`Showing 1–${PAGE_SIZE} of ${MAX_COUNT}+`)).toBeVisible();
    // The "+" says why the count stopped rather than the data (UX-2).
    await expect(page.getByText(`of ${MAX_COUNT}+`)).toHaveAttribute(
      'title',
      `More than ${MAX_COUNT} records match; the count stops at ${MAX_COUNT}.`,
    );
    await expect(page.getByRole('button', { name: 'Previous' })).toBeDisabled();

    const next = page.getByRole('button', { name: 'Next' });
    await expect(next).toBeEnabled();
    await next.click();
    await expect(page).toHaveURL(/page=2/);
    // Page 2 holds every remaining record — the cap bounds the *count*, not
    // the rows a page returns.
    await expect(page.getByTestId('records-record-row')).toHaveCount(SEEDED - PAGE_SIZE);
    await expect((await rowTitles(page))[0]).toBe('row-25');
    // Last page: `Next` is decided from the capped total, so the numbered
    // pager stops at the cap. Walking further is what `?after=` is for.
    await expect(next).toBeDisabled();
    // The range's end is what this page actually shows (33), which can run
    // past the "+" number (32) — that is what "+" means (UX-2's fix: the old
    // range end was `min(page*pageSize, total)`, one short of the real rows).
    await expect(page.getByText(`Showing 26–${SEEDED} of ${MAX_COUNT}+`)).toBeVisible();

    await page.getByRole('button', { name: 'Previous' }).click();
    await expect(page.getByTestId('records-record-row')).toHaveCount(PAGE_SIZE);
    await expect((await rowTitles(page))[0]).toBe('row-00');
  });

  test('a type below the ceiling still reports an exact total', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('uncapped');
    await apiCreateType(page, {
      key,
      label: 'Small thing',
      label_plural: 'Small things',
      fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
      display_field: 'name',
    });
    for (let i = 0; i < 3; i += 1) {
      await apiCreateRecord(page, key, { data: { name: `row-${i}` }, position: i });
    }

    const listed = await apiListRecords(page, key);
    expect(listed.total).toBe(3);
    expect(listed.total_capped).toBe(false);

    await page.goto(`/admin/records/${key}`);
    // One page of three: the footer renders nothing at all, capped or not.
    await expect(page.getByText(/^Showing /)).toHaveCount(0);
    await expect(page.getByTestId('records-record-row')).toHaveCount(3);
  });

  test('?after= walks past the capped total to the real end of the type', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('cursor');
    await apiCreateType(page, {
      key,
      label: 'Cursor thing',
      label_plural: 'Cursor things',
      fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
      display_field: 'name',
    });
    for (let i = 0; i < SEEDED; i += 1) {
      await apiCreateRecord(page, key, {
        data: { name: `row-${String(i).padStart(2, '0')}` },
        position: i,
      });
    }

    // The admin UI has numbered pages; an export or a widget walks the
    // cursor, and that walk is what still reaches record 33 when the count
    // stopped at 32. `total=false` is the cheap form the README recommends
    // for exactly this.
    const seen: string[] = [];
    let cursor: string | null = null;
    for (let guard = 0; guard < 10; guard += 1) {
      const query = `page_size=10&total=false${cursor ? `&after=${encodeURIComponent(cursor)}` : ''}`;
      const chunk: RecordPage = await apiListRecords(page, key, query);
      seen.push(...chunk.items.map((item) => item.display_title));
      cursor = chunk.next_cursor;
      if (!cursor) break;
    }
    expect(seen).toHaveLength(SEEDED);
    expect(new Set(seen).size).toBe(SEEDED);
    expect(seen[seen.length - 1]).toBe(`row-${String(SEEDED - 1).padStart(2, '0')}`);
  });
});
