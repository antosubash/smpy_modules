import { expect, test } from '@playwright/test';

import { calendarUrl, chip, guard, seedWriter } from './events-calendar-helpers';
import { enable, LABEL, seed } from './events-extensions-helpers';
import { shoot } from './events-shots';
import { login } from './helpers';
import { apiGetType, apiUpdateType } from './records-helpers';

/**
 * A second module's dates on an events calendar: records' `records:dates` source, enabled in the
 * Sources dialog, shown with its chip and detail, hidden by the source filter, kept from someone
 * who may not read the record type, reported (not fatal) when its setting breaks, and in German.
 * The dialog and public-site cases are in events-extensions-dialog.spec.ts.
 *
 * Standalone: every test seeds its own calendar, record type and records through the APIs.
 */

test.use({ viewport: { width: 1440, height: 1100 } });
let problems: string[] = [];

test.beforeEach(async ({ page }) => {
  problems = [];
  guard(page, problems);
  await login(page);
});
test.afterEach(() => {
  expect(problems).toEqual([]);
});

test('enable the source in the Sources dialog, see the record, open it', async ({ page }) => {
  const s = await seed(page, 'Project calendar');
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
  const s = await seed(page, 'Team deadlines');
  await enable(page, s);
  await page.goto(calendarUrl(s.calendar.id, 'month', s.day));
  await expect(chip(page, 'Grant report due')).toBeVisible();
  const own = page.getByRole('group', { name: 'Sources' }).getByLabel('Events', { exact: true });
  await own.check();
  await expect(page).toHaveURL(/source=events/);
  await expect(chip(page, 'Kick-off meeting')).toBeVisible();
  await expect(chip(page, 'Grant report due')).toHaveCount(0);
  await shoot(page, '03-source-filter');
  await own.uncheck();
  await expect(chip(page, 'Grant report due')).toBeVisible();
});

test('someone who may not read the record type does not see its records', async ({
  page,
  browser,
}) => {
  const s = await seed(page, 'Staff calendar');
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
  const s = await seed(page, 'Research calendar');
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
  await shoot(page, '04-status-notice');
});

test('German: the dialog, the filter and the notice', async ({ page, context }) => {
  const s = await seed(page, 'Kalender Projekt');
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
