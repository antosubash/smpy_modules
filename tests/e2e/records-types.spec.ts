import { expect, test } from '@playwright/test';

import { login } from './helpers';
import {
  addFieldInEditor,
  apiCreateRecord,
  apiCreateType,
  apiDeleteType,
  apiGetType,
  apiListTypes,
  fieldRow,
  saveType,
  uniqueTypeKey,
} from './records-helpers';

/**
 * The Record Types list and the schema editor (design §12's `Types.tsx` and
 * `TypeEditor.tsx`): building a type out of every field kind the editor
 * offers, the immutable-key rules it enforces inline, and what the list says
 * about a populated type.
 */
test.describe('Records — types', () => {
  test('builds a type with one field of every kind the editor offers', async ({ page }) => {
    test.setTimeout(180_000);
    await login(page);

    // `relation` needs something to point at, and the editor only offers
    // types that already exist — so the target is seeded first.
    const targetKey = uniqueTypeKey('tgt');
    await apiCreateType(page, {
      key: targetKey,
      label: `Target ${targetKey}`,
      fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
      display_field: 'name',
    });

    const key = uniqueTypeKey('kinds');
    await page.goto('/admin/records/types/new');
    await expect(page.getByRole('heading', { name: 'New type' })).toBeVisible();

    await page.locator('#type-editor-key').fill(key);
    await page.locator('#type-editor-label').fill('Kitchen sink');
    await page.locator('#type-editor-label-plural').fill('Kitchen sinks');
    await page.locator('#type-editor-description').fill('One field of every kind.');

    const specs = [
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
        choices: [
          { value: 'red', label: 'Red' },
          { value: 'green', label: 'Green' },
        ],
      },
      {
        key: 'tags',
        type: 'multiselect',
        label: 'Tags',
        choices: [
          { value: 'a', label: 'Alpha' },
          { value: 'b', label: 'Beta' },
        ],
      },
      { key: 'contact', type: 'email', label: 'Contact', unique: true },
      { key: 'link', type: 'url', label: 'Link' },
      { key: 'meta', type: 'json', label: 'Meta' },
      { key: 'owner', type: 'relation', label: 'Owner', targetType: targetKey },
    ];

    for (const [index, spec] of specs.entries()) {
      await addFieldInEditor(page, index, spec);
    }

    // `unique` implies `indexed` — the editor normalises rather than letting
    // the save bounce (rules.ts::normaliseOnToggle mirroring `_validate_flags`).
    await expect(fieldRow(page, 9).getByRole('checkbox', { name: 'Indexed' })).toBeChecked();
    // `longtext` and `json` have no index table, so the box is unavailable.
    await expect(fieldRow(page, 1).getByRole('checkbox', { name: 'Indexed' })).toBeDisabled();
    await expect(fieldRow(page, 11).getByRole('checkbox', { name: 'Indexed' })).toBeDisabled();

    await page.locator('#type-editor-display-field').selectOption('title');
    await page.locator('#type-editor-slug-field').selectOption('title');

    await saveType(page);
    await expect(page).toHaveURL(new RegExp(`/admin/records/types/${key}$`));
    await expect(page.getByRole('heading', { name: 'Kitchen sink' })).toBeVisible();

    const stored = await apiGetType(page, key);
    expect(stored.fields.map((f) => `${f.key}:${f.type}`)).toEqual(
      specs.map((s) => `${s.key}:${s.type}`),
    );
    expect(stored.display_field).toBe('title');
    expect(stored.slug_field).toBe('title');
    expect(stored.fields.find((f) => f.key === 'title')?.required).toBe(true);
    expect(stored.fields.find((f) => f.key === 'contact')?.unique).toBe(true);
    expect(stored.fields.find((f) => f.key === 'contact')?.indexed).toBe(true);
    expect(stored.fields.find((f) => f.key === 'colour')?.options.choices).toEqual([
      { value: 'red', label: 'Red' },
      { value: 'green', label: 'Green' },
    ]);
    expect(stored.fields.find((f) => f.key === 'owner')?.options.target_type).toBe(targetKey);
  });

  test('refuses a reserved, malformed or duplicate field key inline', async ({ page }) => {
    await login(page);
    await page.goto('/admin/records/types/new');
    await expect(page.getByRole('heading', { name: 'New type' })).toBeVisible();

    const row = await addFieldInEditor(page, 0, { key: 'ok_key', type: 'text', label: 'Ok' });
    const keyInput = row.getByLabel('Key', { exact: true });

    await keyInput.fill('_orphaned');
    await expect(
      row.getByText(
        '"_orphaned" is reserved by the module: it names a column every record already has.',
      ),
    ).toBeVisible();

    // The message names whichever reserved key was actually typed, not a
    // fixed example (M2) — `status` is also in `RESERVED_FIELD_KEYS`.
    await keyInput.fill('status');
    await expect(
      row.getByText(
        '"status" is reserved by the module: it names a column every record already has.',
      ),
    ).toBeVisible();

    await keyInput.fill('Bad-Key');
    await expect(row.getByText(/Must start with a lowercase letter/)).toBeVisible();

    await keyInput.fill('ok_key');
    await expect(row.getByText(/reserved|lowercase letter/)).toHaveCount(0);

    const second = await addFieldInEditor(page, 1, { key: 'ok_key', type: 'text', label: 'Dup' });
    await expect(second.getByText('Another field already uses this key.')).toBeVisible();
  });

  test('the types list shows each type with its live and trashed counts', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('counts');
    await apiCreateType(page, {
      key,
      label: `Counted ${key}`,
      label_plural: `Counted ${key} items`,
      fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
      display_field: 'name',
    });
    const keep = await apiCreateRecord(page, key, { data: { name: 'Keeper' } });
    const bin = await apiCreateRecord(page, key, { data: { name: 'Binned' } });
    await page.request.delete(`/api/records/types/${key}/records/${bin.uuid}`);

    await page.goto('/admin/records/');
    const row = page.locator(`[data-testid="records-type-row"][data-type-key="${key}"]`);
    await expect(row).toContainText(`Counted ${key}`);
    await expect(row).toContainText(key);

    // Both links on the row go where the list promises.
    await row.getByRole('link', { name: 'View records' }).click();
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}$`));
    await expect(page.getByRole('heading', { name: `Counted ${key} items` })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Keeper' })).toBeVisible();
    expect(keep.display_title).toBe('Keeper');
  });

  test('the types list counts a type’s live and trashed records', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('tally');
    await apiCreateType(page, {
      key,
      label: `Tally ${key}`,
      fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
      display_field: 'name',
    });
    await apiCreateRecord(page, key, { data: { name: 'Keeper' } });
    const bin = await apiCreateRecord(page, key, { data: { name: 'Binned' } });
    await page.request.delete(`/api/records/types/${key}/records/${bin.uuid}`);

    await page.goto('/admin/records/');
    const row = page.locator(`[data-testid="records-type-row"][data-type-key="${key}"]`);
    await expect(row).toContainText('1 record');
    await expect(row).toContainText('(1 trashed)');
  });

  test('shows the empty state when no types exist', async ({ page }) => {
    await login(page);
    // Deliberately destructive, and deliberately last: the e2e database is
    // disposable and every other spec creates the type it needs inside its
    // own test, so nothing that ran before this needs its types afterwards.
    // Relation targets can only be dropped once their referrers are gone,
    // hence the repeated passes rather than one sweep.
    for (let pass = 0; pass < 4; pass += 1) {
      const { items } = await apiListTypes(page);
      if (items.length === 0) break;
      for (const type of items) {
        try {
          await apiDeleteType(page, type.key, type.record_count + type.trashed_record_count);
        } catch {
          // A `restrict` relation still points here — the next pass gets it.
        }
      }
    }

    await page.goto('/admin/records/');
    await expect(page.getByRole('heading', { name: 'Record Types' })).toBeVisible();
    await expect(page.getByText('No record types yet')).toBeVisible();
    await expect(page.getByTestId('records-type-row')).toHaveCount(0);
  });
});
