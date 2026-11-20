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
import { seedItems } from './events-subscriptions-helpers';
import { login, moduleCsrfHeader } from './helpers';

/**
 * A calendar subscribed to an external calendar: the dialog and who may open it, the one refusal,
 * the masked address, the status after the worker's guarded attempt, external entries read-only on
 * the calendar, and what never carries them (the calendar's own `.ics`, the public grid unless
 * the subscription is marked public).
 *
 * The browser suite does not exercise a live fetch: the fetcher refuses loopback whatever the
 * setting says (so a local feed server cannot be reached) and no test host may be given a way
 * around that. The fetch path is covered end to end in the Python suite over a real loopback TLS
 * socket. Where a spec needs external items, `support/seed_external.py` writes them through the
 * module's own store function.
 *
 * Standalone: every test seeds its own calendar through the API.
 */

test.use({ viewport: { width: 1440, height: 1100 } });
const SECRET_URL = 'https://localhost/private/SECRET-TOKEN-123/basic.ics?key=SECRET2';
const CSRF_VIEW = '/admin/events/calendars';
let problems: string[] = [];

test.beforeEach(async ({ page }) => {
  problems = [];
  guard(page, problems);
  await login(page);
});
test.afterEach(() => {
  expect(problems).toEqual([]);
});

type Sub = { id: string; url_display: string; status: string; error_code: string | null };

async function subscribe(page: Page, calendarId: string, url: string, label: string, more = {}) {
  const made = await page.request.post(`/api/events/calendars/${calendarId}/subscriptions`, {
    headers: await moduleCsrfHeader(page, CSRF_VIEW),
    data: { url, label, ...more },
  });
  expect(made.status(), await made.text()).toBe(201);
  return (await made.json()) as Sub;
}

const dialogOf = (page: Page) => page.getByRole('dialog');

test('add, see the masked address and the status, edit and remove', async ({ page }) => {
  const calendar = await seedCalendar(page, { label: 'Neighbourhood hub calendar', plain: true });
  await page.goto('/admin/events/calendars');
  await page.getByRole('button', { name: `Subscriptions of ${calendar.name}` }).click();
  const dialog = dialogOf(page);
  await expect(dialog.getByText('This calendar has no subscriptions yet.')).toBeVisible();
  await dialog.getByRole('button', { name: 'Add a subscription' }).click();
  await dialog.getByLabel('Calendar address (ICS)').fill(SECRET_URL);
  await dialog.getByLabel('Name').fill('Public holidays');
  await expect(dialog.getByText('stored encrypted and never shown again')).toBeVisible();
  await shoot(dialog, '01-subscriptions-dialog');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();

  const row = dialog.getByTestId('subscription-row');
  await expect(row).toContainText('Public holidays');
  await expect(row.getByTestId('subscription-url')).toHaveText('https://localhost/…');
  // the worker's guarded attempt (eager on this host) refuses loopback: one code, no detail
  await expect(row.getByTestId('subscription-status')).toHaveText('Failing');
  await expect(row.getByTestId('subscription-code')).toHaveText(
    'The address cannot be used or reached.',
  );
  await expect(dialog).not.toContainText('SECRET');
  await shoot(dialog, '04-status-failed');

  await row.getByRole('button', { name: 'Edit Public holidays' }).click();
  await expect(dialog.getByLabel('Calendar address (ICS)')).toHaveValue('');
  await dialog.getByLabel('Name').fill('Holidays');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(row).toContainText('Holidays');

  await row.getByRole('button', { name: 'Pause Holidays' }).click();
  await expect(row.getByTestId('subscription-status')).toHaveText('Paused');

  await row.getByRole('button', { name: 'Remove Holidays' }).click();
  const confirm = page.getByRole('alertdialog');
  await expect(confirm).toContainText('cached events disappear from the calendar');
  await confirm.getByRole('button', { name: 'Remove', exact: true }).click();
  await expect(dialog.getByText('This calendar has no subscriptions yet.')).toBeVisible();
});

test('an address that cannot be used gets the one message, and nothing is stored', async ({
  page,
}) => {
  const calendar = await seedCalendar(page, { label: 'Refusals' });
  await page.goto('/admin/events/calendars');
  await page.getByRole('button', { name: `Subscriptions of ${calendar.name}` }).click();
  const dialog = dialogOf(page);
  for (const url of [
    'https://127.0.0.1/a.ics',
    'https://169.254.169.254/latest/',
    'https://[::1]/a.ics',
  ]) {
    await dialog.getByRole('button', { name: 'Add a subscription' }).click();
    await dialog.getByLabel('Calendar address (ICS)').fill(url);
    await dialog.getByLabel('Name').fill('Internal');
    await dialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dialog.getByRole('alert')).toHaveText('The address cannot be used or reached.');
    await dialog.getByRole('button', { name: 'Cancel' }).click();
  }
  const list = await page.request.get(`/api/events/calendars/${calendar.id}/subscriptions`);
  expect(await list.json()).toEqual([]);
});

test('someone who may not manage the calendar cannot open the dialog or call the API', async ({
  page,
  browser,
}) => {
  const calendar = await seedCalendar(page, { label: 'Owned elsewhere' });
  const sub = await subscribe(page, calendar.id, 'https://localhost/a.ics', 'Mine');
  const email = await seedWriter(page, ['events.view', 'events.edit']);
  const context = await browser.newContext();
  const other = await context.newPage();
  const seen: string[] = [];
  guard(other, seen);
  await login(other, { email, password: 'changeme1' });
  await other.goto('/admin/events/calendars');
  await expect(
    other.getByRole('button', { name: `Subscriptions of ${calendar.name}` }),
  ).toHaveCount(0);
  const headers = await moduleCsrfHeader(other, CSRF_VIEW);
  const list = await other.request.get(`/api/events/calendars/${calendar.id}/subscriptions`);
  expect(list.status()).toBe(403); // it sees the calendar, it may not subscribe
  const patch = await other.request.patch(`/api/events/subscriptions/${sub.id}`, {
    headers,
    data: { label: 'x' },
  });
  expect(patch.status()).toBe(403);
  expect(seen).toEqual([]);
  await context.close();
});

test('external entries on the calendar are marked and read-only, and never in its own feed', async ({
  page,
  request,
}) => {
  const day = wednesday(3);
  const calendar = await seedCalendar(page, {
    visibility: 'public',
    label: 'Town hall calendar',
    plain: true,
  });
  const own = await seedEvent(page, {
    calendar: calendar.id,
    title: 'Town meeting',
    start: `${day}T10:00`,
    end: `${day}T11:00`,
  });
  await publishEvent(page, own);
  const sub = await subscribe(
    page,
    calendar.id,
    'https://holidays.localhost/holidays.ics',
    'Public holidays',
  );
  seedItems(sub.id, day, ['National holiday']);

  await page.goto(calendarUrl(calendar.id, 'month', day));
  await expect(chip(page, 'Town meeting')).toBeVisible();
  const external = page.getByTestId('external-chip').filter({ hasText: 'National holiday' });
  await expect(external).toBeVisible();
  await shoot(page, '02-calendar-with-external');
  await external.click();
  const detail = page.getByTestId('external-detail');
  await expect(detail).toContainText('From Public holidays (external calendar)');
  await expect(detail.getByRole('link', { name: 'Open at the source' })).toHaveAttribute(
    'rel',
    'noopener noreferrer nofollow',
  );
  await expect(detail.getByRole('button')).toHaveCount(0); // no edit, move, remind or register
  await shoot(page, '03-external-detail');

  // never re-published: the calendar's own feed carries ours and nothing external
  const feed = await request.get(
    `/events/c/${(await (await page.request.get(`/api/events/calendars/${calendar.id}`)).json()).slug}.ics`,
  );
  expect(feed.status()).toBe(200);
  const body = await feed.text();
  expect(body).toContain('Town meeting');
  expect(body).not.toContain('National holiday');

  // the public grid: not until the subscription is marked public
  const grid = `/events/api/occurrences?start=${day}T00:00:00Z&end=${day}T23:59:59Z`;
  expect(await (await request.get(grid)).text()).not.toContain('National holiday');
  const patched = await page.request.patch(`/api/events/subscriptions/${sub.id}`, {
    headers: await moduleCsrfHeader(page, CSRF_VIEW),
    data: { public: true },
  });
  expect(patched.status(), await patched.text()).toBe(200);
  // a change of the public setting starts a new generation: what was stored is gone until the
  // next fetch, so the entries are stored again as that fetch would
  seedItems(sub.id, day, ['National holiday']);
  const shown = await (await request.get(grid)).text();
  expect(shown).toContain('National holiday');
  expect(shown).toContain('Public holidays');
  expect(
    await (
      await request.get(
        `/events/c/${(await (await page.request.get(`/api/events/calendars/${calendar.id}`)).json()).slug}.ics`,
      )
    ).text(),
  ).not.toContain('National holiday');
});

test('a refresh that fails keeps the cached entries and shows the code', async ({ page }) => {
  const day = wednesday(3);
  const calendar = await seedCalendar(page, { label: 'Kept entries' });
  const sub = await subscribe(page, calendar.id, 'https://kept.localhost/a.ics', 'Feed');
  seedItems(sub.id, day, ['Cached holiday']);
  await page.goto('/admin/events/calendars');
  await page.getByRole('button', { name: `Subscriptions of ${calendar.name}` }).click();
  const dialog = dialogOf(page);
  const row = dialog.getByTestId('subscription-row');
  await expect(row).toContainText('1 event');
  await row.getByRole('button', { name: 'Refresh Feed now' }).click();
  await expect(row.getByTestId('subscription-code')).toHaveText(
    'The address cannot be used or reached.',
  );
  await expect(row).toContainText('1 event');
  await page.goto(calendarUrl(calendar.id, 'month', day));
  await expect(
    page.getByTestId('external-chip').filter({ hasText: 'Cached holiday' }),
  ).toBeVisible();
});

test('German and the phone layout', async ({ page, context }) => {
  const calendar = await seedCalendar(page, { label: 'Kalender Rathaus', plain: true });
  await subscribe(page, calendar.id, 'https://german.localhost/a.ics', 'Feiertage');
  await context.addCookies([
    { name: 'locale', value: 'de', url: new URL('/', page.url()).toString() },
  ]);
  await page.goto('/admin/events/calendars');
  await page.getByRole('button', { name: `Abonnements von ${calendar.name}` }).click();
  const dialog = dialogOf(page);
  await expect(dialog.getByTestId('subscription-row')).toContainText('Feiertage');
  await expect(dialog.getByTestId('subscription-code')).toHaveText(
    'Die Adresse kann nicht verwendet oder erreicht werden.',
  );
  await shoot(dialog, '05-de');
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(dialog).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
  await shoot(page, '06-phone');
});
