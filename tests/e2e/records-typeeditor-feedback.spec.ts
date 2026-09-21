import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateType,
  apiDeleteType,
  type FieldDef,
  fieldRow,
  saveType,
  uniqueTypeKey,
} from './records-helpers';

/**
 * What the type editor tells the operator — the second half of the
 * 2026-09-20 UX review's verification pass, split from
 * `records-typeeditor-ux.spec.ts` for the 300-line cap along the seam
 * between what the editor *does* (that file: collapsing rows, reordering,
 * forcing a change through) and what it *says back*:
 *
 * - R6, both halves: a 422 the schema as a whole owns (`__root__`), which
 *   used to render nowhere at all, and one that names a field, which used
 *   to open its row and nothing else.
 * - R19's plural guess, which used to offer "Blog Postses".
 * - An icon name the framework cannot draw.
 * - R4's containment, on the one screen it had not reached: at 390 px the
 *   editor scrolled sideways.
 */

function textField(key: string, extra: Partial<FieldDef> = {}): FieldDef {
  return { key, type: 'text', label: key.toUpperCase(), indexed: true, ...extra };
}

/** A type shaped like a seeded one — never a seeded type itself, which no
 *  test here may edit. */
async function seed(page: Page, prefix: string, fields: FieldDef[]): Promise<string> {
  const key = uniqueTypeKey(prefix);
  await apiCreateType(page, {
    key,
    label: `Reviewed ${key}`,
    label_plural: `Reviewed ${key} things`,
    description: 'What this type is for.',
    icon: 'package',
    fields,
    display_field: fields[0].key,
  });
  return key;
}

test.describe('Records — type editor feedback', () => {
  test('R6: a refusal the schema as a whole owns is said out loud', async ({ page }) => {
    await login(page);
    const key = await seed(page, 'r6root', [textField('title')]);

    await page.goto(`/admin/records/types/${key}`);
    // A field added and left unnamed: the server refuses the *list*, not any
    // one field, so the 422 comes back keyed `__root__`. That used to be
    // filtered out of the metadata form and matched no row either, so Save
    // went back to its idle label having changed nothing on screen at all.
    await page.getByRole('button', { name: 'Add field' }).click();
    await fieldRow(page, 1).getByLabel('Label', { exact: true }).fill('Nameless');
    await saveType(page);

    const stranded = page.getByTestId('records-type-save-errors');
    await expect(stranded).toBeVisible();
    await expect(stranded).toContainText("every field needs a 'key'");
    await expect(stranded).toHaveAttribute('role', 'alert');
    // And the save was genuinely refused — the draft is still dirty.
    await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeEnabled();

    await apiDeleteType(page, key, 0);
  });

  test('R6: a refusal naming a field counts it, opens it and goes there', async ({ page }) => {
    await login(page);
    const key = await seed(page, 'r6field', [
      textField('title'),
      textField('note'),
      textField('extra'),
    ]);

    await page.goto(`/admin/records/types/${key}`);
    const row = fieldRow(page, 2);
    await row.getByTestId('records-field-toggle').click();
    await row.getByLabel('Label', { exact: true }).fill('');
    // Collapsed again, and the button pressed from the bottom of the page:
    // the refusal is about a row that is neither open nor on screen.
    await row.getByTestId('records-field-toggle').click();
    await expect(row).toHaveAttribute('data-field-expanded', 'false');
    await saveType(page);

    await expect(page.getByTestId('records-type-save-summary')).toContainText(
      '1 field needs attention',
    );
    await expect(row).toHaveAttribute('data-field-expanded', 'true');
    await expect(row.getByText('label must be a non-empty string')).toBeVisible();
    // Focus followed, so the keyboard is already where the fix has to be made.
    await expect(row.locator(':focus')).toHaveCount(1);

    await apiDeleteType(page, key, 0);
  });

  test('the type editor fits a 390 px viewport', async ({ page }) => {
    await login(page);
    // A seeded-shaped type: the badges on a `required`/`unique`/`indexed`
    // field are what used to make a row's min-content 473 px wide, and a CSS
    // grid hands that width to the row, the list and the document (R4's
    // containment covered the record list and the hub only).
    const key = await seed(page, 'r4te', [
      textField('name', { required: true, unique: true }),
      textField('website', { indexed: false }),
      { key: 'employees', type: 'integer', label: 'Employees', indexed: true },
      { key: 'founded', type: 'date', label: 'Founded', indexed: true },
      { key: 'notes', type: 'longtext', label: 'Notes', indexed: false },
    ]);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/admin/records/types/${key}`);
    await expect(page.getByTestId('records-field-row')).toHaveCount(5);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390,
    );

    // Expanded too — every input in a row is inside the same 390 px.
    await fieldRow(page, 0).getByTestId('records-field-toggle').click();
    await expect(fieldRow(page, 0)).toHaveAttribute('data-field-expanded', 'true');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      390,
    );
    expect(await page.evaluate(() => document.body.scrollWidth)).toBeLessThanOrEqual(390);

    await apiDeleteType(page, key, 0);
  });

  test('an icon name the framework cannot draw falls back, and the field says so', async ({
    page,
  }) => {
    await login(page);
    const key = uniqueTypeKey('icon');
    await apiCreateType(page, {
      key,
      label: `Icon ${key}`,
      label_plural: `Icon ${key} things`,
      // A real lucide-react name, and not one of `NavIcon`'s allowlist — the
      // old help text promised any lucide icon and this one drew nothing.
      icon: 'flask-conical',
      fields: [{ key: 'title', type: 'text', label: 'Title', indexed: true }],
      display_field: 'title',
    });

    await page.goto(`/admin/records/types/${key}`);
    const preview = page.getByTestId('records-type-icon-preview');
    await expect(preview).toHaveAttribute('data-icon', 'database');
    await expect(preview.locator('svg')).toHaveCount(1);
    // The note names the icon that will actually be drawn instead. (The
    // Icon field's help text was rewritten in the same pass to name the
    // allowlist rather than promise "any lucide-react icon"; it is not
    // asserted here because the running host loaded its catalog at boot.)
    const unknown = page.getByTestId('records-type-icon-unknown');
    await expect(unknown).toContainText('flask-conical');
    await expect(unknown).toContainText('database');

    // A name it can draw is drawn, and the note goes away.
    await page.locator('#type-editor-icon').fill('tag');
    await expect(preview).toHaveAttribute('data-icon', 'tag');
    await expect(page.getByTestId('records-type-icon-unknown')).toHaveCount(0);

    // The hub row draws the fallback rather than leaving a hole.
    await page.goto('/admin/records/');
    const row = page.locator(`[data-testid="records-type-row"][data-type-key="${key}"]`);
    await expect(row.getByTestId('records-type-icon')).toHaveAttribute('data-icon', 'database');
    await expect(row.locator('svg')).toHaveCount(1);

    await apiDeleteType(page, key, 0);
  });

  test('R19: the plural guess leaves an already-plural label alone', async ({ page }) => {
    await login(page);
    // Nothing is created: the guess happens while typing, before any save.
    await page.goto('/admin/records/types/new');

    await page.locator('#type-editor-label').fill('Review Note');
    await expect(page.locator('#type-editor-label-plural')).toHaveValue('Review Notes');

    // The rough edge: every `s` ending used to take another `es`.
    await page.locator('#type-editor-label').fill('Blog Posts');
    await expect(page.locator('#type-editor-label-plural')).toHaveValue('Blog Posts');

    // And a singular no suffix rule reaches is left for the operator to
    // write, rather than guessed at as "Contact Persons".
    await page.locator('#type-editor-label').fill('Contact Person');
    await expect(page.locator('#type-editor-label-plural')).toHaveValue('Contact Person');

    await page.locator('#type-editor-label').fill('City');
    await expect(page.locator('#type-editor-label-plural')).toHaveValue('Cities');
  });
});
