import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateRecord,
  apiCreateType,
  recordField,
  recordFieldError,
  seedTextType,
  uniqueTypeKey,
} from './records-helpers';

/**
 * The record editor's UX-review fixes (2026-09-20): R6 (a refused save takes
 * you to the field and clears as you fix it), R12a (a dropped connection
 * says so in words), R12c (unsaved work is guarded), R16 (the schema form
 * comes first, Status sits in the header, Slug/Position behind "Advanced"),
 * R20 (the relation picker is a real combobox) and R22a (creating a record
 * is confirmed).
 *
 * Kept out of `records-crud.spec.ts`, which is near the 300-line cap and is
 * about what the form *stores*; this file is about what it *tells you*.
 */

/** A type whose required field sits under a long one, so the field a refused
 *  save is about is genuinely off-screen from the Save button. */
async function seedTallType(page: Page): Promise<string> {
  const key = uniqueTypeKey('uxed');
  await apiCreateType(page, {
    key,
    label: 'UX Thing',
    label_plural: 'UX Things',
    fields: [
      { key: 'title', type: 'text', label: 'Title', required: true, indexed: true },
      { key: 'body', type: 'longtext', label: 'Body' },
      { key: 'contact', type: 'email', label: 'Contact' },
    ],
    display_field: 'title',
    slug_field: 'title',
  });
  return key;
}

test.describe('Records — editor UX', () => {
  test('a refused save names how many fields, focuses the first, and clears as it is fixed', async ({
    page,
  }) => {
    await login(page);
    const key = await seedTallType(page);
    await page.goto(`/admin/records/${key}/new`);

    await recordField(page, 'contact').fill('not-an-email');
    await page.getByRole('button', { name: 'Save', exact: true }).click();

    // R6, part one: a summary beside the button that appeared to do nothing…
    const summary = page.getByTestId('records-save-summary');
    await expect(summary).toHaveText('2 fields need attention');
    // …and focus on the first invalid field in *render* order, not in
    // whatever order the validator happened to report them.
    await expect(recordField(page, 'title')).toBeFocused();

    // R6, part two: the message goes as the value is corrected, without
    // another save.
    await recordField(page, 'title').fill('Now valid');
    await expect(recordFieldError(page, 'title')).toHaveCount(0);
    await expect(summary).toHaveText('1 field needs attention');
    await recordField(page, 'contact').fill('ada@example.com');
    await expect(summary).toHaveCount(0);
  });

  test('the form comes before the plumbing, and Slug/Position are behind Advanced', async ({
    page,
  }) => {
    await login(page);
    const key = await seedTallType(page);
    await page.goto(`/admin/records/${key}/new`);

    // R16: Status is in the header row, next to Cancel — and the first
    // control inside the page body is the record's own first field.
    await expect(page.locator('#record-status')).toBeVisible();
    const order = await page.evaluate(() => {
      const ids = ['record-status', 'record-field-title', 'record-slug'];
      return ids.map((id) => {
        const node = document.getElementById(id);
        return node ? node.getBoundingClientRect().top : -1;
      });
    });
    const [statusTop, titleTop, slugTop] = order;
    expect(statusTop).toBeLessThan(titleTop);
    expect(titleTop).toBeLessThan(slugTop);

    // Slug and Position are collapsed until asked for.
    const advanced = page.getByTestId('records-advanced-fields');
    await expect(advanced).toHaveJSProperty('open', false);
    await expect(page.locator('#record-slug')).toBeHidden();
    await advanced.getByText('Advanced', { exact: true }).click();
    await expect(page.locator('#record-slug')).toBeVisible();
    await expect(advanced).toContainText('Leave blank to derive it from Title.');
    await expect(advanced).toContainText('Orders this record in a public list');
  });

  test('creating a record is confirmed on the editor it lands on', async ({ page }) => {
    await login(page);
    const key = await seedTallType(page);
    await page.goto(`/admin/records/${key}/new`);

    await recordField(page, 'title').fill('Confirmed creation');
    await page.getByRole('button', { name: 'Save', exact: true }).click();

    // R22a: the create navigates, so the toast has to survive the visit.
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}/[0-9a-f]{32}$`));
    await expect(page.getByText('Record created', { exact: true })).toBeVisible();
    // …and only once: a reload of the same editor is not a creation.
    await page.reload();
    await expect(page.getByText('Record created', { exact: true })).toHaveCount(0);
  });

  test('a dropped connection says what happened and keeps the typed values', async ({ page }) => {
    await login(page);
    const key = await seedTallType(page);
    const record = await apiCreateRecord(page, key, { data: { title: 'Still here' } });
    await page.goto(`/admin/records/${key}/${record.uuid}`);

    await recordField(page, 'title').fill('Edited while offline');
    // R12a: the API is simply not there — `fetch` rejects rather than
    // answering, which used to surface as a raw "Failed to fetch".
    await page.route('**/api/records/types/**', (route) => route.abort('connectionrefused'));
    await page.getByRole('button', { name: 'Save', exact: true }).click();

    await expect(page.getByText(/Couldn't reach the server/)).toBeVisible();
    await expect(recordField(page, 'title')).toHaveValue('Edited while offline');
    await page.unroute('**/api/records/types/**');
  });

  test('leaving with unsaved changes asks first, and staying keeps them', async ({ page }) => {
    await login(page);
    const key = await seedTallType(page);
    const record = await apiCreateRecord(page, key, { data: { title: 'Guarded' } });
    await page.goto(`/admin/records/${key}/${record.uuid}`);

    // Nothing typed yet: Cancel just leaves (R12c must not nag).
    await expect(recordField(page, 'title')).toHaveValue('Guarded');
    await recordField(page, 'title').fill('Unsaved edit');

    // Dismissing the confirm keeps you on the page with the edit intact.
    let asked = 0;
    const dismiss = (dialog: { dismiss: () => Promise<void> }) => {
      asked += 1;
      void dialog.dismiss();
    };
    page.on('dialog', dismiss);
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect.poll(() => asked).toBe(1);
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}/${record.uuid}$`));
    await expect(recordField(page, 'title')).toHaveValue('Unsaved edit');

    // Accepting it lets the navigation through.
    page.off('dialog', dismiss);
    page.on('dialog', (dialog) => void dialog.accept());
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}$`));
  });

  test('the relation picker is a combobox that can be driven from the keyboard', async ({
    page,
  }) => {
    await login(page);
    const authorKey = await seedTextType(page, 'uxauthor', { field: 'name', label: 'UX Author' });
    for (const name of ['Kombu Alpha', 'Kombu Beta', 'Kombu Gamma']) {
      await apiCreateRecord(page, authorKey, { data: { name } });
    }
    const bookKey = uniqueTypeKey('uxbook');
    await apiCreateType(page, {
      key: bookKey,
      label: 'UX Book',
      fields: [
        { key: 'name', type: 'text', label: 'Name', indexed: true },
        {
          key: 'written_by',
          type: 'relation',
          label: 'Written By',
          // `many`, so the search input stays on screen after a pick — the
          // single-value picker hides it once it is filled.
          options: { target_type: authorKey, many: true, on_delete: 'set_null' },
        },
      ],
      display_field: 'name',
    });

    await page.goto(`/admin/records/${bookKey}/new`);
    const picker = page.getByTestId(`records-relation-written_by`);

    // R11: the group and its input carry the field's own name.
    await expect(picker).toHaveAttribute('aria-labelledby', 'record-field-written_by-label');
    const input = picker.getByRole('combobox', { name: 'Search Written By' });
    await expect(input).toHaveAttribute('aria-expanded', 'false');

    // R20: type, then drive the list with the keyboard only.
    await input.fill('Kombu');
    await expect(picker.getByRole('option').first()).toBeVisible();
    await expect(input).toHaveAttribute('aria-expanded', 'true');
    await expect(picker.getByRole('listbox')).toHaveCount(1);
    // R20: the count nobody announced before.
    await expect(picker.getByText('3 records found')).toHaveCount(1);

    // The order the API returns is not this test's business — what matters
    // is that Down moves the active option by exactly one and Enter takes
    // whichever one that is.
    const names = (await picker.getByRole('option').allTextContents()).map((name) => name.trim());
    expect(names).toHaveLength(3);
    await input.press('ArrowDown');
    await expect(input).toHaveAttribute(
      'aria-activedescendant',
      /records-relation-option-written_by-/,
    );
    await expect(picker.getByRole('option', { name: names[1] })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await input.press('Enter');

    // The pick becomes a chip whose remove button names what it removes.
    await expect(picker.getByRole('button', { name: `Remove ${names[1]}` })).toBeVisible();
    await expect(picker.getByRole('listbox')).toHaveCount(0);

    // Escape dismisses a reopened list without clearing what was typed.
    await input.fill('Kombu');
    await expect(picker.getByRole('listbox')).toHaveCount(1);
    await input.press('Escape');
    await expect(picker.getByRole('listbox')).toHaveCount(0);
    await expect(input).toHaveValue('Kombu');
  });

  test('a unique-value collision marks the field once, not also as a toast', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('uxcollide');
    await apiCreateType(page, {
      key,
      label: 'UX Collide',
      label_plural: 'UX Collides',
      fields: [
        { key: 'title', type: 'text', label: 'Title', required: true, indexed: true },
        { key: 'email', type: 'email', label: 'Email', unique: true, indexed: true },
      ],
      display_field: 'title',
    });
    await apiCreateRecord(page, key, { data: { title: 'First', email: 'dup@example.com' } });
    await page.goto(`/admin/records/${key}/new`);

    await recordField(page, 'title').fill('Second');
    await recordField(page, 'email').fill('dup@example.com');
    await page.getByRole('button', { name: 'Save', exact: true }).click();

    // R8b's inline mark is still there, sentence and all…
    await expect(recordFieldError(page, 'email')).toContainText('may be in the Trash');
    // …but a field that owns the collision no longer *also* gets a toast
    // saying the same thing a beat later (the double announcement UX-R26
    // was fixed to stop doing, that this collision picked back up).
    await expect(page.locator('[data-sonner-toast]')).toHaveCount(0);
  });
});
