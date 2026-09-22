import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateRecord,
  apiCreateType,
  apiGetRecord,
  apiUpdateRecord,
  confirmDialog,
  recordField,
  recordFieldError,
  uniqueTypeKey,
} from './records-helpers';

/**
 * The generic, schema-driven record form (design §12's `RecordEditor.tsx`):
 * one input per field kind, the client validator that mirrors
 * `schema/_builders.py`, the 409 conflict panel that §12 insists must be a
 * real screen state rather than a toast, and delete/restore.
 */

const KITCHEN_SINK = [
  { key: 'title', type: 'text', label: 'Title', required: true, indexed: true },
  { key: 'body', type: 'longtext', label: 'Body' },
  { key: 'price', type: 'number', label: 'Price', indexed: true },
  { key: 'qty', type: 'integer', label: 'Quantity', indexed: true },
  { key: 'flag', type: 'boolean', label: 'Flag', indexed: true },
  { key: 'due', type: 'date', label: 'Due' },
  { key: 'starts', type: 'datetime', label: 'Starts' },
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
  {
    key: 'tags',
    type: 'multiselect',
    label: 'Tags',
    options: {
      choices: [
        { value: 'a', label: 'Alpha' },
        { value: 'b', label: 'Beta' },
      ],
    },
  },
  { key: 'contact', type: 'email', label: 'Contact' },
  { key: 'link', type: 'url', label: 'Link' },
  { key: 'meta', type: 'json', label: 'Meta' },
];

/** A type holding one field of every kind, plus a seeded relation target. */
async function seedSinkType(page: Page): Promise<{ key: string; targetKey: string }> {
  const targetKey = uniqueTypeKey('rel');
  await apiCreateType(page, {
    key: targetKey,
    label: 'Owner',
    fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
    display_field: 'name',
  });
  await apiCreateRecord(page, targetKey, { data: { name: 'Ada Lovelace' }, status: 'published' });

  const key = uniqueTypeKey('crud');
  await apiCreateType(page, {
    key,
    label: 'Thing',
    label_plural: 'Things',
    fields: [
      ...KITCHEN_SINK,
      { key: 'owner', type: 'relation', label: 'Owner', options: { target_type: targetKey } },
    ],
    display_field: 'title',
    slug_field: 'title',
  });
  return { key, targetKey };
}

test.describe('Records — record CRUD', () => {
  test('creates a record through the form, one value per field kind', async ({ page }) => {
    test.setTimeout(120_000);
    await login(page);
    const { key, targetKey } = await seedSinkType(page);

    await page.goto(`/admin/records/${key}`);
    await expect(page.getByRole('heading', { name: 'Things' })).toBeVisible();
    await expect(page.getByText('No records yet')).toBeVisible();

    // The empty state carries its own "New record" call to action now
    // (UX-R1), so this has to say which of the two it means — and the one
    // inside the box is the one an empty type's reader actually reaches for.
    await page.getByTestId('records-empty-state').getByRole('link', { name: 'New record' }).click();
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}/new$`));

    await recordField(page, 'title').fill('First thing');
    await recordField(page, 'body').fill('Long body text.');
    await recordField(page, 'price').fill('9.99');
    await recordField(page, 'qty').fill('42');
    await recordField(page, 'flag').click();
    await recordField(page, 'due').fill('2026-03-04');
    await recordField(page, 'starts').fill('2026-03-04T05:06:07');
    await recordField(page, 'colour').selectOption('green');
    // One checkbox per choice, located by label: the ids are index-based
    // now, since a value with a space made one no selector could reach.
    await page.getByRole('checkbox', { name: 'Alpha', exact: true }).click();
    await page.getByRole('checkbox', { name: 'Beta', exact: true }).click();
    await recordField(page, 'contact').fill('ada@example.com');
    await recordField(page, 'link').fill('https://example.com/a');
    await recordField(page, 'meta').fill('{"k": 1}');

    // The relation is picked through `RelationPicker`, which searches the
    // target type on `display_title:contains:` and stores `{type, uuid}`.
    const picker = page.getByTestId('records-relation-owner');
    await picker.getByRole('combobox').fill('Ada');
    await picker.getByRole('option', { name: 'Ada Lovelace' }).click();
    await expect(picker.getByText('Ada Lovelace')).toBeVisible();

    await page.locator('#record-status').selectOption('published');
    await page.getByRole('button', { name: 'Save', exact: true }).click();

    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}/[0-9a-f]{32}$`));
    const uuid = page.url().split('/').pop() as string;
    const stored = await apiGetRecord(page, key, uuid);

    expect(stored.data.title).toBe('First thing');
    expect(stored.data.body).toBe('Long body text.');
    expect(stored.data.price).toBe('9.99');
    expect(stored.data.qty).toBe(42);
    expect(stored.data.flag).toBe(true);
    expect(stored.data.due).toBe('2026-03-04');
    expect(String(stored.data.starts)).toContain('2026-03-04T05:06:07');
    expect(stored.data.colour).toBe('green');
    expect(stored.data.tags).toEqual(['a', 'b']);
    expect(stored.data.contact).toBe('ada@example.com');
    expect(stored.data.link).toBe('https://example.com/a');
    expect(stored.data.meta).toEqual({ k: 1 });
    expect((stored.data.owner as { type: string }).type).toBe(targetKey);
    expect(stored.display_title).toBe('First thing');
    expect(stored.slug).toBe('first-thing');
    expect(stored.status).toBe('published');

    // …and the list now shows it under its display title.
    await page.goto(`/admin/records/${key}`);
    const row = page.locator(`[data-testid="records-record-row"][data-record-uuid="${uuid}"]`);
    await expect(row.getByRole('link', { name: 'First thing' })).toBeVisible();
    await expect(row).toContainText('Published');
  });

  test('shows inline validation errors before anything is sent', async ({ page }) => {
    await login(page);
    const { key } = await seedSinkType(page);
    await page.goto(`/admin/records/${key}/new`);
    await expect(page.getByRole('heading', { name: 'New record' })).toBeVisible();

    await recordField(page, 'contact').fill('not-an-email');
    await recordField(page, 'price').fill('1.234567');
    await recordField(page, 'qty').fill('1.5');
    await recordField(page, 'link').fill('ftp://nope');
    await recordField(page, 'meta').fill('{not json');
    await page.getByRole('button', { name: 'Save', exact: true }).click();

    // Required first — `title` was never filled in.
    await expect(recordFieldError(page, 'title')).toHaveText('This field is required');
    await expect(recordFieldError(page, 'contact')).toHaveText('Not a valid email address');
    await expect(recordFieldError(page, 'qty')).toHaveText('Must be a whole number');
    await expect(recordFieldError(page, 'link')).toContainText('http:// or https:// URL');
    await expect(recordFieldError(page, 'meta')).toHaveText('Not valid JSON');
    // The five-decimal `Numeric(19, 5)` contract of design §7.3.
    await expect(recordFieldError(page, 'price')).toContainText('decimal places are stored');
    // Nothing was written: the client validator short-circuits the save.
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}/new$`));
  });

  test('flags a choice that is not on the schema after a raw-JSON edit', async ({ page }) => {
    await login(page);
    const { key } = await seedSinkType(page);
    await page.goto(`/admin/records/${key}/new`);
    await expect(page.getByRole('heading', { name: 'New record' })).toBeVisible();

    // The raw editor is the only way to put a value the form cannot express
    // into `colour` — which is exactly what makes it the way to prove the
    // choice check is real rather than an artefact of the `<select>`.
    await page.getByRole('button', { name: /Advanced: edit raw JSON/ }).click();
    await page.locator('#record-data').fill('{"title": "Raw", "colour": "chartreuse"}');
    await page.getByRole('button', { name: /Back to the form/ }).click();
    await page.getByRole('button', { name: 'Save', exact: true }).click();

    await expect(recordFieldError(page, 'colour')).toHaveText('Not one of the configured choices');
  });

  test('edits a record and re-renders its derived title', async ({ page }) => {
    await login(page);
    const { key } = await seedSinkType(page);
    const record = await apiCreateRecord(page, key, { data: { title: 'Before' } });

    await page.goto(`/admin/records/${key}/${record.uuid}`);
    await expect(page.getByRole('heading', { name: 'Before' })).toBeVisible();
    await recordField(page, 'title').fill('After');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect
      .poll(async () => (await apiGetRecord(page, key, record.uuid)).data.title)
      .toBe('After');

    const stored = await apiGetRecord(page, key, record.uuid);
    expect(stored.data.title).toBe('After');
    expect(stored.display_title).toBe('After');
    expect(stored.version).toBe(record.version + 1);

    await page.goto(`/admin/records/${key}`);
    await expect(page.getByRole('link', { name: 'After' })).toBeVisible();
  });

  test('a concurrent write lands in the conflict panel, not a toast', async ({ page }) => {
    await login(page);
    const { key } = await seedSinkType(page);
    const record = await apiCreateRecord(page, key, { data: { title: 'Mine' } });

    await page.goto(`/admin/records/${key}/${record.uuid}`);
    await recordField(page, 'title').fill('My edit');

    // Someone else saves between the load and the save.
    await apiUpdateRecord(page, key, record.uuid, record.version, {
      data: { title: 'Their edit' },
    });

    await page.getByRole('button', { name: 'Save', exact: true }).click();
    const panel = page.getByTestId('records-conflict-panel');
    await expect(panel).toBeVisible();
    await expect(panel).toContainText('This record changed while you were editing');
    await expect(panel).toContainText('Their edit');
    await expect(panel).toContainText('My edit');

    await panel.getByRole('button', { name: 'Reload' }).click();
    await expect(panel).toHaveCount(0);
    await expect(recordField(page, 'title')).toHaveValue('Their edit');

    // Reloading adopts the server's version, so the next save goes through.
    await recordField(page, 'title').fill('Agreed');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect
      .poll(async () => (await apiGetRecord(page, key, record.uuid)).data.title)
      .toBe('Agreed');
  });

  // The "Overwrite anyway" branch of the same conflict (H1) lives in
  // `records-crud-conflict.spec.ts` — this file was already near the
  // 300-line cap.

  test('confirms a successful save on screen', async ({ page }) => {
    await login(page);
    const { key } = await seedSinkType(page);
    const record = await apiCreateRecord(page, key, { data: { title: 'Feedback' } });

    await page.goto(`/admin/records/${key}/${record.uuid}`);
    await recordField(page, 'title').fill('Feedback edited');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect
      .poll(async () => (await apiGetRecord(page, key, record.uuid)).data.title)
      .toBe('Feedback edited');

    // The editor calls `toast.success('Saved')` here — and `toast.error(...)`
    // for any failure that isn't a 409 or a 422, which is the only channel
    // those have. `exact` matters: a loose match also matches the
    // "Save"+"Delete" button row's combined text.
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();
  });

  test('deletes a record from the editor', async ({ page }) => {
    await login(page);
    const { key } = await seedSinkType(page);
    const record = await apiCreateRecord(page, key, { data: { title: 'Doomed' } });

    await page.goto(`/admin/records/${key}/${record.uuid}`);
    // U15: the action stays "Delete", the dialog it opens says what that
    // really does — its title and confirm button read "Move to Trash".
    await confirmDialog(page, page.getByRole('button', { name: 'Delete' }), 'Move to Trash');
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}$`));
    await expect(page.getByRole('link', { name: 'Doomed' })).toHaveCount(0);
  });

  test('a deleted record can be reached and restored from the UI', async ({ page }) => {
    await login(page);
    const { key } = await seedSinkType(page);
    const record = await apiCreateRecord(page, key, { data: { title: 'Recoverable' } });
    await page.request.delete(`/api/records/types/${key}/records/${record.uuid}`);

    // §8's soft delete is restorable, and `RecordActions`/`RecordEditor`
    // render a "Deleted" badge with Restore and Delete-permanently for
    // exactly that state — so the trashed record has to be reachable.
    await page.goto(`/admin/records/${key}/${record.uuid}`);
    await expect(page.getByText('Deleted')).toBeVisible();
    await confirmDialog(page, page.getByRole('button', { name: 'Restore' }), 'Restore');
    await expect(page.getByText('Deleted')).toHaveCount(0);
    expect((await apiGetRecord(page, key, record.uuid)).is_deleted).toBe(false);
  });
});
