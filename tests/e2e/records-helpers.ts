import { expect, type Locator, type Page } from '@playwright/test';

/**
 * Shared plumbing for the `records-*.spec.ts` suite: the page objects, plus a
 * re-export of the JSON-API seeding layer in `records-api.ts` (split out for
 * the 300-line cap) so a spec has one import to reach for.
 *
 * Not a `.spec.ts` on purpose — Playwright's default `testMatch` only
 * collects `*.spec.ts`, so this file is importable without being run.
 */

export * from './records-api';

// ---- Page objects -------------------------------------------------------

/** One row of the schema editor's field list, by position. */
export function fieldRow(page: Page, index: number): Locator {
  return page.getByTestId('records-field-row').nth(index);
}

/** One schema-driven input on the record form. Located by its generated id
 *  (`record-field-<key>`) and not its label: `FieldShell` folds a
 *  screen-reader-only "Required" into every required field's label. */
export function recordField(page: Page, key: string): Locator {
  return page.locator(`#record-field-${key}`);
}

/** The inline error slot under one schema-driven input. */
export function recordFieldError(page: Page, key: string): Locator {
  return page.getByTestId(`records-field-error-${key}`);
}

export type EditorField = {
  key: string;
  type: string;
  label: string;
  required?: boolean;
  unique?: boolean;
  indexed?: boolean;
  choices?: { value: string; label: string }[];
  targetType?: string;
};

/**
 * Add one field through the schema editor's own controls.
 *
 * Order matters: picking a `type` resets that row's `options`, `constraints`
 * and `default` (`FieldRow::handleTypeChange`), so the key and the type go in
 * before anything type-specific does.
 */
export async function addFieldInEditor(
  page: Page,
  index: number,
  spec: EditorField,
): Promise<Locator> {
  await page.getByRole('button', { name: 'Add field' }).click();
  const row = fieldRow(page, index);
  await row.getByLabel('Key', { exact: true }).fill(spec.key);
  await row.getByLabel('Type', { exact: true }).selectOption(spec.type);
  await row.getByLabel('Label', { exact: true }).fill(spec.label);

  if (spec.required) await row.getByRole('checkbox', { name: 'Required' }).click();
  if (spec.unique) await row.getByRole('checkbox', { name: 'Unique' }).click();
  if (spec.indexed) await row.getByRole('checkbox', { name: 'Indexed' }).click();

  for (const [i, choice] of (spec.choices ?? []).entries()) {
    await row.getByRole('button', { name: 'Add choice' }).click();
    await row.getByLabel('Value', { exact: true }).nth(i).fill(choice.value);
    // "Label" is also the field's own label input, which sits before every
    // choice row in the DOM — hence the +1 offset rather than nth(i).
    await row
      .getByLabel('Label', { exact: true })
      .nth(i + 1)
      .fill(choice.label);
  }

  if (spec.targetType) {
    await row.getByLabel('Target type', { exact: true }).selectOption(spec.targetType);
  }
  return row;
}

/** The schema editor's save button. */
export async function saveType(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Save', exact: true }).click();
}

/**
 * Wait for a schema write to land, without relying on a toast.
 *
 * `TypeEditor` re-seeds its draft from the server's response on success, so
 * "Preview changes" goes back to disabled — that is the only on-screen
 * confirmation the page actually produces (see the REPORT: `AdminLayout`
 * mounts no `<Toaster>`, so every `toast.success` in this module is
 * swallowed).
 */
export async function expectTypeSaved(page: Page): Promise<void> {
  await expect(page.getByRole('button', { name: 'Preview changes' })).toBeDisabled();
}

/** Confirm an action behind the module's own `ConfirmDialog` (an `alertdialog`
 *  whose confirm button is scoped to the dialog, since the trigger behind it
 *  often carries a similar name). The confirm label is passed in rather than
 *  assumed to repeat the trigger's: a record delete is triggered by "Delete"
 *  and confirmed by "Move to Trash" (U15 — the dialog says what actually
 *  happens). No typed-phrase gate, unlike `helpers.ts::clickAndConfirm`:
 *  only `DeleteTypeSection` asks for one, and it asks for a record count. */
export async function confirmDialog(
  page: Page,
  trigger: Locator,
  confirmLabel: RegExp | string,
): Promise<void> {
  await trigger.click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: confirmLabel }).click();
  await expect(dialog).toHaveCount(0);
}

/** Apply one filter term through the filter bar. */
export async function applyFilter(
  page: Page,
  field: string,
  op: string,
  value?: string,
): Promise<void> {
  await page.locator('#records-filter-field').selectOption(field);
  await page.locator('#records-filter-op').selectOption(op);
  if (value !== undefined) {
    // `status` is the one field whose value control is a `<select>` — the
    // bar swaps the input out for a two-option list rather than trusting
    // free text against an enum.
    const input = page.locator('#records-filter-value');
    const tag = await input.evaluate((node) => node.tagName);
    if (tag === 'SELECT') await input.selectOption(value);
    else await input.fill(value);
  }
  await page.getByRole('button', { name: 'Apply' }).click();
}

/** The display titles currently rendered in the record table, in order. */
export async function rowTitles(page: Page): Promise<string[]> {
  const rows = page.getByTestId('records-record-row');
  return rows.evaluateAll((nodes) =>
    nodes.map((node) => node.querySelector('td a')?.textContent?.trim() ?? ''),
  );
}
