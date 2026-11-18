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
async function seed(page: Page, label: string): Promise<Seeded> {
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
  const calendar = await seedCalendar(page, { label, plain: true });
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

test('the public grid shows a public record type, and the phone layout holds', async ({
  page,
  browser,
}) => {
  const key = uniqueTypeKey('openday');
  await apiCreateType(page, {
    key,
    label: 'Open days',
    label_plural: 'Open days',
    display_field: 'title',
    is_public: true,
    fields: [
      { key: 'title', type: 'text', label: 'Title', indexed: false },
      { key: 'on', type: 'date', label: 'On', indexed: true },
    ],
  });
  const day = wednesday(3);
  await apiCreateRecord(page, key, {
    status: 'published',
    data: { title: 'Campus open day', on: day },
  });
  const calendar = await seedCalendar(page, {
    visibility: 'public',
    label: 'Open day calendar',
    plain: true,
  });
  const headers = await moduleCsrfHeader(page, '/admin/events/calendars');
  const current = await (await page.request.get(`/api/events/calendars/${calendar.id}`)).json();
  const put = await page.request.put(`/api/events/calendars/${calendar.id}/sources`, {
    headers,
    data: {
      expected: current.sources_version,
      sources: [
        {
          id: 'records:dates',
          settings: { mappings: [{ type_key: key, field: 'on' }] },
        },
      ],
    },
  });
  expect(put.status(), await put.text()).toBe(200);

  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const anon = await context.newPage();
  await anon.goto(`/events/?view=calendar&date=${day}`);
  await expect(anon.getByText('Campus open day').first()).toBeVisible();
  await shoot(anon, '05-public-grid-records');
  await context.close();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(calendarUrl(calendar.id, 'month', day));
  await expect(chip(page, 'Campus open day')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.evaluate(() => window.scrollTo(0, 560));
  await shoot(page, '07-phone');
});

test('a manager who may not read a mapped type sees a placeholder, and keeps it on save', async ({
  page,
  browser,
}) => {
  const s = await seed(page, 'Finance calendar');
  const secret = uniqueTypeKey('salary_reviews');
  await apiCreateType(page, {
    key: secret,
    label: 'Salary reviews',
    label_plural: 'Salary reviews',
    display_field: 'title',
    fields: [
      { key: 'title', type: 'text', label: 'Title', indexed: false },
      { key: 'review', type: 'date', label: 'Review date', indexed: true },
    ],
  });
  const headers = await moduleCsrfHeader(page, '/admin/events/calendars');
  const current = await (await page.request.get(`/api/events/calendars/${s.calendar.id}`)).json();
  const mappings = [
    { type_key: s.key, field: 'due' },
    { type_key: secret, field: 'review', color: '#aa0000' },
  ];
  const put = await page.request.put(`/api/events/calendars/${s.calendar.id}/sources`, {
    headers,
    data: {
      expected: current.sources_version,
      sources: [{ id: 'records:dates', settings: { mappings } }],
    },
  });
  expect(put.status(), await put.text()).toBe(200);
  const type = await apiGetType(page, secret);
  await apiUpdateType(page, secret, type.version, { allowed_roles: ['editor'] });

  const email = await seedWriter(page, ['events.view', 'events.manage', 'records.view']);
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const other = await context.newPage();
  const seen: string[] = [];
  guard(other, seen);
  await login(other, { email, password: 'changeme1' });
  const raw = await other.request.get(`/api/events/calendars/${s.calendar.id}`);
  const text = await raw.text();
  for (const leaked of [secret, 'review', '#aa0000', 'Salary']) expect(text).not.toContain(leaked);
  await other.goto('/admin/events/calendars');
  await other.getByRole('button', { name: `Sources of ${s.calendar.name}` }).click();
  const dialog = other.getByRole('dialog');
  await expect(dialog.getByTestId('records-mapping-hidden')).toContainText(
    'A mapping you cannot view',
  );
  await expect(dialog.getByTestId('records-mapping')).toHaveCount(1);
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).toBeHidden();
  const lifted = await apiGetType(page, secret);
  await apiUpdateType(page, secret, lifted.version, { allowed_roles: [] }); // so the admin can read it
  const stored = await (await page.request.get(`/api/events/calendars/${s.calendar.id}`)).json();
  expect(stored.sources[0].settings.mappings[1]).toMatchObject({ type_key: secret });
  expect(seen).toEqual([]);
  await context.close();
});

test('a mapping whose field stopped being a date is shown as stored and can be fixed', async ({
  page,
}) => {
  const s = await seed(page, 'Library calendar');
  await enable(page, s);
  const type = await apiGetType(page, s.key);
  await apiUpdateType(page, s.key, type.version, {
    fields: [
      { key: 'title', type: 'text', label: 'Title', indexed: false },
      { key: 'due', type: 'date', label: 'Due', indexed: false },
    ],
  });
  await page.goto('/admin/events/calendars');
  await page.getByRole('button', { name: `Sources of ${s.calendar.name}` }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Record type')).toHaveValue(s.key);
  await expect(dialog.getByLabel('Date field')).toHaveValue('due');
  await expect(dialog).toContainText('due (no longer available)');
  await expect(dialog).toContainText('no longer an indexed date');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).toContainText('no longer an indexed date');
  await dialog.getByLabel(LABEL).click(); // turning the source off always works (after asking)
  await page.getByRole('alertdialog').getByRole('button', { name: 'Turn off' }).click();
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).toBeHidden();
});

test('the dialog reads in order: the sources first, then Cancel and Save', async ({ page }) => {
  const s = await seed(page, 'Events desk');
  await page.goto('/admin/events/calendars');
  await page.getByRole('button', { name: `Sources of ${s.calendar.name}` }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel(LABEL)).toBeVisible();
  const order: string[] = [];
  for (let i = 0; i < 6; i++) {
    order.push(
      await page.evaluate(() => {
        const e = document.activeElement as HTMLElement | null;
        return `${e?.tagName}:${(e?.getAttribute('aria-label') || e?.textContent || '').trim()}`;
      }),
    );
    await page.keyboard.press('Tab');
  }
  const first = order.findIndex((o) => o.startsWith('INPUT'));
  const cancel = order.findIndex((o) => o.endsWith(':Cancel'));
  expect(first, order.join(' > ')).toBeGreaterThanOrEqual(0);
  expect(cancel === -1 || cancel > first, order.join(' > ')).toBe(true);
});
