import { readFileSync } from 'node:fs';

import { expect, type Page, test } from '@playwright/test';

import { guard, seedCalendar, seedWriter } from './events-calendar-helpers';
import { shoot } from './events-shots';
import { login } from './helpers';

/**
 * The .ics import on the production bundle, as a New York browser into a Vienna calendar.
 * Standalone: its calendar and its viewer are seeded through the API.
 */
test.skip(process.env.E2E_BUNDLE !== '1', 'the nonce policy exists only in the bundle');
test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1280, height: 1000 }, timezoneId: 'America/New_York' });

const FIXTURE = readFileSync('tests/e2e/fixtures/events-import.ics');
const IMPORT = '/admin/events/import';
let problems: string[] = [];

test.beforeEach(async ({ page }) => {
  problems = [];
  guard(page, problems);
  await login(page);
});
test.afterEach(() => expect(problems).toEqual([]));

async function upload(page: Page, calendar: string, name: string, buffer: Buffer) {
  await page.goto(IMPORT);
  await page.getByLabel('Into calendar').selectOption({ label: calendar });
  await page
    .getByLabel('Calendar file (.ics)')
    .setInputFiles({ name, mimeType: 'text/calendar', buffer });
  await page.getByRole('button', { name: 'Upload and preview' }).click();
}

async function titles(page: Page, calendar: string): Promise<Record<string, string>> {
  const res = await page.request.get(`/api/events/events?calendar=${calendar}&page_size=100`);
  const items = (
    (await res.json()) as { items: { title: string; start_local: string; status: string }[] }
  ).items;
  return Object.fromEntries(items.map((e) => [e.title, `${e.status} ${e.start_local}`]));
}

test('a realistic file goes through preview, import and a second import', async ({ page }) => {
  const cal = await seedCalendar(page, { visibility: 'internal', label: 'Imported' });
  await page.goto(IMPORT);
  await shoot(page, '03-import-upload');

  await upload(page, cal.name, 'term.ics', FIXTURE);
  await expect(page.getByRole('heading', { name: 'Preview' })).toBeFocused();
  await expect(page.getByTestId('events-import-announce')).toContainText('Preview ready: 5 events');
  const table = page.getByRole('table');
  await expect(table.getByText('Imported lecture')).toBeVisible();
  await expect(table.getByText('Imported choir')).toBeVisible();
  await expect(table.getByText('Imported spring fair')).toBeVisible();
  await expect(table.getByText('Imported board meeting')).toBeVisible();
  await shoot(page, '04-import-preview', { fullPage: true });

  await page.getByRole('button', { name: 'Import as drafts' }).click();
  await expect(page.getByRole('heading', { name: 'Result' })).toBeVisible();
  await expect(page.getByText(/Created [1-9]/)).toBeVisible();
  await shoot(page, '05-import-result', { fullPage: true });

  const made = await titles(page, cal.id);
  expect(made['Imported lecture']).toBe('draft 2027-03-10T10:00'); // Vienna time, not New York
  expect(made['Imported choir']).toMatch(/^draft 2027-03-01T18:00/);
  expect(made['Imported spring fair']).toMatch(/^draft 2027-03-20/);
  expect(made['Imported board meeting']).toMatch(/^draft /); // a private item is kept as a draft
  expect(made['Imported ticker']).toBeUndefined(); // an unsupported rule is skipped, not guessed

  // The same file again changes nothing.
  await upload(page, cal.name, 'term.ics', FIXTURE);
  await expect(page.getByRole('heading', { name: 'Preview' })).toBeVisible();
  await expect(page.getByRole('button', { name: /^Unchanged 4/ })).toBeVisible(); // the preview agrees
  await expect(page.getByRole('button', { name: /^Update 0/ })).toBeVisible();
  await page.getByRole('button', { name: 'Import as drafts' }).click();
  await expect(page.getByRole('heading', { name: 'Result' })).toBeVisible();
  await expect(page.getByText('Created 0')).toBeVisible();
  await expect(page.getByText('Updated 0')).toBeVisible();
  expect(await titles(page, cal.id)).toEqual(made);
});

test('a file with too many events is refused with a readable message', async ({ page }) => {
  const cal = await seedCalendar(page, { visibility: 'internal', label: 'Hostile' });
  const one = (n: number) =>
    `BEGIN:VEVENT\r\nUID:h${n}@x\r\nDTSTART:20270301T080000Z\r\nDTEND:20270301T090000Z\r\nSUMMARY:E${n}\r\nEND:VEVENT\r\n`;
  const body = `BEGIN:VCALENDAR\r\nVERSION:2.0\r\n${Array.from({ length: 5001 }, (_, n) => one(n)).join('')}END:VCALENDAR\r\n`;
  await upload(page, cal.name, 'huge.ics', Buffer.from(body));
  await expect(page.getByRole('heading', { name: 'The import failed' })).toBeFocused();
  await expect(page.getByRole('alert')).toContainText(/more events than one import takes/);
  await shoot(page, '06-import-refused', { fullPage: true });
});

test('a user who may only view cannot import; the screen speaks German; fits a phone', async ({
  page,
  browser,
  context,
}) => {
  const email = await seedWriter(page, ['events.view']);
  const other = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const viewer = await other.newPage();
  guard(viewer, problems);
  await login(viewer, { email, password: 'changeme1' });
  const res = await viewer.goto(IMPORT);
  expect(res?.status()).toBe(403); // events.manage is required; the unit tests pin the same code
  await expect(viewer.getByLabel('Calendar file (.ics)')).toHaveCount(0);
  expect((await viewer.request.get('/api/events/imports')).status()).toBe(403);
  await other.close();

  const origin = new URL(page.url()).origin;
  await context.addCookies([{ name: 'locale', value: 'de', url: origin }]);
  await page.goto(IMPORT);
  await expect(page.getByRole('heading', { name: 'Termine importieren' })).toBeVisible();
  await shoot(page, '07-import-de');
  await context.addCookies([{ name: 'locale', value: 'en', url: origin }]);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(IMPORT);
  await expect(page.getByRole('heading', { name: 'Import events' })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
  await shoot(page, '08-phone');
});
