import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateRecord,
  apiCreateType,
  apiGetRecord,
  type Json,
  type RecordRead,
  uniqueTypeKey,
} from './records-helpers';

/**
 * Phase 4's forward/reverse relation surfaces: `?expand=` rendered in the
 * list and editor (design §9), the "Referenced by" panel, and the
 * referrer-aware delete dialog.
 */

async function apiDeleteRecord(page: Page, key: string, uuid: string): Promise<void> {
  const res = await page.request.delete(`/api/records/types/${key}/records/${uuid}`);
  if (!res.ok()) throw new Error(`delete ${key}/${uuid} → ${res.status()}: ${await res.text()}`);
}

async function apiRestoreRecord(page: Page, key: string, uuid: string): Promise<RecordRead> {
  const res = await page.request.post(`/api/records/types/${key}/records/${uuid}/restore`);
  if (!res.ok()) throw new Error(`restore ${key}/${uuid} → ${res.status()}: ${await res.text()}`);
  return res.json();
}

/** An `author` type and a `book` type pointing at it — this suite's own copy
 *  of `tests/relation_helpers.py::library`, over the admin JSON API. */
async function makeLibrary(
  page: Page,
  onDelete: 'restrict' | 'set_null' | 'cascade' = 'restrict',
): Promise<{ authorKey: string; bookKey: string }> {
  const authorKey = uniqueTypeKey('author');
  const bookKey = uniqueTypeKey('book');
  await apiCreateType(page, {
    key: authorKey,
    label: 'Author',
    fields: [{ key: 'name', type: 'text', label: 'Name', indexed: true }],
    display_field: 'name',
  });
  await apiCreateType(page, {
    key: bookKey,
    label: 'Book',
    fields: [
      { key: 'name', type: 'text', label: 'Name', indexed: true },
      {
        key: 'written_by',
        type: 'relation',
        label: 'Written By',
        options: { target_type: authorKey, on_delete: onDelete },
      },
    ],
    display_field: 'name',
  });
  return { authorKey, bookKey };
}

function relationCell(page: Page, uuid: string) {
  return page.locator(`[data-record-uuid="${uuid}"]`);
}

test.describe('Records — relations', () => {
  test("the list and the editor show the target's title, not a uuid", async ({ page }) => {
    await login(page);
    const { authorKey, bookKey } = await makeLibrary(page);
    const author = await apiCreateRecord(page, authorKey, { data: { name: 'Herbert' } });
    const book = await apiCreateRecord(page, bookKey, {
      data: { name: 'Dune', written_by: { type: authorKey, uuid: author.uuid } },
    });

    await page.goto(`/admin/records/${bookKey}`);
    const cell = relationCell(page, book.uuid).getByTestId('records-relation-link');
    await expect(cell).toHaveText('Herbert');
    await expect(cell).toHaveAttribute('href', `/admin/records/${authorKey}/${author.uuid}`);

    // The editor's own `RelationPicker`, loaded fresh from the server —
    // not the "just picked it" path `records-crud.spec.ts` already covers.
    await page.goto(`/admin/records/${bookKey}/${book.uuid}`);
    const picker = page.getByTestId('records-relation-written_by');
    await expect(picker.getByText('Herbert')).toBeVisible();
  });

  test('trashing the target (via a restore window) shows the deleted marker, not a uuid', async ({
    page,
  }) => {
    // §9: a restorable delete must not break what references it. The only
    // way to reach that state through the API rather than the database is
    // the window a trash-then-restore opens: trash the *referrer* first (so
    // it no longer blocks deleting its target), delete the target, then
    // restore the referrer — which comes back live, still pointing at a
    // target that is now gone.
    await login(page);
    const { authorKey, bookKey } = await makeLibrary(page);
    const author = await apiCreateRecord(page, authorKey, { data: { name: 'Herbert' } });
    const book = await apiCreateRecord(page, bookKey, {
      data: { name: 'Dune', written_by: { type: authorKey, uuid: author.uuid } },
    });

    await apiDeleteRecord(page, bookKey, book.uuid);
    await apiDeleteRecord(page, authorKey, author.uuid);
    await apiRestoreRecord(page, bookKey, book.uuid);

    await page.goto(`/admin/records/${bookKey}`);
    const cell = relationCell(page, book.uuid);
    const marker = cell.getByTestId('records-relation-deleted');
    await expect(marker).toBeVisible();
    await expect(marker).toContainText(author.uuid.slice(0, 8));
    await expect(cell.getByTestId('records-relation-link')).toHaveCount(0);
  });

  test('the editor shows "Referenced by" and the panel lists the referrer with its on_delete badge', async ({
    page,
  }) => {
    await login(page);
    const { authorKey, bookKey } = await makeLibrary(page, 'restrict');
    const author = await apiCreateRecord(page, authorKey, { data: { name: 'Herbert' } });
    const book = await apiCreateRecord(page, bookKey, {
      data: { name: 'Dune', written_by: { type: authorKey, uuid: author.uuid } },
    });

    await page.goto(`/admin/records/${authorKey}/${author.uuid}`);
    await expect(page.getByText('Referenced by 1 record', { exact: true })).toBeVisible();

    await page.getByTestId('records-referrers-toggle').click();
    const item = page.getByTestId('records-referrer-item');
    await expect(item).toHaveCount(1);
    await expect(item.getByRole('link', { name: 'Dune' })).toHaveAttribute(
      'href',
      `/admin/records/${bookKey}/${book.uuid}`,
    );
    await expect(item.getByTestId('records-referrer-on-delete-restrict')).toBeVisible();
    await expect(item.getByTestId('records-referrer-trashed')).toHaveCount(0);
  });

  test('the delete dialog on a restrict target is blocked, with the referrer linked', async ({
    page,
  }) => {
    await login(page);
    const { authorKey, bookKey } = await makeLibrary(page, 'restrict');
    const author = await apiCreateRecord(page, authorKey, { data: { name: 'Herbert' } });
    const book = await apiCreateRecord(page, bookKey, {
      data: { name: 'Dune', written_by: { type: authorKey, uuid: author.uuid } },
    });

    await page.goto(`/admin/records/${authorKey}/${author.uuid}`);
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();

    const referrers = dialog.getByTestId('records-delete-dialog-referrers');
    await expect(referrers).toBeVisible();
    await expect(referrers).toContainText('1 record will block this delete');
    await expect(referrers.getByRole('link', { name: 'Dune' })).toHaveAttribute(
      'href',
      `/admin/records/${bookKey}/${book.uuid}`,
    );

    const confirm = dialog.getByRole('button', { name: 'Delete', exact: true });
    await expect(confirm).toBeDisabled();

    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toHaveCount(0);
    // Still there — the dialog never let the delete through.
    expect((await apiGetRecord(page, authorKey, author.uuid)).is_deleted).toBe(false);
  });

  test('the delete dialog on a set_null target proceeds and clears the reference', async ({
    page,
  }) => {
    await login(page);
    const { authorKey, bookKey } = await makeLibrary(page, 'set_null');
    const author = await apiCreateRecord(page, authorKey, { data: { name: 'Herbert' } });
    await apiCreateRecord(page, bookKey, {
      data: { name: 'Dune', written_by: { type: authorKey, uuid: author.uuid } },
    });

    await page.goto(`/admin/records/${authorKey}/${author.uuid}`);
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('1 record will have this reference cleared');

    const confirm = dialog.getByRole('button', { name: 'Delete', exact: true });
    await expect(confirm).toBeEnabled();
    await confirm.click();
    await expect(dialog).toHaveCount(0);
    await expect(page).toHaveURL(new RegExp(`/admin/records/${authorKey}$`));

    const books = await page.request.get(`/api/records/types/${bookKey}/records`);
    const { items } = (await books.json()) as { items: { data: Json }[] };
    expect(items[0].data.written_by ?? null).toBeNull();
  });

  test('the relation picker finds a record by prefix, and widens to contains', async ({ page }) => {
    await login(page);
    const { authorKey, bookKey } = await makeLibrary(page);
    // Five sharing a prefix, plus one whose distinctive word is in the
    // middle of its title — F9's two cases in one fixture.
    for (let i = 1; i <= 5; i += 1) {
      await apiCreateRecord(page, authorKey, { data: { name: `Common Author ${i}` } });
    }
    await apiCreateRecord(page, authorKey, { data: { name: 'Ursula Le Guin' } });

    // Every relation query the picker makes, in order.
    const filters: string[] = [];
    page.on('request', (request) => {
      const url = new URL(request.url());
      if (!url.pathname.endsWith(`/types/${authorKey}/records`)) return;
      const filter = url.searchParams.get('filter');
      if (filter) filters.push(filter);
    });

    await page.goto(`/admin/records/${bookKey}/new`);
    const picker = page.getByTestId('records-relation-written_by');
    // The picker's input is a `combobox` since UX review R20, not a bare
    // searchbox, and its results are `option`s in a listbox.
    const search = picker.getByRole('combobox');

    // A prefix that finds enough is answered from the title index alone —
    // the `contains` scan is never asked for (F9's `WIDEN_BELOW`).
    await search.fill('Common');
    await expect(picker.getByRole('option', { name: 'Common Author 1' })).toBeVisible();
    await expect.poll(() => filters.length).toBe(1);
    expect(filters[0]).toBe('display_title:starts_with:Common');

    // A term from the middle of a title finds nothing by prefix, and the
    // picker falls back to `contains` rather than saying "No matching records".
    await search.fill('Guin');
    const hit = picker.getByRole('option', { name: 'Ursula Le Guin' });
    await expect(hit).toBeVisible();
    expect(filters.slice(1)).toEqual([
      'display_title:starts_with:Guin',
      'display_title:contains:Guin',
    ]);

    // And picking it is what the search was for.
    await hit.click();
    await expect(picker.getByText('Ursula Le Guin')).toBeVisible();
  });
});
