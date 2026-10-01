import { expect, type Locator, type Page } from '@playwright/test';

import { apiCreateType, type FieldDef, type Json, uniqueTypeKey } from './records-api';

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

/** Open one field row's editing body. Rows collapse to a one-line summary
 *  (UX review R9), so anything inside the body has to be expanded first;
 *  a row added through `addFieldInEditor` opens by itself. */
export async function expandField(page: Page, index: number): Promise<void> {
  const row = fieldRow(page, index);
  if ((await row.getAttribute('data-field-expanded')) === 'true') return;
  await row.getByTestId('records-field-toggle').click();
  await expect(row).toHaveAttribute('data-field-expanded', 'true');
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

// ---- Seeds --------------------------------------------------------------

/** A type whose one field is an indexed text `title` (or `name`, via `field`)
 *  that is also its display field. `extra` is spread into the create body —
 *  `label`, `label_plural`, `is_public`, `translatable`, `show_in_menu` … —
 *  and `label` defaults to `Type <key>`. */
export async function seedTextType(
  page: Page,
  prefix: string,
  { field = 'title', ...extra }: { field?: string } & Json = {},
): Promise<string> {
  const key = uniqueTypeKey(prefix);
  await apiCreateType(page, {
    key,
    label: `Type ${key}`,
    ...extra,
    fields: [
      { key: field, type: 'text', label: field === 'title' ? 'Title' : 'Name', indexed: true },
    ],
    display_field: field,
  });
  return key;
}

/** An indexed text field whose label is its key, upper-cased. */
export function textField(key: string, extra: Partial<FieldDef> = {}): FieldDef {
  return { key, type: 'text', label: key.toUpperCase(), indexed: true, ...extra };
}

/** A type shaped like a seeded one — never a seeded type itself, which no
 *  type-editor test may edit. */
export async function seedReviewedType(
  page: Page,
  prefix: string,
  fields: FieldDef[],
): Promise<string> {
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

// ---- Import / export ----------------------------------------------------

export type ImportRow = { uuid?: string; locale?: string; data: Record<string, unknown> };

export function jsonFile(rows: ImportRow[]) {
  return {
    name: 'records.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({ records: rows })),
  };
}

/** A type with one indexed text field, its display field, and a free `note`. */
export async function seedIoType(page: Page, prefix: string, extra: Json = {}): Promise<string> {
  const key = uniqueTypeKey(prefix);
  await apiCreateType(page, {
    key,
    label: 'IO thing',
    label_plural: 'IO things',
    fields: [
      { key: 'title', type: 'text', label: 'Title', indexed: true },
      { key: 'note', type: 'text', label: 'Note' },
    ],
    display_field: 'title',
    ...extra,
  });
  return key;
}

/** Pick a file and wait for the dry-run report dialog it always opens. */
export async function importFile(page: Page, file: ReturnType<typeof jsonFile>): Promise<Locator> {
  await page.getByTestId('records-import-input').setInputFiles(file);
  const dialog = page.getByTestId('records-import-report');
  await expect(dialog).toBeVisible();
  return dialog;
}
