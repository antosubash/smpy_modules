import { expect, type Page, test } from '@playwright/test';

import {
  calendarUrl,
  chip,
  guard,
  seedCalendar,
  seedEvent,
  seedWriter,
  wednesday,
} from './events-calendar-helpers';
import { publishEvent } from './events-seed';
import { shoot } from './events-shots';
import { login, moduleCsrfHeader } from './helpers';
import {
  apiCreateRecord,
  apiCreateType,
  apiGetType,
  apiUpdateType,
  uniqueTypeKey,
} from './records-helpers';

/**
 * A second module's dates on an events calendar: records' `records:dates` source, enabled in
 * the Sources dialog, shown with its chip and detail, hidden by the source filter, kept from
 * someone who may not read the record type, reported (not fatal) when its setting breaks, and
 * in German.
 *
 * Standalone: every test seeds its own calendar, record type and records through the APIs.
 */

test.use({ viewport: { width: 1440, height: 1100 } });
const LABEL = 'Records with a date';
let problems: string[] = [];

test.beforeEach(async ({ page }) => {
  problems = [];
  guard(page, problems);
  await login(page);
});
test.afterEach(() => {
  expect(problems).toEqual([]);
});

type Seeded = { calendar: { id: string; name: string }; key: string; day: string; uuid: string };

/** An internal calendar, a "Project deadlines" type (title, indexed `due` date) and one
 *  published deadline three weeks out, plus a plain event the same day. */
async function seed(page: Page): Promise<Seeded> {
  const key = uniqueTypeKey('deadlines');
  await apiCreateType(page, {
    key,
    label: 'Project deadlines',
    label_plural: 'Project deadlines',
    display_field: 'title',
    fields: [
      { key: 'title', type: 'text', label: 'Title', indexed: false },
      { key: 'due', type: 'date', label: 'Due', indexed: true },
    ],
  });
  const day = wednesday(3);
  const record = await apiCreateRecord(page, key, {
    status: 'published',
    data: { title: 'Grant report due', due: day },
  });
  const calendar = await seedCalendar(page, { label: 'Project calendar' });
  const event = await seedEvent(page, {
    calendar: calendar.id,
    title: 'Kick-off meeting',
    start: `${day}T10:00`,
    end: `${day}T11:00`,
  });
  await publishEvent(page, event); // a viewer sees published events only
  return { calendar, key, day, uuid: record.uuid };
}

async function enable(page: Page, s: Seeded, mapping: Record<string, unknown> = {}) {
  const headers = await moduleCsrfHeader(page, '/admin/events/calendars');
  const current = await (await page.request.get(`/api/events/calendars/${s.calendar.id}`)).json();
  const put = await page.request.put(`/api/events/calendars/${s.calendar.id}/sources`, {
    headers,
    data: {
      expected: current.sources_version,
      sources: [
        {
          id: 'records:dates',
          settings: { mappings: [{ type_key: s.key, field: 'due', ...mapping }] },
        },
      ],
    },
  });
  expect(put.status(), await put.text()).toBe(200);
}

test('enable the source in the Sources dialog, see the record, open it', async ({ page }) => {
  const s = await seed(page);
  await page.goto('/admin/events/calendars');
  await page.getByRole('button', { name: `Sources of ${s.calendar.name}` }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel(LABEL).check();
  await dialog.getByLabel('Record type').selectOption(s.key);
  await dialog.getByLabel('Date field').selectOption('due');
  await shoot(dialog, '01-sources-dialog');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).toBeHidden();

  await page.goto(calendarUrl(s.calendar.id, 'month', s.day));
  await expect(chip(page, 'Kick-off meeting')).toBeVisible();
  await expect(chip(page, 'Grant report due')).toBeVisible();
  await shoot(page, '02-calendar-with-records');
  await chip(page, 'Grant report due').click();
  await page.getByRole('link', { name: 'Open record' }).click();
  await expect(page).toHaveURL(new RegExp(`/admin/records/${s.key}/${s.uuid}$`));
  await expect(page.getByLabel('Title')).toHaveValue('Grant report due');
});

test('the source filter leaves the records out', async ({ page }) => {
  const s = await seed(page);
  await enable(page, s);
  await page.goto(calendarUrl(s.calendar.id, 'month', s.day));
  await expect(chip(page, 'Grant report due')).toBeVisible();
  const own = page.getByRole('group', { name: 'Sources' }).getByLabel('Events', { exact: true });
  await own.check();
  await expect(page).toHaveURL(/source=events/);
  await expect(chip(page, 'Kick-off meeting')).toBeVisible();
  await expect(chip(page, 'Grant report due')).toHaveCount(0);
  await own.uncheck();
  await expect(chip(page, 'Grant report due')).toBeVisible();
});

test('someone who may not read the record type does not see its records', async ({
  page,
  browser,
}) => {
  const s = await seed(page);
  await enable(page, s); // while the admin may still read the type
  const type = await apiGetType(page, s.key);
  await apiUpdateType(page, s.key, type.version, { allowed_roles: ['editor'] }); // editors only
  const email = await seedWriter(page, ['events.view', 'records.view']);
  const context = await browser.newContext();
  const other = await context.newPage();
  const seen: string[] = [];
  guard(other, seen);
  await login(other, { email, password: 'changeme1' });
  await other.goto(calendarUrl(s.calendar.id, 'month', s.day));
  await expect(chip(other, 'Kick-off meeting')).toBeVisible();
  await expect(chip(other, 'Grant report due')).toHaveCount(0);
  const read = await other.request.get(
    `/api/events/occurrences?calendar=${s.calendar.id}&start=${s.day}T00:00:00Z&end=${s.day}T23:59:00Z`,
  );
  const sources = ((await read.json()) as { items: { source: string }[] }).items.map(
    (i) => i.source,
  );
  expect(sources).toEqual(['events']);
  expect(seen).toEqual([]);
  await context.close();
});

test('a setting that no longer fits shows a notice and the calendar keeps working', async ({
  page,
}) => {
  const s = await seed(page);
  await enable(page, s);
  const type = await apiGetType(page, s.key);
  await apiUpdateType(page, s.key, type.version, {
    fields: [
      { key: 'title', type: 'text', label: 'Title', indexed: false },
      { key: 'due', type: 'date', label: 'Due', indexed: false },
    ],
  });
  await page.goto(calendarUrl(s.calendar.id, 'month', s.day));
  await expect(chip(page, 'Kick-off meeting')).toBeVisible();
  const notice = page.getByTestId('source-status');
  await expect(notice).toContainText(`${LABEL} could not be loaded`);
  await expect(chip(page, 'Grant report due')).toHaveCount(0);
  await shoot(page, '03-source-status-notice');
});

test('German: the dialog, the filter and the notice', async ({ page, context }) => {
  const s = await seed(page);
  await enable(page, s);
  await context.addCookies([
    { name: 'locale', value: 'de', url: new URL('/', page.url()).toString() },
  ]);
  await page.goto('/admin/events/calendars');
  await page.getByRole('button', { name: `Quellen von ${s.calendar.name}` }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Datensätze mit Datum')).toBeChecked();
  await expect(dialog.getByLabel('Datensatztyp')).toHaveValue(s.key);
  await dialog.getByRole('button', { name: 'Abbrechen' }).click();
  await page.goto(calendarUrl(s.calendar.id, 'month', s.day));
  await expect(chip(page, 'Grant report due')).toBeVisible();
  await expect(page.getByRole('group', { name: 'Quellen' })).toBeVisible();
  await shoot(page, '06-de');
});
