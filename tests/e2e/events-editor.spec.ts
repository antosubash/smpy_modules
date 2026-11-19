import { expect, type Page, test } from '@playwright/test';

import {
  apiEvent,
  apiGet,
  apiOverride,
  edit,
  field,
  freshCalendar,
  LIST,
  row,
  save,
  setupSpec,
} from './events-editor-helpers';
import { uniqueSlug } from './helpers';

/**
 * The events list and the event editor, end to end: times in the event's zone,
 * create, validation and recurrence. Standalone: every test seeds its own
 * calendar and events through the API.
 */

setupSpec();

async function openList(page: Page, title: string) {
  await page.goto(LIST);
  await page.getByLabel('Search titles').fill(title);
  return row(page, title);
}

test('the sidebar lists Events and the list shows the time in the event zone', async ({ page }) => {
  const title = `Zone ${uniqueSlug('ev')}`;
  await apiEvent(page, await freshCalendar(page), title);
  await page.goto('/admin/events/calendars');
  const link = page.locator('aside').locator(`a[href="${LIST}"]`);
  await expect(link.getByText('Events', { exact: true })).toBeVisible();
  await link.click();
  await expect(page.getByRole('heading', { name: 'Events', level: 1 })).toBeVisible();
  const found = await openList(page, title);
  await expect(found).toContainText('10:00');
  await expect(found).toContainText('Europe/Vienna');
  await expect(found).not.toContainText('04:00');
  await expect(found).not.toContainText('05:00');
});

test('create an event in the editor: times, rich description and stored instants', async ({
  page,
}) => {
  const title = `Made ${uniqueSlug('ev')}`;
  const calendar = await freshCalendar(page);
  await page.goto(LIST);
  await page.getByLabel('Calendar for the new event').selectOption(calendar);
  await page.getByRole('button', { name: 'New event', exact: true }).click();
  await field(page, 'Title').fill(title);
  await expect(field(page, 'Timezone')).toHaveValue('Europe/Vienna');
  await field(page, 'Start').fill('2027-01-12T10:00');
  await field(page, 'End').fill('2027-01-12T11:30');
  await page.getByRole('textbox', { name: 'Description' }).click();
  await page.keyboard.type('Plain and ');
  await page.getByRole('button', { name: 'Bold', exact: true }).click();
  await page.keyboard.type('bold words');
  await page.getByRole('button', { name: 'Create event' }).click();
  await expect(page).toHaveURL(/\/admin\/events\/edit\/[0-9a-f-]{36}/);
  const id = page.url().split('/').pop() ?? '';

  await page.reload();
  await expect(field(page, 'Title')).toHaveValue(title);
  await expect(field(page, 'Start')).toHaveValue('2027-01-12T10:00');
  await expect(field(page, 'End')).toHaveValue('2027-01-12T11:30');
  const body = page.getByRole('textbox', { name: 'Description' });
  await expect(body).toContainText('Plain and bold words');
  await expect(body.locator('strong, b')).toHaveText('bold words');
  const stored = await apiGet(page, id);
  expect(stored.starts_at).toMatch(/^2027-01-12T09:00:00/);
  expect(stored.ends_at).toMatch(/^2027-01-12T10:30:00/);
});

test('validation: empty title, a time in the DST gap, an end before the start', async ({
  page,
}) => {
  const calendar = await freshCalendar(page);
  await page.goto(`/admin/events/edit/new?calendar=${calendar}`);
  await page.getByRole('button', { name: 'Create event' }).click();
  await expect(field(page, 'Title')).toHaveAccessibleDescription(/required/i);
  await expect(field(page, 'Title')).toBeFocused();

  await field(page, 'Title').fill(`Gap ${uniqueSlug('ev')}`);
  await field(page, 'Start').fill('2026-03-29T02:30');
  await field(page, 'End').fill('2026-03-29T03:30');
  await page.getByRole('button', { name: 'Create event' }).click();
  await expect(field(page, 'Start')).toHaveAccessibleDescription(
    'This time does not exist in the timezone: the clocks skip it.',
  );

  await field(page, 'Start').fill('2027-01-12T10:00');
  await field(page, 'End').fill('2027-01-12T09:00');
  await page.getByRole('button', { name: 'Create event' }).click();
  await expect(field(page, 'End')).toHaveAccessibleDescription('The end must be after the start.');
});

test('a weekly series: summary, DST-aware preview, skip, cancel and move persist', async ({
  page,
}) => {
  const calendar = await freshCalendar(page);
  await page.goto(`/admin/events/edit/new?calendar=${calendar}`);
  await field(page, 'Title').fill(`Weekly ${uniqueSlug('ev')}`);
  await field(page, 'Start').fill('2026-03-03T10:00');
  await field(page, 'End').fill('2026-03-03T11:00');
  await page.getByRole('combobox', { name: 'Repeats', exact: true }).selectOption('WEEKLY');
  await expect(page.getByText(/Every week.*Tuesday/)).toBeVisible();
  const preview = page.getByRole('region', { name: 'Next occurrences' });
  const items = preview.getByRole('listitem');
  await expect(items).toHaveCount(10);
  for (const [index, offset] of ['01', '01', '01', '01', '02'].entries()) {
    await expect(items.nth(index)).toContainText('10:00');
    await expect(items.nth(index)).toContainText(`(UTC+${offset}:00)`);
  }
  await page.getByRole('button', { name: 'Create event' }).click();
  await expect(page).toHaveURL(/\/admin\/events\/edit\/[0-9a-f-]{36}/);
  const id = page.url().split('/').pop() ?? '';

  await preview
    .getByRole('button', { name: /^Skip / })
    .first()
    .click();
  await expect(items.nth(0)).toContainText('Skipped');
  await preview
    .getByRole('button', { name: /^Cancel / })
    .first()
    .click();
  await expect(items.nth(1)).toContainText('Cancelled');
  await preview
    .getByRole('button', { name: /^Move / })
    .first()
    .click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Start', { exact: true }).fill('2026-03-17T14:00');
  await dialog.getByLabel('End', { exact: true }).fill('2026-03-17T15:00');
  await dialog.getByRole('button', { name: 'Move', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  const moved = items.nth(2);
  await expect(moved).toContainText('Moved');
  await expect(moved).toContainText('14:00');

  await page.reload();
  await expect(items.nth(0)).toContainText('Skipped');
  await expect(items.nth(1)).toContainText('Cancelled');
  await expect(items.nth(2)).toContainText('Moved');
  const kinds = (await apiGet(page, id)).overrides.map((o) => o.kind).sort();
  expect(kinds).toEqual(['cancelled', 'moved', 'skipped']);
});

test('changing a series start asks before it drops overrides; cancelling keeps them', async ({
  page,
}) => {
  const calendar = await freshCalendar(page);
  const series = await apiEvent(page, calendar, `Series ${uniqueSlug('ev')}`, {
    start: '2026-03-03T10:00',
    end: '2026-03-03T11:00',
    rrule: 'FREQ=WEEKLY;BYDAY=TU',
  });
  await apiOverride(page, series.id, '2026-03-03T09:00:00Z', 'skipped');
  await apiOverride(page, series.id, '2026-03-10T09:00:00Z', 'cancelled');
  await page.goto(edit(series.id));
  await field(page, 'End').fill('2026-03-03T12:00');
  await field(page, 'Start').fill('2026-03-03T11:00');
  await save(page).click();
  const confirm = page.getByRole('alertdialog');
  await expect(confirm).toContainText('Changed occurrences will be removed');
  await expect(confirm).toContainText('Skipped');
  await expect(confirm).toContainText('Cancelled');
  await confirm.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(confirm).toHaveCount(0);
  const kept = await apiGet(page, series.id);
  expect(kept.overrides).toHaveLength(2);
  expect(kept.starts_at).toMatch(/^2026-03-03T09:00:00/);

  await save(page).click();
  await confirm.getByRole('button', { name: 'Save and remove them' }).click();
  await expect.poll(async () => (await apiGet(page, series.id)).overrides.length).toBe(0);
});
