import { expect, test } from '@playwright/test';

import {
  calendarUrl,
  chip,
  guard,
  seedCalendar,
  seedWriter,
  wednesday,
} from './events-calendar-helpers';
import { enable, LABEL, seed } from './events-extensions-helpers';
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
 * The Sources dialog and the public site for records' `records:dates` source: a public record
 * type on the public grid and the phone layout, a mapping the manager may not read (a placeholder
 * that survives a save), a mapping that stopped working (shown as stored, fixable), and the
 * dialog's tab order. Standalone: every test seeds its own calendar and record types.
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
