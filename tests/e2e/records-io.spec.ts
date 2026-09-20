import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateRecord,
  apiCreateTranslation,
  apiCreateType,
  applyFilter,
  rowTitles,
  uniqueTypeKey,
} from './records-helpers';

/**
 * Import and export **through the record-list toolbar** (Phase 5 §2).
 *
 * The service code is covered by the module's own suites; what earns a
 * browser test is the toolbar's contract with an operator: an export link
 * that really downloads a file the browser saves, an import that is a dry
 * run before it is a write, and a refusal that is readable on screen rather
 * than only in a 422 body.
 *
 * Files go in through `setInputFiles` with an in-memory buffer — the input
 * is the hidden one `RecordIoMenu` clicks for you, so this is the same code
 * path a file dialog takes without a temp file on disk.
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

test.describe('Records — import / export from the list toolbar', () => {
  test('the export menu downloads JSON and CSV with the right content type and rows', async ({
    page,
  }) => {
    await login(page);
    const key = await seedType(page, 'export');
    await apiCreateRecord(page, key, {
      data: { title: 'First export', note: 'one' },
      status: 'published',
    });
    await apiCreateRecord(page, key, { data: { title: 'Second export', note: 'two' } });

    await page.goto(`/admin/records/${key}`);
    await page.getByTestId('records-export-menu').click();
    const jsonLink = page.getByTestId('records-export-json');
    await expect(jsonLink).toBeVisible();
    const jsonHref = await jsonLink.getAttribute('href');
    expect(jsonHref).toContain(`/api/records/types/${key}/records/export`);
    expect(jsonHref).toContain('format=json');

    // The link really is a download: Chromium fires `download` because the
    // response carries `Content-Disposition: attachment`, and the file is
    // named after the type and the day (`export_filename`).
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      jsonLink.click({ noWaitAfter: true }),
    ]);
    expect(download.suggestedFilename()).toMatch(
      new RegExp(`^${key}-\\d{4}-\\d{2}-\\d{2}\\.json$`),
    );

    // The headers and the body, over the same session the browser used.
    const json = await page.request.get(jsonHref ?? '');
    expect(json.status()).toBe(200);
    expect(json.headers()['content-type']).toContain('application/json');
    expect(json.headers()['content-disposition']).toContain('attachment');
    const body = (await json.json()) as {
      type: { key: string; fields: unknown[] };
      records: { uuid: string; status: string; locale: string; data: Record<string, unknown> }[];
    };
    expect(body.type.key).toBe(key);
    expect(body.records).toHaveLength(2);
    expect(body.records.map((r) => r.data.title).sort()).toEqual(['First export', 'Second export']);
    // The lenient read: `note` is filled for both, and every row carries the
    // §5 envelope the importer matches on.
    expect(body.records[0]).toHaveProperty('uuid');
    expect(body.records[0]).toHaveProperty('locale', 'en');

    await page.getByTestId('records-export-menu').click();
    const csvLink = page.getByTestId('records-export-csv');
    const csvHref = (await csvLink.getAttribute('href')) ?? '';
    expect(csvHref).toContain('format=csv');
    const csv = await page.request.get(csvHref);
    expect(csv.headers()['content-type']).toContain('text/csv');
    const lines = (await csv.text()).trim().split('\r\n');
    expect(lines[0]).toBe(
      'uuid,slug,locale,translation_group,status,position,published_at,title,note',
    );
    expect(lines).toHaveLength(3);
    expect(lines.slice(1).join('\n')).toContain('First export');
  });

  test('"Export" exports what the screen is showing — the filter travels with it', async ({
    page,
  }) => {
    await login(page);
    const key = await seedType(page, 'expfilter');
    await apiCreateRecord(page, key, { data: { title: 'Keep me' } });
    await apiCreateRecord(page, key, { data: { title: 'Drop me' } });

    await page.goto(`/admin/records/${key}`);
    await applyFilter(page, 'title', 'eq', 'Keep me');
    await expect.poll(() => rowTitles(page)).toEqual(['Keep me']);

    await page.getByTestId('records-export-menu').click();
    const href = (await page.getByTestId('records-export-json').getAttribute('href')) ?? '';
    expect(href).toContain('filter=title%3Aeq%3AKeep+me');
    const exported = await page.request.get(href);
    const body = (await exported.json()) as { records: { data: { title: string } }[] };
    expect(body.records.map((r) => r.data.title)).toEqual(['Keep me']);
  });

  test('an import is a dry run first, and "Apply import" writes and refreshes the list', async ({
    page,
  }) => {
    await login(page);
    const key = await seedType(page, 'import');

    await page.goto(`/admin/records/${key}`);
    const dialog = await importFile(
      page,
      jsonFile([{ data: { title: 'Imported one' } }, { data: { title: 'Imported two' } }]),
    );

    await expect(dialog.getByText('Import preview')).toBeVisible();
    await expect(page.getByTestId('records-import-counts')).toHaveText(
      '2 row(s): 2 to create, 0 to update, 0 unchanged, 0 failed',
    );
    // A dry run writes nothing — asserted against the API rather than the
    // screen, since the list behind the dialog was rendered before the
    // import and would look the same either way.
    const beforeApply = await page.request.get(`/api/records/types/${key}/records`);
    expect((await beforeApply.json()).total).toBe(0);

    await page.getByTestId('records-import-apply').click();
    await expect(dialog.getByText('Import result')).toBeVisible();
    // Past tense once it has actually happened (UX-10) — the preview above
    // used "to create"/"to update", this one does not.
    await expect(page.getByTestId('records-import-counts')).toHaveText(
      '2 row(s): 2 created, 0 updated, 0 unchanged, 0 failed',
    );
    await expect(page.getByTestId('records-import-apply')).toHaveCount(0);

    // The list refreshes itself once the apply lands (UX-1) — no manual
    // reload needed to see the rows just imported, same as a delete/restore.
    await expect
      .poll(() => rowTitles(page))
      .toEqual(expect.arrayContaining(['Imported one', 'Imported two']));

    // `.first()`: Radix's own corner dismiss button is also named "Close".
    await dialog.getByRole('button', { name: 'Close' }).first().click();
  });

  // The import-options popover (`force`/`mode`/`on_error`/`match_by`) and
  // what the export menu says about a trash export are covered in
  // `records-io-options.spec.ts`, split out for the 300-line cap.

  for (const format of ['json', 'csv'] as const) {
    test(`re-importing a ${format.toUpperCase()} export reports every row unchanged`, async ({
      page,
    }) => {
      await login(page);
      const key = await seedType(page, `round${format}`);
      const first = await apiCreateRecord(page, key, { data: { title: 'Round trip' } });

      await page.goto(`/admin/records/${key}`);
      const exported = await page.request.get(
        `/api/records/types/${key}/records/export?format=${format}`,
      );
      await page.getByTestId('records-import-input').setInputFiles({
        name: `roundtrip.${format}`,
        mimeType: format === 'json' ? 'application/json' : 'text/csv',
        buffer: Buffer.from(await exported.text()),
      });

      await expect(page.getByTestId('records-import-report')).toBeVisible();
      await expect(page.getByTestId('records-import-counts')).toHaveText(
        '1 row(s): 0 to create, 0 to update, 1 unchanged, 0 failed',
      );

      // Nothing moved: `skipped` is what keeps a re-import from bumping every
      // record's version (README § Import and export).
      const after = await page.request.get(`/api/records/types/${key}/records/${first.uuid}`);
      expect((await after.json()).version).toBe(first.version);
    });
  }

  test('a file with a bad row lists the row errors and offers no "Apply import"', async ({
    page,
  }) => {
    await login(page);
    const key = uniqueTypeKey('badfile');
    await apiCreateType(page, {
      key,
      label: 'Strict thing',
      fields: [{ key: 'title', type: 'text', label: 'Title', required: true, indexed: true }],
      display_field: 'title',
    });

    await page.goto(`/admin/records/${key}`);
    const dialog = await importFile(page, jsonFile([{ data: { title: 'Fine' } }, { data: {} }]));

    await expect(page.getByTestId('records-import-counts')).toHaveText(
      '2 row(s): 1 to create, 0 to update, 0 unchanged, 1 failed',
    );
    await expect(dialog.getByText(/^Row 2 \(title\):/)).toBeVisible();
    // A run with a failing row cannot be applied from here at all — the
    // button is absent, not merely disabled (`RecordIoMenu`).
    await expect(page.getByTestId('records-import-apply')).toHaveCount(0);
  });

  test('an import that would move a record between languages is refused inline', async ({
    page,
  }) => {
    await login(page);
    const key = await seedType(page, 'iolocale', { translatable: true });
    const en = await apiCreateRecord(page, key, { data: { title: 'English row' } });
    await apiCreateTranslation(page, key, en.uuid, { locale: 'de' });

    await page.goto(`/admin/records/${key}`);
    const dialog = await importFile(
      page,
      jsonFile([{ uuid: en.uuid, locale: 'de', data: { title: 'English row' } }]),
    );

    await expect(page.getByTestId('records-import-counts')).toHaveText(
      '1 row(s): 0 to create, 0 to update, 0 unchanged, 1 failed',
    );
    await expect(dialog.getByText(/locale is fixed for its lifetime/)).toBeVisible();
    await expect(dialog.getByText(/create a translation instead/)).toBeVisible();
    await expect(page.getByTestId('records-import-apply')).toHaveCount(0);
  });
});
