import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateRecord,
  apiCreateType,
  fieldRow,
  saveType,
  uniqueTypeKey,
} from './records-helpers';

/**
 * The deferred schema preview — Phase 5 §1, F10.
 *
 * `POST /types/{key}/schema/preview` is synchronous up to
 * `RecordsSettings.preview_sync_limit` records and answers `202 {job}` above
 * it, which the editor polls. The setting defaults to **5,000**;
 * `tests/e2e/start-test-server.sh` lowers it to `SYNC_LIMIT` below through
 * `scripts/set_setting.py` — the module's settings live in the database, so
 * this is the only way a browser test can cross the line. The value stays
 * above `records-schema-change.spec.ts`'s fixtures (two records), so that
 * suite keeps exercising the synchronous path.
 *
 * What the operator must see either way is one thing: press the button, and
 * a report arrives. The deferred path adds a progress label in between,
 * which on a type this size is over before a poll can catch it — so the
 * label is asserted against one intercepted poll (frontend rendering) and
 * the real job is asserted end to end (server contract).
 */

/** Must match `start-test-server.sh`. */
const SYNC_LIMIT = 3;
const WITH_NOTE = 5;
const WITHOUT_NOTE = 4;
const TOTAL = WITH_NOTE + WITHOUT_NOTE;

/** A type over the sync limit, with `WITHOUT_NOTE` records that a `required`
 *  `note` would invalidate. */
async function seedType(page: Page): Promise<string> {
  const key = uniqueTypeKey('preview');
  await apiCreateType(page, {
    key,
    label: 'Previewed thing',
    label_plural: 'Previewed things',
    fields: [
      { key: 'title', type: 'text', label: 'Title', indexed: true },
      { key: 'note', type: 'text', label: 'Note' },
    ],
    display_field: 'title',
  });
  expect(TOTAL).toBeGreaterThan(SYNC_LIMIT);
  for (let i = 0; i < TOTAL; i += 1) {
    await apiCreateRecord(page, key, {
      data: {
        title: `record-${String(i).padStart(2, '0')}`,
        ...(i < WITH_NOTE ? { note: 'filled in' } : {}),
      },
    });
  }
  return key;
}

/** Open one field row's editing body. Rows collapse to a one-line summary
 *  (UX review R9), so anything inside the body has to be expanded first;
 *  a row added through `addFieldInEditor` opens by itself. */
async function expandField(page: Page, index: number): Promise<void> {
  const row = fieldRow(page, index);
  if ((await row.getAttribute('data-field-expanded')) === 'true') return;
  await row.getByTestId('records-field-toggle').click();
  await expect(row).toHaveAttribute('data-field-expanded', 'true');
}

/** Make `note` required — the restrictive change every test here previews. */
async function makeNoteRequired(page: Page): Promise<void> {
  await expandField(page, 1);
  await fieldRow(page, 1).getByRole('checkbox', { name: 'Required' }).click();
}

test.describe('Records — deferred schema preview', () => {
  test('a type over the sync limit previews through a job and shows the report', async ({
    page,
  }) => {
    await login(page);
    const key = await seedType(page);

    // The 202 is the thing that makes this the deferred path — captured from
    // the browser's own request rather than inferred from the record count.
    const statuses: number[] = [];
    page.on('response', (response) => {
      if (response.url().includes('/schema/preview')) statuses.push(response.status());
    });

    await page.goto(`/admin/records/types/${key}`);
    await makeNoteRequired(page);
    await page.getByRole('button', { name: 'Preview changes' }).click();

    const report = page.getByTestId('records-schema-preview');
    await expect(report).toBeVisible();
    await expect(
      report.getByText(`${TOTAL} records checked, ${WITHOUT_NOTE} would fail`),
    ).toBeVisible();
    // A sample of the failing records, by display title and field.
    await expect(report.getByText(`record-0${WITH_NOTE}`)).toBeVisible();
    await expect(report.getByText(/note: /)).toHaveCount(WITHOUT_NOTE);

    expect(statuses[0]).toBe(202);
    // The button is back to offering another preview, not stuck on "Checking…".
    await expect(page.getByRole('button', { name: 'Preview changes' })).toBeVisible();
  });

  test('while the job runs the button reads "Checked N of M"', async ({ page }) => {
    await login(page);
    const key = await seedType(page);

    // A scan of nine records finishes in milliseconds, so the first poll
    // already finds it done and the progress label never renders. One
    // intercepted poll — the shape the server really answers with while a
    // scan is running (`SchemaPreviewJobRead`) — is what makes the label
    // assertable; every later poll goes to the server untouched, so the
    // report that follows is the real one.
    let polls = 0;
    await page.route(/\/schema\/preview\/[0-9a-f]+$/, async (route) => {
      polls += 1;
      if (polls > 1) return route.fallback();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          job: 'intercepted',
          status: 'running',
          checked: WITH_NOTE,
          total: TOTAL,
          preview: null,
        }),
      });
    });

    await page.goto(`/admin/records/types/${key}`);
    await makeNoteRequired(page);
    await page.getByRole('button', { name: 'Preview changes' }).click();

    await expect(
      page.getByRole('button', { name: `Checked ${WITH_NOTE} of ${TOTAL}…` }),
    ).toBeVisible();
    // Then the real poll lands and the same button hands over the report.
    await expect(page.getByTestId('records-schema-preview')).toBeVisible();
    await expect(
      page.getByText(`${TOTAL} records checked, ${WITHOUT_NOTE} would fail`),
    ).toBeVisible();
    expect(polls).toBeGreaterThan(1);
  });

  test('saving after a deferred preview is refused with the same report', async ({ page }) => {
    await login(page);
    const key = await seedType(page);

    await page.goto(`/admin/records/types/${key}`);
    await makeNoteRequired(page);
    await page.getByRole('button', { name: 'Preview changes' }).click();
    await expect(page.getByTestId('records-schema-preview')).toBeVisible();

    // `apply` may reuse the finished job's report instead of re-scanning
    // (F10: same type, same proposed fields, same `version`). Reuse is not
    // visible from here — what is, is that the refusal says the same thing
    // the preview did, which is the whole point of reusing it.
    await saveType(page);
    const refusal = page.getByTestId('records-schema-report');
    await expect(refusal).toBeVisible();
    await expect(refusal.getByText('This change would leave records invalid')).toBeVisible();
    await expect(
      refusal.getByText(`${TOTAL} records checked, ${WITHOUT_NOTE} would fail`),
    ).toBeVisible();
    await expect(
      refusal.getByRole('button', {
        name: `Apply anyway — ${WITHOUT_NOTE} records will be marked invalid`,
      }),
    ).toBeVisible();

    // Nothing was written: the type still has an optional `note`.
    const current = await page.request.get(`/api/records/types/${key}`);
    const fields = (await current.json()).fields as { key: string; required: boolean }[];
    expect(fields.find((f) => f.key === 'note')?.required).toBe(false);
  });

  test("a pruned preview job shows the module's own copy and a retry action", async ({ page }) => {
    await login(page);
    const key = await seedType(page);

    // The registry is in-process (`services/preview_jobs.py`): a 404 means a
    // worker restart, a multi-worker host, or the TTL pruned the job — not a
    // real failure of the scan (UX-4).
    let polls = 0;
    const pollUrl = /\/schema\/preview\/[0-9a-f]+$/;
    await page.route(pollUrl, async (route) => {
      polls += 1;
      await route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: `no schema preview job 'x' for '${key}'` }),
      });
    });

    await page.goto(`/admin/records/types/${key}`);
    await makeNoteRequired(page);
    await page.getByRole('button', { name: 'Preview changes' }).click();

    const expired = page.getByTestId('records-preview-expired');
    await expect(expired).toBeVisible();
    await expect(expired).toContainText('The preview expired; preview again.');
    // Not the server's own sentence.
    await expect(expired).not.toContainText('no schema preview job');
    expect(polls).toBeGreaterThan(0);

    // The real job, once retried, is not intercepted and shows the report.
    await page.unroute(pollUrl);
    await page.getByTestId('records-preview-expired-retry').click();
    await expect(page.getByTestId('records-schema-preview')).toBeVisible();
  });
});
