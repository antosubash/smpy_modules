import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import {
  addFieldInEditor,
  apiCreateRecord,
  apiCreateType,
  apiGetRecord,
  apiGetType,
  apiListRecords,
  expandField,
  expectTypeSaved,
  fieldRow,
  saveType,
  uniqueTypeKey,
} from './records-helpers';

/**
 * Changing a schema that already holds records — design §8.
 *
 * The four classifications, the dry run that has to run before a restrictive
 * change is allowed to land, the `force` escape hatch that marks records
 * instead of rewriting them, the `_orphaned` decision a re-added key forces
 * (§8.8), and the reindex window an `indexed` toggle opens (§8.5).
 */

async function seedPopulatedType(page: Page, prefix: string): Promise<string> {
  const key = uniqueTypeKey(prefix);
  await apiCreateType(page, {
    key,
    label: 'Populated',
    label_plural: 'Populated things',
    fields: [
      { key: 'title', type: 'text', label: 'Title', indexed: true },
      { key: 'note', type: 'text', label: 'Note' },
    ],
    display_field: 'title',
  });
  await apiCreateRecord(page, key, { data: { title: 'One', note: 'first' } });
  await apiCreateRecord(page, key, { data: { title: 'Two', note: 'second' } });
  return key;
}

test.describe('Records — schema change', () => {
  test('previews a restrictive change with the records it would break', async ({ page }) => {
    await login(page);
    const key = await seedPopulatedType(page, 'prev');
    await page.goto(`/admin/records/types/${key}`);
    await expect(page.getByRole('heading', { name: 'Populated' })).toBeVisible();

    // "Preview changes" is only meaningful once the draft has moved.
    await expect(page.getByRole('button', { name: 'Preview changes' })).toBeDisabled();
    await addFieldInEditor(page, 2, {
      key: 'rank',
      type: 'integer',
      label: 'Rank',
      required: true,
    });
    await page.getByRole('button', { name: 'Preview changes' }).click();

    const preview = page.getByTestId('records-schema-preview');
    await expect(preview).toBeVisible();
    await expect(preview).toContainText('Restrictive');
    await expect(preview).toContainText('Field added');
    // The dry run names a failing record and the field that fails on it.
    await expect(preview).toContainText('One');
    await expect(preview).toContainText('rank');

    // A preview writes nothing (§8.9).
    const stored = await apiGetType(page, key);
    expect(stored.fields.map((f) => f.key)).toEqual(['title', 'note']);
  });

  test('refuses a restrictive save, then marks records on "apply anyway"', async ({ page }) => {
    await login(page);
    const key = await seedPopulatedType(page, 'force');
    await page.goto(`/admin/records/types/${key}`);
    await expect(page.getByRole('heading', { name: 'Populated' })).toBeVisible();

    await addFieldInEditor(page, 2, {
      key: 'rank',
      type: 'integer',
      label: 'Rank',
      required: true,
    });
    await saveType(page);

    const report = page.getByTestId('records-schema-report');
    await expect(report).toBeVisible();
    await expect(report).toContainText('This change would leave records invalid');
    await expect(report).toContainText('rank');
    // Refused, not applied.
    expect((await apiGetType(page, key)).fields.map((f) => f.key)).toEqual(['title', 'note']);

    await report.getByRole('button', { name: /Apply anyway/ }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Apply anyway' }).click();
    await expectTypeSaved(page);

    const after = await apiGetType(page, key);
    expect(after.fields.map((f) => f.key)).toEqual(['title', 'note', 'rank']);

    // §8.3: marked, not hidden — and the editor says so on the record.
    const { items } = await apiListRecords(page, key);
    const first = items[0];
    expect((await apiGetRecord(page, key, first.uuid)).invalid.length).toBeGreaterThan(0);

    await page.goto(`/admin/records/${key}/${first.uuid}`);
    const notice = page.getByTestId('records-invalid-notice');
    await expect(notice).toBeVisible();
    await expect(notice).toContainText('does not satisfy the current schema');
    await expect(notice).toContainText('rank');
  });

  test('removing a field, then re-adding its key, forces a restore-or-discard', async ({
    page,
  }) => {
    await login(page);
    const key = await seedPopulatedType(page, 'orph');
    await page.goto(`/admin/records/types/${key}`);
    await expect(page.getByRole('heading', { name: 'Populated' })).toBeVisible();

    // Destructive: `note` goes, its values stay in storage (§8.2).
    await fieldRow(page, 1).getByRole('button', { name: 'Remove field' }).click();
    await saveType(page);
    await expectTypeSaved(page);
    expect((await apiGetType(page, key)).fields.map((f) => f.key)).toEqual(['title']);

    await page.reload();
    await addFieldInEditor(page, 1, { key: 'note', type: 'text', label: 'Note again' });
    await saveType(page);

    const conflicts = page.getByTestId('records-orphaned-conflicts');
    await expect(conflicts).toBeVisible();
    await expect(conflicts).toContainText('These fields still hold values from a previous delete');
    await expect(conflicts).toContainText('note');

    await conflicts.getByRole('button', { name: 'Restore', exact: true }).click();
    await expectTypeSaved(page);

    const { items } = await apiListRecords(page, key);
    expect(items.map((i) => i.data.note).sort()).toEqual(['first', 'second']);
  });

  test('discarding drops the orphaned values for good', async ({ page }) => {
    await login(page);
    const key = await seedPopulatedType(page, 'disc');
    await page.goto(`/admin/records/types/${key}`);
    await expect(page.getByRole('heading', { name: 'Populated' })).toBeVisible();

    await fieldRow(page, 1).getByRole('button', { name: 'Remove field' }).click();
    await saveType(page);
    await expectTypeSaved(page);

    await page.reload();
    await addFieldInEditor(page, 1, { key: 'note', type: 'text', label: 'Note again' });
    await saveType(page);

    const conflicts = page.getByTestId('records-orphaned-conflicts');
    await expect(conflicts).toBeVisible();
    await conflicts.getByRole('button', { name: 'Discard' }).click();
    await expectTypeSaved(page);

    const { items } = await apiListRecords(page, key);
    // Discarded: the key reads back empty rather than carrying the old value.
    for (const item of items) expect(item.data.note ?? null).toBeNull();
  });

  test('turning on indexing shows the reindex banner until the rebuild clears', async ({
    page,
  }) => {
    await login(page);
    const key = await seedPopulatedType(page, 'reidx');
    await page.goto(`/admin/records/types/${key}`);
    await expect(page.getByRole('heading', { name: 'Populated' })).toBeVisible();

    // `note` holds values and is not indexed — turning indexing on is the
    // index-affecting change of §8.5, which opens the reindex window.
    await expandField(page, 1);
    await fieldRow(page, 1).getByRole('checkbox', { name: 'Indexed' }).click();
    await saveType(page);
    await expectTypeSaved(page);

    const banner = page.getByTestId('records-reindex-status');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('Rebuilding the index for:');
    await expect(banner).toContainText('note');

    // The banner polls `router.reload({ only: ['type'] })` every ~5s and
    // disappears the moment `reindex_pending` empties.
    await expect(banner).toHaveCount(0, { timeout: 20_000 });
    expect(await apiGetType(page, key).then((t) => t.reindex_pending)).toEqual({});

    // …and the field is filterable once the rebuild is done.
    await page.goto(`/admin/records/${key}?filter=note:eq:first`);
    await expect(page.getByTestId('records-filter-error')).toHaveCount(0);
    await expect(page.getByTestId('records-record-row')).toHaveCount(1);
  });

  test('refuses a filter on a field whose reindex has not finished', async ({ page }) => {
    await login(page);
    const key = await seedPopulatedType(page, 'window');
    // Straight to the API so the assertion lands inside the window §8.5
    // describes rather than racing the background task through the UI.
    const type = await apiGetType(page, key);
    await page.request.put(`/api/records/types/${key}`, {
      headers: { 'content-type': 'application/json' },
      data: {
        expected_version: type.version,
        fields: [
          { key: 'title', type: 'text', label: 'Title', indexed: true },
          { key: 'note', type: 'text', label: 'Note', indexed: true },
        ],
      },
    });

    await page.goto(`/admin/records/${key}?filter=note:eq:first`);
    // Wait for the page itself before reading either branch — a count taken
    // before hydration is always zero and would silently pick one.
    await expect(page.getByRole('heading', { name: 'Populated things' })).toBeVisible();
    // Either the rebuild already finished (a clean list) or it has not, in
    // which case the refusal has to be explained rather than silently
    // rendering as "no matching records".
    const notice = page.getByTestId('records-filter-error');
    if (await notice.count()) {
      await expect(notice).toContainText('being reindexed right now');
    } else {
      await expect(page.getByTestId('records-record-row')).toHaveCount(1);
    }
  });

  test('deleting a type asks for its exact record count', async ({ page }) => {
    await login(page);
    const key = await seedPopulatedType(page, 'del');
    await page.goto(`/admin/records/types/${key}`);
    await expect(page.getByRole('heading', { name: 'Populated' })).toBeVisible();

    await page.getByRole('button', { name: 'Delete this type' }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();

    // A wrong count is refused in the dialog, which stays open. The guard
    // now disarms the button itself instead of waiting for the click to
    // fail (`DeleteTypeSection`, confirmDisabled), so the refusal is the
    // disabled button plus the inline mismatch message.
    const confirm = dialog.getByRole('button', { name: 'Delete', exact: true });
    await expect(confirm).toBeDisabled();
    await dialog.locator('#type-editor-delete-confirm').fill('1');
    await expect(dialog.getByText(/That doesn.t match/)).toBeVisible();
    await expect(confirm).toBeDisabled();
    await expect(dialog).toBeVisible();

    await dialog.locator('#type-editor-delete-confirm').fill('2');
    await expect(dialog.getByText(/That doesn.t match/)).toHaveCount(0);
    await expect(confirm).toBeEnabled();
    await confirm.click();
    await expect(page).toHaveURL(/\/admin\/records\/?$/);
    await expect(
      page.locator(`[data-testid="records-type-row"][data-type-key="${key}"]`),
    ).toHaveCount(0);
  });
});
