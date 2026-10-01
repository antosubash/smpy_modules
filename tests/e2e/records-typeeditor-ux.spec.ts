import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import {
  addFieldInEditor,
  apiCreateRecord,
  apiDeleteType,
  expectTypeSaved,
  fieldRow,
  saveType,
  seedReviewedType,
  textField,
  uniqueTypeKey,
} from './records-helpers';

/**
 * The type editor and the Record Types hub after the 2026-09-20 UX review:
 * R7 (a forced change's report survives, and the worklist is re-derivable),
 * R9 (collapsed field rows and choices), R10 (the reorder arrows move twice
 * and keep focus), R12c (unsaved work is guarded), R13 (the hub leads to
 * records), R19 (the permanent key gets help before it is typed) and R22b.
 */

/** The field keys on screen, in order, read off the collapsed summaries. */
async function fieldKeys(page: Page): Promise<string[]> {
  return page.getByTestId('records-field-key').allInnerTexts();
}

test.describe('Records — type editor UX', () => {
  test('R9: field rows collapse to a summary and expand on click', async ({ page }) => {
    await login(page);
    const key = await seedReviewedType(page, 'r9', [
      textField('title', { required: true }),
      textField('note', { indexed: false }),
    ]);

    await page.goto(`/admin/records/types/${key}`);
    const first = fieldRow(page, 0);
    await expect(first).toHaveAttribute('data-field-expanded', 'false');
    // The summary carries key, type and the flags — and nothing else.
    const summary = first.getByTestId('records-field-toggle');
    await expect(summary).toContainText('title');
    await expect(summary).toContainText('text');
    await expect(summary).toContainText('Required');
    await expect(summary).toContainText('Indexed');
    await expect(first.getByLabel('Help text', { exact: true })).toHaveCount(0);
    // U6: the "Indexed" hint is in the card header once, unrepeated.
    await expect(page.getByText(/Tick "Indexed" on the fields worth filtering/)).toHaveCount(1);
    await expect(page.getByText(/Indexed fields can be filtered and sorted/)).toHaveCount(0);

    await summary.click();
    await expect(first).toHaveAttribute('data-field-expanded', 'true');
    await expect(first.getByLabel('Help text', { exact: true })).toBeVisible();
    // Expanding brings back the checkbox's own consequence, wired to it.
    await expect(first.getByText(/Indexed fields can be filtered and sorted/)).toHaveCount(1);
    const box = first.getByRole('checkbox', { name: 'Indexed' });
    await expect(box).toHaveAttribute('aria-describedby', /-indexed-hint$/);
    // The other row is untouched — expanding is per row.
    await expect(fieldRow(page, 1)).toHaveAttribute('data-field-expanded', 'false');

    await summary.click();
    await expect(first).toHaveAttribute('data-field-expanded', 'false');

    await apiDeleteType(page, key, 0);
  });

  test('R9: a select field collapses its choices and takes a pasted list', async ({ page }) => {
    await login(page);
    const key = await seedReviewedType(page, 'r9c', [
      textField('title'),
      {
        key: 'colour',
        type: 'select',
        label: 'Colour',
        options: {
          choices: [
            { value: 'red', label: 'Red' },
            { value: 'green', label: 'Green' },
          ],
        },
      },
    ]);

    await page.goto(`/admin/records/types/${key}`);
    const row = fieldRow(page, 1);
    await row.getByTestId('records-field-toggle').click();
    // Collapsed: a count, not fifty editable rows.
    await expect(row.getByTestId('records-choices-count')).toHaveText('2 choices');
    await expect(row.getByLabel('Value', { exact: true })).toHaveCount(0);

    await row.getByTestId('records-choices-toggle').click();
    await expect(row.getByLabel('Value', { exact: true })).toHaveCount(2);

    await row.getByTestId('records-choices-paste').click();
    await row.getByTestId('records-choices-bulk').fill('blue | Blue\nteal');
    await row.getByRole('button', { name: 'Add these' }).click();
    await expect(row.getByTestId('records-choices-count')).toHaveText('4 choices');
    await expect(row.getByLabel('Label', { exact: true }).nth(4)).toHaveValue('teal');

    await saveType(page);
    await expectTypeSaved(page);
    await apiDeleteType(page, key, 0);
  });

  test('R10: Move up twice moves a field two positions and keeps focus', async ({ page }) => {
    await login(page);
    const key = await seedReviewedType(page, 'r10', [
      textField('alpha'),
      textField('bravo'),
      textField('charlie'),
    ]);

    await page.goto(`/admin/records/types/${key}`);
    await expect(page.getByTestId('records-field-row')).toHaveCount(3);
    expect(await fieldKeys(page)).toEqual(['alpha', 'bravo', 'charlie']);

    // Keyboard only: focus the button once and press it twice. With rows
    // keyed by index this used to put `charlie` back where it started.
    await fieldRow(page, 2).getByRole('button', { name: 'Move up' }).focus();
    await page.keyboard.press('Enter');
    await expect.poll(() => fieldKeys(page)).toEqual(['alpha', 'charlie', 'bravo']);
    await page.keyboard.press('Enter');
    await expect.poll(() => fieldKeys(page)).toEqual(['charlie', 'alpha', 'bravo']);

    // Focus travelled with the field, not with the position.
    await expect(fieldRow(page, 0).locator(':focus')).toHaveCount(1);

    await saveType(page);
    await expectTypeSaved(page);
    await apiDeleteType(page, key, 0);
  });

  test('R7: a forced change leaves its report, and "Check records" is honest', async ({ page }) => {
    await login(page);
    const key = await seedReviewedType(page, 'r7', [
      textField('title'),
      textField('note', { indexed: false }),
    ]);
    await apiCreateRecord(page, key, { data: { title: 'One' } });
    await apiCreateRecord(page, key, { data: { title: 'Two' } });

    await page.goto(`/admin/records/types/${key}`);
    await fieldRow(page, 1).getByTestId('records-field-toggle').click();
    await fieldRow(page, 1).getByRole('checkbox', { name: 'Required' }).click();
    await saveType(page);

    const report = page.getByTestId('records-schema-report');
    await expect(report).toBeVisible();
    await report.getByRole('button', { name: /Apply anyway/ }).click();
    await page.getByRole('alertdialog').getByRole('button', { name: 'Apply anyway' }).click();
    await expectTypeSaved(page);

    // R7a: the only inventory of what the force just broke is still here.
    const last = page.getByTestId('records-last-applied-report');
    await expect(last).toBeVisible();
    await expect(last).toContainText('Last applied change left 2 records invalid');
    await expect(last.getByTestId('records-last-applied-sample').getByRole('link')).toHaveCount(2);
    await expect(last.getByTestId('records-copy-uuids')).toBeVisible();

    // R7b: "Check records" dry-runs the schema exactly as saved. It sends
    // `rescan: true`, because the saved schema is its own diff and the server
    // would otherwise skip the scan and answer "0 would fail" about records
    // it never looked at. With the flag it re-derives the worklist the forced
    // apply left behind — the two records above, by name.
    await page.getByTestId('records-check-records').click();
    const preview = page.getByTestId('records-schema-preview');
    await expect(preview).toBeVisible();
    await expect(preview.getByTestId('records-check-records-title')).toBeVisible();
    await expect(preview).toContainText('2 records checked, 2 would fail');

    await apiDeleteType(page, key, 2);
  });

  test('R22b: Save is disabled until something changes', async ({ page }) => {
    await login(page);
    const key = await seedReviewedType(page, 'r22', [textField('title')]);

    await page.goto(`/admin/records/types/${key}`);
    const save = page.getByRole('button', { name: 'Save', exact: true });
    await expect(save).toBeDisabled();
    await expect(page.getByTestId('records-no-changes')).toBeVisible();

    // Metadata alone counts, which `schemaIsDirty` on its own never saw.
    await page.locator('#type-editor-description').fill('Changed.');
    await expect(save).toBeEnabled();
    await expect(page.getByTestId('records-no-changes')).toHaveCount(0);

    await saveType(page);
    await expectTypeSaved(page);
    await expect(save).toBeDisabled();

    await apiDeleteType(page, key, 0);
  });

  test('R12c: leaving with unsaved edits asks first, and Cancel respects it', async ({ page }) => {
    await login(page);
    const key = await seedReviewedType(page, 'r12', [textField('title')]);

    await page.goto(`/admin/records/types/${key}`);
    await page.locator('#type-editor-description').fill('Unsaved.');

    // Refuse the confirm: the edit and the page both survive.
    let asked = '';
    page.once('dialog', (dialog) => {
      asked = dialog.message();
      void dialog.dismiss();
    });
    await page.getByRole('button', { name: 'Cancel' }).click();
    expect(asked).toContain('unsaved changes');
    await expect(page).toHaveURL(new RegExp(`/admin/records/types/${key}$`));
    await expect(page.locator('#type-editor-description')).toHaveValue('Unsaved.');

    // Accept it and the navigation goes through.
    page.once('dialog', (dialog) => void dialog.accept());
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page).toHaveURL(/\/admin\/records\/?$/);

    await apiDeleteType(page, key, 0);
  });

  test('R13: the hub row leads to the records, with the icon and description', async ({ page }) => {
    await login(page);
    const key = await seedReviewedType(page, 'r13', [textField('title')]);

    await page.goto('/admin/records/');
    await expect(page.getByRole('heading', { name: 'Records', exact: true })).toBeVisible();
    await expect(page.getByText('Every record type in this install.')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Record Types' })).toBeVisible();

    const row = page.locator(`[data-testid="records-type-row"][data-type-key="${key}"]`);
    await expect(row.getByTestId('records-type-description')).toHaveText('What this type is for.');
    await expect(row.locator('svg')).toHaveCount(1);

    // Schema editing is a row action now, not the row's headline link.
    await row.getByTestId('records-type-edit-schema').click();
    await expect(page).toHaveURL(new RegExp(`/admin/records/types/${key}$`));

    await page.goto('/admin/records/');
    await row.getByTestId('records-type-link').click();
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}$`));

    await apiDeleteType(page, key, 0);
  });

  test('R19: the new-type form derives the key, checks it, and defers the pointers', async ({
    page,
  }) => {
    await login(page);
    await page.goto('/admin/records/types/new');
    await expect(page.getByRole('heading', { name: 'New type' })).toBeVisible();

    // Nothing to point at yet, and the form says so rather than showing
    // "None" with no options.
    await expect(page.locator('#type-editor-display-field')).toBeDisabled();
    await expect(page.locator('#type-editor-slug-field')).toBeDisabled();
    await expect(page.getByText('Add a field first.')).toHaveCount(2);
    await expect(page.getByText(/Chosen once — this can't be changed later/)).toBeVisible();

    // Key and plural label are derived from the label until they are typed.
    await page.locator('#type-editor-label').fill('Review Note');
    await expect(page.locator('#type-editor-key')).toHaveValue('review_note');
    await expect(page.locator('#type-editor-label-plural')).toHaveValue('Review Notes');

    // And the key answers to the same rule a field key does, inline.
    await page.locator('#type-editor-key').fill('Review Note');
    await expect(page.getByTestId('records-type-key-error')).toContainText(
      'Must start with a lowercase letter',
    );
    // Typed by hand, the key is no longer derived from the label.
    await page.locator('#type-editor-label').fill('Review Notice');
    await expect(page.locator('#type-editor-key')).toHaveValue('Review Note');

    const key = uniqueTypeKey('r19');
    await page.locator('#type-editor-key').fill(key);
    await expect(page.getByTestId('records-type-key-error')).toHaveCount(0);

    await addFieldInEditor(page, 0, { key: 'title', type: 'text', label: 'Title', indexed: true });
    await expect(page.locator('#type-editor-display-field')).toBeEnabled();
    await page.locator('#type-editor-display-field').selectOption('title');

    await saveType(page);
    await expect(page).toHaveURL(new RegExp(`/admin/records/types/${key}$`));
    await apiDeleteType(page, key, 0);
  });
});
