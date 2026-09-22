import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import { apiCreateRecord, apiCreateType, uniqueTypeKey } from './records-helpers';

/**
 * The import options `RecordIoMenu` exposes beyond the file itself — FAIL-1's
 * UI half — plus what the export menu says about a trash export (UX-11).
 *
 * Split out of `records-io.spec.ts` for the 300-line cap: these two tests are
 * long because they exercise the whole "export, edit, re-import" workflow
 * FAIL-1 is about, not because they belong to a different feature.
 */

type Row = { uuid?: string; locale?: string; data: Record<string, unknown> };

function jsonFile(rows: Row[]) {
  return {
    name: 'records.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({ records: rows })),
  };
}

/** A type with one indexed text field, its display field. */
async function seedType(page: Page, prefix: string, extra: Record<string, unknown> = {}) {
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
async function importFile(page: Page, file: ReturnType<typeof jsonFile>) {
  await page.getByTestId('records-import-input').setInputFiles(file);
  const dialog = page.getByTestId('records-import-report');
  await expect(dialog).toBeVisible();
  return dialog;
}

test.describe('Records — import options and trash export', () => {
  test('editing an exported record and re-importing predicts the refusal, and "force" gets it through', async ({
    page,
  }) => {
    await login(page);
    const key = await seedType(page, 'force');
    const record = await apiCreateRecord(page, key, { data: { title: 'Original', note: 'x' } });

    await page.goto(`/admin/records/${key}`);
    const exported = await page.request.get(`/api/records/types/${key}/records/export?format=json`);
    const body = (await exported.json()) as {
      records: { uuid: string; locale: string; data: Record<string, unknown> }[];
    };
    body.records[0].data.title = 'Edited';
    const editedFile = {
      name: 'edited.json',
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify(body)),
    };

    // The dry run now predicts the same refusal the apply would hit
    // (FAIL-1's backend half): the export carries no `version`, so the file
    // cannot say which version it is changing.
    const dialog = await importFile(page, editedFile);
    await expect(page.getByTestId('records-import-counts')).toHaveText(
      '1 row: 0 to create, 0 to update, 0 unchanged, 1 failed',
    );
    await expect(dialog.getByText(/^Row 1 \(version\):/)).toBeVisible();
    await expect(dialog.getByText(/carries no 'version'/)).toBeVisible();
    // And the menu points at the one option that gets past it — which,
    // before this fix, `RecordIoMenu` did not expose at all.
    await expect(page.getByTestId('records-import-force-hint')).toBeVisible();
    // Apply stays on screen and disarmed, naming the rows that failed, so
    // the reason it cannot be pressed is readable instead of the button
    // simply being gone (`RecordIoMenu`, `importApplyBlockedReason`).
    const apply = page.getByTestId('records-import-apply');
    await expect(apply).toBeVisible();
    await expect(apply).toBeDisabled();
    await expect(page.getByTestId('records-import-blocked')).toContainText(
      "1 of 1 row can't be imported, so nothing will be written.",
    );
    const before = await page.request.get(`/api/records/types/${key}/records/${record.uuid}`);
    expect((await before.json()).data.title).toBe('Original');

    // R21: the options trigger now lives inside this same dialog, above
    // Apply, instead of a toolbar popover that had already closed by the
    // time the preview needed it. Turning "force" on from here re-checks
    // the same file automatically — no need to close the dialog and pick it
    // again to see the effect.
    await dialog.getByTestId('records-import-options-trigger').click();
    await page.getByTestId('records-import-force').click();
    await page.keyboard.press('Escape');

    await expect(page.getByTestId('records-import-counts')).toHaveText(
      '1 row: 0 to create, 1 to update, 0 unchanged, 0 failed',
    );
    await expect(page.getByTestId('records-import-file-summary')).toContainText(
      'overwrite unversioned rows: on',
    );
    await page.getByTestId('records-import-apply').click();
    await expect(page.getByTestId('records-import-counts')).toHaveText(
      '1 row: 0 created, 1 updated, 0 unchanged, 0 failed',
    );
    // The options trigger is only offered before a write — the run it
    // configured has now happened.
    await expect(page.getByTestId('records-import-options-trigger')).toHaveCount(0);

    const after = await page.request.get(`/api/records/types/${key}/records/${record.uuid}`);
    expect((await after.json()).data.title).toBe('Edited');
  });

  test('the export menu notes that a trash export cannot be re-imported', async ({ page }) => {
    await login(page);
    const key = await seedType(page, 'trashnote');
    const record = await apiCreateRecord(page, key, { data: { title: 'Binned' } });
    await page.request.delete(`/api/records/types/${key}/records/${record.uuid}`);

    await page.goto(`/admin/records/${key}`);
    await page.getByTestId('records-trash-toggle').click();
    await page.getByTestId('records-export-menu').click();
    await expect(page.getByTestId('records-export-trash-note')).toContainText(
      "can't be re-imported",
    );
    await page.keyboard.press('Escape');

    // Off the trash view, the export menu says nothing of the sort.
    await page.getByTestId('records-trash-toggle').click();
    await page.getByTestId('records-export-menu').click();
    await expect(page.getByTestId('records-export-trash-note')).toHaveCount(0);
  });
});
