import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import {
  addFieldInEditor,
  apiCreateRecord,
  apiCreateType,
  applyFilter,
  confirmDialog,
  recordField,
  rowTitles,
  saveType,
  uniqueTypeKey,
} from './records-helpers';

/**
 * Collections — Phase 5 §6: one Record Type's documents and index rows in
 * their own table set (`records_c_events_*`) instead of the shared one.
 *
 * The demo host declares exactly one (`host/records_collections.py`:
 * `declare_collection("events")`), which is what makes this suite possible
 * at all — the list of collections is the host's Python, not a setting.
 *
 * The property under test is that a collection changes *where* the rows are
 * and nothing else: the same screens, the same list, filter, sort, editor,
 * trash, Languages panel and referrers as a type on the shared tables. Every
 * assertion below is one an equivalent global type would also pass; a
 * regression in the `TableSet` seam is what makes them stop passing.
 */

/** The collection `host/records_collections.py` declares. */
const COLLECTION = 'events';

async function seedCollectionType(
  page: Page,
  prefix: string,
  extra: Record<string, unknown> = {},
): Promise<string> {
  const key = uniqueTypeKey(prefix);
  await apiCreateType(page, {
    key,
    label: 'Event',
    label_plural: 'Events',
    collection: COLLECTION,
    fields: [
      // Not labelled "Title": the table's own display-title column is, and
      // two header buttons with the same accessible name are ambiguous.
      { key: 'title', type: 'text', label: 'Event title', indexed: true },
      { key: 'venue', type: 'text', label: 'Venue', indexed: true },
    ],
    display_field: 'title',
    ...extra,
  });
  return key;
}

test.describe('Records — collections', () => {
  test('the new-type form offers the declared collection, and freezes it afterwards', async ({
    page,
  }) => {
    await login(page);
    const key = uniqueTypeKey('coll');

    await page.goto('/admin/records/types/new');
    const field = page.getByTestId('records-collection');
    await expect(field).toBeVisible();
    const select = page.locator('#type-editor-collection');
    // "Shared tables" is the default and the host's one declared collection
    // is the only alternative.
    await expect(select).toHaveValue('');
    await expect(select.locator('option')).toHaveText(['Shared tables', COLLECTION]);
    await expect(
      field.getByText('Gives this type its own document and index tables. Chosen once'),
    ).toBeVisible();

    await select.selectOption(COLLECTION);
    await page.locator('#type-editor-key').fill(key);
    await page.locator('#type-editor-label').fill('Conference');
    await page.locator('#type-editor-label-plural').fill('Conferences');
    await addFieldInEditor(page, 0, { key: 'title', type: 'text', label: 'Title', indexed: true });
    await page.locator('#type-editor-display-field').selectOption('title');
    await saveType(page);

    await expect(page).toHaveURL(new RegExp(`/admin/records/types/${key}$`));
    // §6.2: moving a populated type between collections is a 409, so the
    // control stops being a control once the type exists.
    const frozen = page.locator('#type-editor-collection');
    await expect(frozen).toHaveValue(COLLECTION);
    await expect(frozen).toBeDisabled();
    await expect(
      page.getByText("A type can't be moved between collections once it is created."),
    ).toBeVisible();

    const stored = await page.request.get(`/api/records/types/${key}`);
    expect((await stored.json()).collection).toBe(COLLECTION);

    // Which collection a type is in is visible from the types list too, not
    // only from opening its editor (UX-6).
    await page.goto('/admin/records/');
    const row = page.locator(`[data-testid="records-type-row"][data-type-key="${key}"]`);
    await expect(row.getByTestId('records-type-collection-badge')).toHaveText(COLLECTION);

    // A type on the shared tables shows no collection control at all — there
    // is nothing to say about it, and §6.5's "inert when unused" is what the
    // absence expresses.
    const globalKey = uniqueTypeKey('global');
    await apiCreateType(page, {
      key: globalKey,
      label: 'Shared thing',
      fields: [{ key: 'title', type: 'text', label: 'Title', indexed: true }],
      display_field: 'title',
    });
    await page.goto(`/admin/records/types/${globalKey}`);
    await expect(page.getByTestId('records-collection')).toHaveCount(0);
    await page.goto('/admin/records/');
    const globalRow = page.locator(
      `[data-testid="records-type-row"][data-type-key="${globalKey}"]`,
    );
    await expect(globalRow.getByTestId('records-type-collection-badge')).toHaveCount(0);
  });

  test('a collection type lists, creates, edits, filters, sorts and deletes like a global one', async ({
    page,
  }) => {
    await login(page);
    const key = await seedCollectionType(page, 'collcrud');

    // Create through the record form, so the write goes through the UI into
    // the collection's own tables rather than only through the API.
    await page.goto(`/admin/records/${key}/new`);
    await recordField(page, 'title').fill('Opening night');
    await recordField(page, 'venue').fill('Barbican');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}/[0-9a-f]{32}$`));

    await apiCreateRecord(page, key, { data: { title: 'Closing night', venue: 'Almeida' } });
    await apiCreateRecord(page, key, { data: { title: 'Matinee', venue: 'Barbican' } });

    await page.goto(`/admin/records/${key}`);
    await expect
      .poll(() => rowTitles(page))
      .toEqual(expect.arrayContaining(['Opening night', 'Closing night', 'Matinee']));

    // Sorting reads the collection's own index table.
    await page.getByRole('button', { name: 'Title', exact: true }).click();
    await expect.poll(() => rowTitles(page)).toEqual(['Closing night', 'Matinee', 'Opening night']);

    // Filtering does too — the semi-join is against `records_c_events_index_*`.
    // Polled against the *exact* set: the unfiltered list also contains both
    // titles, so an `arrayContaining` poll resolves before the filtered
    // reload lands and a plain "Closing night is absent" check then races it.
    await applyFilter(page, 'venue', 'eq', 'Barbican');
    await expect.poll(() => rowTitles(page)).toEqual(['Matinee', 'Opening night']);
    await page.getByRole('button', { name: 'Clear' }).click();

    // Edit, then delete, from the editor.
    await page.getByRole('link', { name: 'Matinee' }).click();
    await recordField(page, 'title').fill('Matinee (moved)');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Matinee (moved)' })).toBeVisible();

    await confirmDialog(page, page.getByRole('button', { name: 'Delete' }), 'Delete');
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}$`));
    await expect.poll(() => rowTitles(page)).not.toContain('Matinee (moved)');
  });

  test('a collection type translates, and a global type expands a relation into it', async ({
    page,
  }) => {
    await login(page);
    const eventKey = await seedCollectionType(page, 'collt', { translatable: true });
    const event = await apiCreateRecord(page, eventKey, {
      data: { title: 'Festival', venue: 'Roundhouse' },
      status: 'published',
    });

    // A global type pointing into the collection (§6.3: relations cross
    // collections; the target type decides the table).
    const ticketKey = uniqueTypeKey('ticket');
    await apiCreateType(page, {
      key: ticketKey,
      label: 'Ticket',
      label_plural: 'Tickets',
      fields: [
        { key: 'name', type: 'text', label: 'Name', indexed: true },
        {
          key: 'event',
          type: 'relation',
          label: 'Event',
          options: { target_type: eventKey, on_delete: 'restrict' },
        },
      ],
      display_field: 'name',
    });
    const ticket = await apiCreateRecord(page, ticketKey, {
      data: { name: 'Row A', event: { type: eventKey, uuid: event.uuid } },
    });

    // The list cell resolves the title out of the collection's record table.
    await page.goto(`/admin/records/${ticketKey}`);
    const cell = page
      .locator(`[data-record-uuid="${ticket.uuid}"]`)
      .getByTestId('records-relation-link');
    await expect(cell).toHaveText('Festival');
    await expect(cell).toHaveAttribute('href', `/admin/records/${eventKey}/${event.uuid}`);

    // "Referenced by" walks every table set and keeps each set's ids with
    // its own class (§6.6) — the referrer here lives in the shared tables
    // and the record being asked about does not.
    await page.goto(`/admin/records/${eventKey}/${event.uuid}`);
    await page.getByTestId('records-referrers-toggle').click();
    const referrer = page.getByTestId('records-referrer-item');
    await expect(referrer).toHaveCount(1);
    await expect(referrer).toContainText('Row A');

    // And the Languages panel behaves as it does on the shared tables: the
    // sibling is a record of its own in the collection's own table.
    const addDe = page.getByTestId('records-translation-add-de');
    await expect(addDe).toBeVisible();
    await addDe.click();
    await expect(page).toHaveURL(new RegExp(`/admin/records/${eventKey}/[0-9a-f]{32}$`));
    await expect(page).not.toHaveURL(new RegExp(`/${event.uuid}$`));
    await expect(page.getByTestId('records-locale-badge')).toHaveText('Deutsch');
    await expect(recordField(page, 'title')).toHaveValue('Festival');

    await page.goto(`/admin/records/${eventKey}`);
    await expect(page.locator('thead').getByText('Language', { exact: true })).toBeVisible();
    await applyFilter(page, 'locale', 'eq', 'de');
    await expect.poll(() => rowTitles(page)).toEqual(['Festival']);
  });
});
