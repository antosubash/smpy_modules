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
 * number that is not the number. The numbered pager stops at the page that
 * holds the ceiling; past it "Next" follows the keyset cursor (`?after=`)
 * and the footer switches to its cursor mode — "First page" / "Next page",
 * no page numbers.
 */

/** Must match `start-test-server.sh`. */
const MAX_COUNT = 32;
const PAGE_SIZE = 25;
const SEEDED = MAX_COUNT + 1;
/** Enough rows that the cap's last numbered page (page 2 at 25) is full and
 *  more follow it — the rows only the cursor reaches. */
const BEYOND = 2 * PAGE_SIZE + 8;

const title = (i: number) => `row-${String(i).padStart(2, '0')}`;

test.describe('Records — capped totals and cursor paging', () => {
  test.describe.configure({ timeout: 180_000 });

  test('past the ceiling the list says "N+", pages to the cap, then continues by cursor', async ({
    page,
  }) => {
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
        data: { name: title(i) },
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
    // Last numbered page, and a short one: there is nothing after it, so
    // `Next` has no cursor to follow and stays disabled.
    await expect(next).toBeDisabled();
    // The range's end is what this page actually shows (33), which can run
    // past the "+" number (32) — that is what "+" means (UX-2's fix: the old
    // range end was `min(page*pageSize, total)`, one short of the real rows).
    await expect(page.getByText(`Showing 26–${SEEDED} of ${MAX_COUNT}+`)).toBeVisible();

    await page.getByRole('button', { name: 'Previous' }).click();
    await expect(page.getByTestId('records-record-row')).toHaveCount(PAGE_SIZE);
    await expect((await rowTitles(page))[0]).toBe('row-00');

    // Now more rows than the numbered pages can hold: page 2 is the cap's
    // last page and it is full, with rows after it that only the cursor
    // reaches.
    for (let i = SEEDED; i < BEYOND; i += 1) {
      await apiCreateRecord(page, key, { data: { name: title(i) }, position: i });
    }
    const rows = page.getByTestId('records-record-row');
    await page.goto(`/admin/records/${key}?sort=name&page=2`);
    await expect(rows).toHaveCount(PAGE_SIZE);
    await expect(rows.first()).toContainText(title(PAGE_SIZE));
    await expect(page.getByText(`Showing 26–50 of ${MAX_COUNT}+`)).toBeVisible();
    await expect(page.getByTestId('records-page-position')).toHaveText('Page 2');
    // The cap's last page, but the server says there is more: Next follows it.
    // From the keyboard: the pressed button keeps focus through the request
    // and becomes the cursor page's "Next page" (review 4, ux F2 — it used to
    // be disabled in flight, which threw focus to <body>).
    await expect(next).toBeEnabled();
    await next.focus();
    await page.keyboard.press('Enter');

    // The cursor page: `after` in the URL instead of a page number…
    await expect(page).toHaveURL(/[?&]after=/);
    await expect(page).not.toHaveURL(/[?&]page=/);
    await expect(page).toHaveURL(/[?&]sort=name/);
    // …and the rows past the ceiling, in order.
    await expect(rows).toHaveCount(BEYOND - 2 * PAGE_SIZE);
    expect(await rowTitles(page)).toEqual(
      Array.from({ length: BEYOND - 2 * PAGE_SIZE }, (_, n) => title(2 * PAGE_SIZE + n)),
    );
    // Cursor mode: no range, no page number, no Previous/Last — First page,
    // Next page and the sentence.
    await expect(page.getByTestId('records-page-cursor')).toHaveText(
      'The list continues in the same order from here, without page numbers.',
    );
    await expect(page.getByTestId('records-page-position')).toHaveCount(0);
    await expect(page.getByText(/^Showing /)).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Previous', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Last', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Next page', exact: true })).toBeFocused();
    // A short page is the end of the list (`aria-disabled` while it still
    // holds focus, `disabled` once focus moves on — both read as disabled).
    await expect(page.getByRole('button', { name: 'Next page', exact: true })).toBeDisabled();

    // Every step is its own history entry: Back walks to the numbered page
    // the cursor came from, Forward returns to the cursor page.
    const cursorUrl = page.url();
    await page.goBack();
    await expect(page).toHaveURL(/[?&]page=2/);
    await expect(rows).toHaveCount(PAGE_SIZE);
    await expect(rows.first()).toContainText(title(PAGE_SIZE));
    await page.goForward();
    await expect(page).toHaveURL(cursorUrl);
    await expect(rows).toHaveCount(BEYOND - 2 * PAGE_SIZE);
    await expect(rows.first()).toContainText(title(2 * PAGE_SIZE));

    // The URL is the whole state: the cursor page opens again from its link
    // in a fresh load, which is what makes it shareable.
    await page.goto(cursorUrl);
    await expect(rows).toHaveCount(BEYOND - 2 * PAGE_SIZE);
    await expect(rows.first()).toContainText(title(2 * PAGE_SIZE));
    await expect(page.getByTestId('records-page-cursor')).toBeVisible();

    // First page leaves the cursor behind.
    await page.getByRole('button', { name: 'First page', exact: true }).click();
    await expect(page).not.toHaveURL(/[?&]after=/);
    await expect(rows).toHaveCount(PAGE_SIZE);
    await expect(rows.first()).toContainText(title(0));

    // A page-size change drops the cursor too: it lands on page 1.
    await page.goto(cursorUrl);
    await expect(rows.first()).toContainText(title(2 * PAGE_SIZE));
    await page.locator('#records-page-size').selectOption('50');
    await expect(page).toHaveURL(/[?&]page_size=50/);
    await expect(page).not.toHaveURL(/[?&]after=/);
    await expect(rows).toHaveCount(50);
    await expect(rows.first()).toContainText(title(0));
  });

  test('a cursor link that no longer fits is the notice, not an error page', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('badcursor');
    await apiCreateType(page, {
      key,
      label: 'Cursor misfit',
      label_plural: 'Cursor misfits',
      fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
      display_field: 'name',
    });
    for (let i = 0; i < 3; i += 1) {
      await apiCreateRecord(page, key, { data: { name: title(i) }, position: i });
    }
    // A cursor minted under `sort=name`, replayed under `sort=-name`.
    const listed = await apiListRecords(page, key, 'sort=name&page_size=1');
    expect(listed.next_cursor).not.toBeNull();
    await page.goto(
      `/admin/records/${key}?sort=-name&after=${encodeURIComponent(listed.next_cursor ?? '')}`,
    );
    await expect(page.getByTestId('records-filter-error')).toContainText(
      "This link can't continue the list",
    );
    await expect(page.getByTestId('records-empty-cursor')).toBeVisible();
    await page
      .getByTestId('records-empty-state')
      .getByRole('button', { name: 'First page' })
      .click();
    await expect(page).not.toHaveURL(/[?&]after=/);
    await expect(page).toHaveURL(/[?&]sort=-name/);
    await expect(page.getByTestId('records-record-row')).toHaveCount(3);
    await expect(page.getByTestId('records-filter-error')).toHaveCount(0);
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
        data: { name: title(i) },
        position: i,
      });
    }

    // An export or a widget walks the cursor through the API (the list does
    // the same through the view, above), and that walk is what still reaches
    // record 33 when the count stopped at 32. `total=false` is the cheap form
    // the README recommends for exactly this.
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
