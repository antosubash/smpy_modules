import { expect, type Locator, type Page } from '@playwright/test';
import { type EventSeed, postCalendar, postEvent, ZONE } from './events-seed';
import { moduleCsrfHeader, uniqueSlug } from './helpers';

/** Seeds for events-calendar.spec.ts: everything is made through the API with unique names. */

const CSRF_VIEW = '/admin/events/calendars';

export { ZONE };

export type Seeded = { id: string; title: string; revision: number };

/** A Wednesday at least three weeks away, as YYYY-MM-DD: always a whole week ahead of "now". */
export function wednesday(weeksAhead = 3): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() + weeksAhead * 7);
  d.setUTCDate(d.getUTCDate() + ((3 - d.getUTCDay() + 7) % 7));
  return d.toISOString().slice(0, 10);
}

export function addDays(date: string, days: number): string {
  const d = new Date(`${date}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export async function seedCalendar(
  page: Page,
  { visibility = 'internal', color = '#2563eb', zone = ZONE, label = 'Cal' } = {},
): Promise<{ id: string; name: string }> {
  const { id, name } = await postCalendar(page, {
    name: `${label} ${uniqueSlug('c')}`,
    visibility,
    color,
    zone,
  });
  return { id, name };
}

type SeedInput = Omit<EventSeed, 'calendar'> & { calendar: string };

export async function seedEvent(page: Page, seed: SeedInput): Promise<Seeded> {
  const { id, revision } = await postEvent(page, seed);
  return { id, title: seed.title, revision };
}

/** Draft -> in review -> published, as the admin (who holds events.publish). */
export async function publish(page: Page, event: Seeded): Promise<void> {
  const headers = await moduleCsrfHeader(page, CSRF_VIEW);
  const submit = await page.request.post(`/api/events/events/${event.id}/submit`, {
    headers,
    data: { expected_revision: event.revision },
  });
  expect(submit.status(), await submit.text()).toBe(200);
  const { revision } = (await submit.json()) as { revision: number };
  const approve = await page.request.post(`/api/events/events/${event.id}/approve`, {
    headers,
    data: { expected_revision: revision },
  });
  expect(approve.status(), await approve.text()).toBe(200);
}

export type ApiEvent = {
  start_local: string;
  end_local: string;
  status: string;
  overrides: { kind: string; start_local: string | null; original_start: string }[];
};

export async function apiEvent(page: Page, id: string): Promise<ApiEvent> {
  const res = await page.request.get(`/api/events/events/${id}`);
  expect(res.status(), await res.text()).toBe(200);
  return (await res.json()) as ApiEvent;
}

export async function listEvents(
  page: Page,
  calendar: string,
): Promise<(ApiEvent & { title: string })[]> {
  const res = await page.request.get(`/api/events/events?calendar=${calendar}&page_size=100`);
  expect(res.status(), await res.text()).toBe(200);
  return ((await res.json()) as { items: (ApiEvent & { title: string })[] }).items;
}

export function calendarUrl(
  calendar: string,
  view: 'month' | 'week' | 'day' | 'list',
  date: string,
  extra = '',
): string {
  return `/admin/events/?view=${view}&date=${date}&calendar=${calendar}${extra}`;
}

/** Fails the test on a page error or a Content Security Policy console message. */
export function guard(page: Page, problems: string[]) {
  page.on('pageerror', (error) => problems.push(String(error)));
  page.on('console', (message) => {
    if (message.text().includes('Content Security Policy')) problems.push(message.text());
  });
}

export const chip = (page: Page, title: string) =>
  page.getByRole('button', { name: new RegExp(title) }).first();
export const monthYear = (date: string) =>
  new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(
    new Date(`${date}T12:00:00Z`),
  );

/** Move the pointer like a person: down on the chip, a stepped move, up. */
export async function dragBy(page: Page, from: Locator, dx: number, dy: number, grab = 0.5) {
  await from.scrollIntoViewIfNeeded();
  const box = (await from.boundingBox()) ?? { x: 0, y: 0, width: 0, height: 0 };
  const x = box.x + box.width / 2;
  const y = box.y + box.height * grab;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx / 2, y + dy / 2, { steps: 10 });
  await page.mouse.move(x + dx, y + dy, { steps: 10 });
  await page.mouse.up();
}

/** One day column and one hour, in pixels, read from the grid's own labels. */
export async function gridSize(page: Page) {
  const centre = async (l: Locator) => {
    const b = (await l.boundingBox()) ?? { x: 0, y: 0, width: 0, height: 0 };
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  };
  const wed = await centre(page.getByText(/^Wed \d+$/));
  const thu = await centre(page.getByText(/^Thu \d+$/));
  const a = await centre(page.getByText('10am', { exact: true }));
  const b = await centre(page.getByText('11am', { exact: true }));
  return { column: thu.x - wed.x, hour: b.y - a.y, wedX: wed.x, topOfTen: a.y };
}

export async function seedWeek(page: Page) {
  const cal = await seedCalendar(page);
  const day = wednesday();
  const one = `One ${uniqueSlug('o')}`;
  const series = `Series ${uniqueSlug('s')}`;
  const oneOff = await seedEvent(page, {
    calendar: cal.id,
    title: one,
    start: `${day}T10:00`,
    end: `${day}T11:00`,
  });
  const weekly = await seedEvent(page, {
    calendar: cal.id,
    title: series,
    start: `${day}T13:00`,
    end: `${day}T14:00`,
    rrule: 'FREQ=WEEKLY;BYDAY=WE',
  });
  return { cal, day, one, series, oneOff, weekly };
}

/** Drag the lower edge of a chip down by `by` pixels, as a person would. */
export async function resizeBy(page: Page, target: Locator, by: number) {
  await target.hover();
  const box = (await target.boundingBox()) ?? { x: 0, y: 0, width: 0, height: 0 };
  const x = box.x + box.width / 2;
  const edge = box.y + box.height - 2;
  await page.mouse.move(x, edge);
  await page.mouse.down();
  await page.mouse.move(x, edge + by / 2, { steps: 8 });
  await page.mouse.move(x, edge + by, { steps: 8 });
  await page.mouse.up();
}

/** A user who may view and edit events but not publish them (or holds `permissions`); returns the email. */
export async function seedWriter(
  page: Page,
  permissions = ['events.view', 'events.edit'],
): Promise<string> {
  const email = `cal-writer-${uniqueSlug('w').replace(/-/g, '')}@example.com`;
  const created = await page.request.post('/api/users/admin', {
    headers: { 'content-type': 'application/json' },
    data: { email, password: 'changeme1', role_names: [] },
  });
  expect(created.status(), await created.text()).toBe(201);
  const users = (await (await page.request.get('/api/users/admin?per_page=100')).json()) as {
    id: string;
    email: string;
  }[];
  const id = users.find((u) => u.email === email)?.id;
  const granted = await page.request.put(`/api/permissions/users/${id}`, {
    headers: { 'content-type': 'application/json' },
    data: { permissions },
  });
  expect(granted.status(), await granted.text()).toBe(200);
  return email;
}

/** The New York hour (as digits, no padding) of 10:00 in Vienna on that date. */
export function viennaTenInNewYork(day: string): string {
  const hourIn = (zone: string, at: Date) =>
    new Intl.DateTimeFormat('en-GB', { timeZone: zone, hour: '2-digit', hourCycle: 'h23' }).format(
      at,
    );
  const at = [8, 9]
    .map((h) => new Date(`${day}T${String(h).padStart(2, '0')}:00:00Z`))
    .find((d) => hourIn('Europe/Vienna', d) === '10') as Date;
  return String(Number(hourIn('America/New_York', at)));
}

/** A one-hour 09:00 event on `day`. */
export const seedOne = (page: Page, calendar: string, title: string, day: string) =>
  seedEvent(page, { calendar, title, start: `${day}T09:00`, end: `${day}T10:00` });

/** Tab from the view switcher until `target` has focus. */
export async function tabTo(page: Page, target: Locator) {
  await page.getByRole('button', { name: 'Week', exact: true }).focus();
  for (let i = 0; i < 60; i++) {
    if (await target.evaluate((el) => el === document.activeElement)) return;
    await page.keyboard.press('Tab');
  }
}

/** Focus is on a calendar chip or the toolbar title, not lost to the page body. */
export const focusIsOnCalendar = (page: Page) =>
  page.evaluate(
    () =>
      document.activeElement?.getAttribute('data-testid') === 'calendar-title' ||
      document.activeElement?.closest('[class*="fc-"], .fc') != null,
  );
