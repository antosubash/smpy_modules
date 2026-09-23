import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import { apiCreateRecord, apiCreateType, uniqueTypeKey } from './records-helpers';

/**
 * The record list's column chooser: pick columns in the "Columns" panel, see
 * the choice land in the link (`?columns=`), survive a reload, open the same
 * view from a browser that has never seen it, fall back to this browser's
 * saved default on a clean URL, and go away again with "Reset to default".
 *
 * Seeds through the JSON API under a per-run type key, the way the rest of
 * the `records-*` suite does. Every record keeps `position: 0`, so the
 * default view hides Position (UX-R25) and the panel starts without it.
 */

const DEFAULT_HEADERS = ['Title', 'Status', 'Price', 'City', 'Published on', 'Updated', 'Actions'];

async function seedColumnsType(page: Page): Promise<string> {
  const key = uniqueTypeKey('cols');
  await apiCreateType(page, {
    key,
    label: 'Column thing',
    label_plural: 'Column things',
    fields: [
      { key: 'name', type: 'text', label: 'Name', indexed: true },
      { key: 'price', type: 'number', label: 'Price', indexed: true },
      { key: 'city', type: 'text', label: 'City', indexed: true },
      { key: 'blurb', type: 'longtext', label: 'Blurb' },
      { key: 'meta', type: 'json', label: 'Meta' },
    ],
    display_field: 'name',
  });
  for (let i = 0; i < 2; i += 1) {
    await apiCreateRecord(page, key, {
      data: {
        name: `Col Row ${i}`,
        price: `${i + 1}.5`,
        city: `City ${i}`,
        blurb: `Blurb ${i}\n\nsecond paragraph`,
        meta: { n: i },
      },
      position: 0,
    });
  }
  return key;
}

/** The header texts, minus the tick-box column's empty one and the sort
 *  arrow a sorted header carries. */
async function headers(page: Page): Promise<string[]> {
  await expect(page.getByTestId('records-record-row').first()).toBeVisible();
  const texts = await page.locator('thead th').allTextContents();
  return texts.map((text) => text.replace(/[▲▼]/g, '').trim()).filter(Boolean);
}

async function openColumns(page: Page) {
  await page.getByTestId('records-columns-button').click();
  const panel = page.getByTestId('records-columns-panel');
  await expect(panel).toBeVisible();
  return panel;
}

test.describe('Records — the column chooser', () => {
  test('choose → link → reload → shared in a fresh browser → reset', async ({ page, browser }) => {
    await login(page);
    const key = await seedColumnsType(page);
    const listPath = `/admin/records/${key}`;
    await page.goto(listPath);
    expect(await headers(page)).toEqual(DEFAULT_HEADERS);

    const panel = await openColumns(page);
    await expect(panel.getByTestId('records-columns-count')).toHaveText('2 of 8 field columns');
    // A non-indexed field is choosable, and the panel says why it won't sort.
    const blurbRow = panel.locator('[data-column="blurb"]');
    await expect(blurbRow.getByTestId('records-column-not-indexed')).toBeVisible();
    await panel.getByRole('checkbox', { name: 'Blurb' }).click();
    // A ticked field joins the other fields, before the dates (review 4 F11).
    await expect(page).toHaveURL(/columns=status,price,city,blurb,published_at,updated_at(&|$)/);

    // Reorder from the keyboard: focus stays on the moved column's button.
    const moveUp = panel.getByRole('button', { name: 'Move Blurb up' });
    await moveUp.focus();
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/columns=status,price,blurb,city,published_at,updated_at(&|$)/);
    await expect(moveUp).toBeFocused();

    // Hide Status with the keyboard too.
    await panel.getByRole('checkbox', { name: 'Status' }).focus();
    await page.keyboard.press('Space');
    await expect(page).toHaveURL(/columns=price,blurb,city,published_at,updated_at(&|$)/);
    await page.keyboard.press('Escape');
    await expect(panel).toBeHidden();

    const chosen = ['Title', 'Price', 'Blurb', 'City', 'Published on', 'Updated', 'Actions'];
    expect(await headers(page)).toEqual(chosen);
    // The non-indexed column has no sort control.
    const blurbHeader = page.getByTestId('records-column-unsortable');
    await expect(blurbHeader).toHaveText('Blurb');
    await expect(blurbHeader.getByRole('button')).toHaveCount(0);

    // The link is the view: a reload keeps it.
    const sharedUrl = page.url();
    await page.reload();
    expect(await headers(page)).toEqual(chosen);

    // This browser saved it as the type's default: a clean URL shows it,
    // and the URL stays clean.
    await page.goto(listPath);
    await expect(page).toHaveURL(new RegExp(`${listPath}$`));
    expect(await headers(page)).toEqual(chosen);

    // Another browser with nothing saved: the shared link carries the view,
    // and the clean URL is the plain default there.
    const other = await browser.newContext();
    try {
      const fresh = await other.newPage();
      await login(fresh);
      await fresh.goto(sharedUrl);
      expect(await headers(fresh)).toEqual(chosen);
      await fresh.goto(listPath);
      expect(await headers(fresh)).toEqual(DEFAULT_HEADERS);
    } finally {
      await other.close();
    }

    // Reset clears both the link and the saved default.
    await page.goto(sharedUrl);
    const again = await openColumns(page);
    await again.getByTestId('records-columns-reset').click();
    await expect(page).not.toHaveURL(/columns=/);
    // Reset disables itself; focus moves to the panel's heading (F10).
    await expect(again.getByText('Columns', { exact: true })).toBeFocused();
    await page.keyboard.press('Escape');
    expect(await headers(page)).toEqual(DEFAULT_HEADERS);
    await page.goto(listPath);
    expect(await headers(page)).toEqual(DEFAULT_HEADERS);
  });

  test('an unknown key in the link is dropped with a notice, not an error', async ({ page }) => {
    await login(page);
    const key = await seedColumnsType(page);
    await page.goto(`/admin/records/${key}?columns=price,nope,meta`);
    expect(await headers(page)).toEqual(['Title', 'Price', 'Meta', 'Actions']);
    await expect(page.getByTestId('records-columns-notice')).toContainText('nope');
    await expect(page.getByTestId('records-filter-error')).toHaveCount(0);
  });

  test('hiding the sorted column drops the sort; hiding another keeps it', async ({ page }) => {
    await login(page);
    const key = await seedColumnsType(page);
    await page.goto(`/admin/records/${key}?sort=-city&columns=price,city`);
    expect(await headers(page)).toEqual(['Title', 'Price', 'City', 'Actions']);

    const panel = await openColumns(page);
    await panel.getByRole('checkbox', { name: 'Price' }).click();
    await expect(page).toHaveURL(/columns=city(&|$)/);
    await expect(page).toHaveURL(/sort=-city/);

    await panel.getByRole('checkbox', { name: 'City' }).click();
    await expect(page).not.toHaveURL(/sort=/);
    await expect(page).toHaveURL(/columns=(&|$)/);
  });

  test('a field labelled "Status" is told apart from the record Status', async ({ page }) => {
    // Review 4, ux F3: two identical "Status" headers, and "Status: Open"
    // beside the status badge on a phone card.
    await login(page);
    const key = uniqueTypeKey('colsclash');
    await apiCreateType(page, {
      key,
      label: 'Clash thing',
      label_plural: 'Clash things',
      fields: [
        { key: 'name', type: 'text', label: 'Name', indexed: true },
        { key: 'state', type: 'text', label: 'Status', indexed: true },
      ],
      display_field: 'name',
    });
    await apiCreateRecord(page, key, { data: { name: 'Clash 1', state: 'Open' }, position: 0 });
    await page.goto(`/admin/records/${key}`);
    expect(await headers(page)).toEqual(
      expect.arrayContaining(['Status (status)', 'Status (state)']),
    );
    expect(await headers(page)).not.toContain('Status');
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId('records-record-card').locator('dt')).toHaveText([
      'Status (state)',
      'Published on',
      'Updated',
    ]);
  });

  // Review 4, ux F1: the sixth toolbar button (Columns) pushed a 720px
  // document to 745px — PageShell sizes its actions box to its content, so
  // the group has to cap its own width to wrap (RecordListActions).
  for (const [width, height] of [
    [720, 450],
    [390, 844],
  ] as const) {
    test(`the list toolbar wraps instead of scrolling the page at ${width}×${height}`, async ({
      page,
    }) => {
      await login(page);
      const key = await seedColumnsType(page);
      await page.setViewportSize({ width, height });
      await page.goto(`/admin/records/${key}`);
      const toolbar = page.getByTestId('records-list-actions');
      await expect(toolbar.getByRole('link', { name: 'New record' })).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);
      const box = await toolbar.getByRole('link', { name: 'New record' }).boundingBox();
      expect(box && box.x >= 0 && box.x + box.width <= width).toBeTruthy();
    });
  }
});
