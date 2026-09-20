import { expect, type Locator, type Page } from '@playwright/test';

/**
 * Shared plumbing for the `records-*.spec.ts` suite.
 *
 * Not a `.spec.ts` on purpose — Playwright's default `testMatch` only
 * collects `*.spec.ts`, so this file is importable without being run.
 *
 * Seeding goes through the module's own JSON API (`/api/records/*`) with
 * `page.request`, which shares the logged-in context's cookie jar. Records
 * writes ride the framework's `SameSite=Lax` baseline and opt into no CSRF
 * token (see `sm_records/utils/api.ts`), so unlike `csrfHeader()` for
 * pagebuilder there is no header to attach here.
 */

const BASE = '/api/records';

export type Json = Record<string, unknown>;

export type FieldDef = {
  key: string;
  type: string;
  label: string;
  required?: boolean;
  unique?: boolean;
  indexed?: boolean;
  default?: unknown;
  help?: string | null;
  constraints?: Json;
  options?: Json;
};

export type TypeRead = {
  key: string;
  label: string;
  label_plural: string;
  fields: Required<FieldDef>[];
  version: number;
  schema_version: number;
  display_field: string | null;
  slug_field: string | null;
  record_count: number;
  trashed_record_count: number;
  reindex_pending: Record<string, string>;
  translatable: boolean;
};

export type RecordRead = {
  uuid: string;
  version: number;
  data: Json;
  display_title: string;
  status: string;
  slug: string | null;
  locale: string;
  translation_group: string;
  position: number;
  is_deleted: boolean;
  invalid: { field: string; message: string }[];
};

export type RecordPage = { items: RecordRead[]; total: number; page: number; page_size: number };

/**
 * A type key that is unique per run and still satisfies the server's
 * `^[a-z][a-z0-9_]*$` / 64-character rule — and is never `types` or `new`,
 * both of which would shadow a view route (`constants.RESERVED_TYPE_KEYS`).
 */
export function uniqueTypeKey(prefix = 'e2e'): string {
  const stamp = Date.now().toString(36);
  const salt = Math.random().toString(36).slice(2, 6);
  return `${prefix}_${stamp}_${salt}`.toLowerCase();
}

async function api<T>(
  page: Page,
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  data?: Json,
): Promise<T> {
  const response = await page.request.fetch(`${BASE}${path}`, {
    method,
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    ...(data === undefined ? {} : { data }),
  });
  if (!response.ok()) {
    throw new Error(`${method} ${path} → ${response.status()}: ${await response.text()}`);
  }
  if (response.status() === 204) return undefined as T;
  return (await response.json()) as T;
}

// ---- Types --------------------------------------------------------------

export function apiCreateType(page: Page, body: Json): Promise<TypeRead> {
  return api(page, 'POST', '/types', body);
}

export function apiGetType(page: Page, key: string): Promise<TypeRead> {
  return api(page, 'GET', `/types/${key}`);
}

export function apiUpdateType(
  page: Page,
  key: string,
  expectedVersion: number,
  changes: Json,
): Promise<TypeRead> {
  return api(page, 'PUT', `/types/${key}`, { expected_version: expectedVersion, ...changes });
}

export function apiListTypes(page: Page): Promise<{ items: TypeRead[] }> {
  return api(page, 'GET', '/types');
}

export async function apiDeleteType(page: Page, key: string, count: number): Promise<void> {
  await api(page, 'DELETE', `/types/${key}?confirm_record_count=${count}`);
}

// ---- Records ------------------------------------------------------------

export function apiCreateRecord(page: Page, key: string, body: Json): Promise<RecordRead> {
  return api(page, 'POST', `/types/${key}/records`, body);
}

export function apiGetRecord(page: Page, key: string, uuid: string): Promise<RecordRead> {
  return api(page, 'GET', `/types/${key}/records/${uuid}`);
}

export function apiUpdateRecord(
  page: Page,
  key: string,
  uuid: string,
  expectedVersion: number,
  body: Json,
): Promise<RecordRead> {
  return api(page, 'PUT', `/types/${key}/records/${uuid}`, {
    expected_version: expectedVersion,
    ...body,
  });
}

export function apiListRecords(page: Page, key: string, query = ''): Promise<RecordPage> {
  return api(page, 'GET', `/types/${key}/records${query ? `?${query}` : ''}`);
}

// ---- Translations ---------------------------------------------------------

export function apiListTranslations(page: Page, key: string, uuid: string): Promise<Json[]> {
  return api(page, 'GET', `/types/${key}/records/${uuid}/translations`);
}

export function apiCreateTranslation(
  page: Page,
  key: string,
  uuid: string,
  body: Json,
): Promise<RecordRead> {
  return api(page, 'POST', `/types/${key}/records/${uuid}/translations`, body);
}

// ---- Page objects -------------------------------------------------------

/** One row of the schema editor's field list, by position. */
export function fieldRow(page: Page, index: number): Locator {
  return page.getByTestId('records-field-row').nth(index);
}

/** One schema-driven input on the record form. Located by its generated id
 *  (`record-field-<key>`) rather than its label: `FieldShell` folds a
 *  screen-reader-only "Required" into the label of every required field, so
 *  an exact label match would miss exactly the fields a test cares about. */
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
 *  whose confirm button repeats the trigger's label, so it has to be scoped
 *  to the dialog). Unlike `helpers.ts::clickAndConfirm` there is no typed
 *  phrase gate here — only `DeleteTypeSection` asks for one, and it asks for
 *  a record count rather than a phrase. */
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
