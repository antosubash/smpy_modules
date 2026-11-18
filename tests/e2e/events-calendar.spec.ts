import { expect, test } from '@playwright/test';

import {
  addDays,
  apiEvent,
  calendarUrl,
  chip,
  dragBy,
  gridSize,
  guard,
  listEvents,
  monthYear,
  publish,
  resizeBy,
  seedCalendar,
  seedOne,
  seedWeek,
  seedWriter,
  tabTo,
  viennaTenInNewYork,
  wednesday,
} from './events-calendar-helpers';
import { login, uniqueSlug } from './helpers';

/**
 * The console calendar on the production bundle: views, filters, create, the Move dialog,
 * a real pointer drag and resize, "this one or all", the grid time zone, the German console
 * and a writer who may not touch a published event.
 *
 * Standalone: each test seeds its own calendar and events through the API.
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

test('/admin/events/ is the calendar, first in the sidebar', async ({ page }) => {
  await page.goto('/admin/events/');
  await expect(page).toHaveURL(/\/admin\/events\/(\?.*)?$/);
  await expect(page.getByRole('heading', { name: 'Calendar', level: 1 })).toBeVisible();
  const links = page.locator('aside a[href^="/admin/events"]');
  await expect(links.first()).toHaveAttribute('href', '/admin/events/');
  await expect(links.first()).toContainText('Calendar');
});

test('month, week, day and list show the one-off and the series, and the title follows', async ({
  page,
}) => {
  const { cal, day, one, series } = await seedWeek(page);
  await page.goto(calendarUrl(cal.id, 'month', day));
  const title = page.getByTestId('calendar-title');
  await expect(title).toHaveText(monthYear(day));
  await expect(chip(page, one)).toBeVisible();
  await expect(chip(page, series)).toBeVisible();

  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(title).toHaveText(monthYear(addDays(day, 31)));
  await page.getByRole('button', { name: 'Previous', exact: true }).click();
  await expect(title).toHaveText(monthYear(day));
  await page.getByRole('button', { name: 'Today', exact: true }).click();
  await expect(title).toHaveText(monthYear(new Date().toISOString().slice(0, 10)));

  for (const view of ['Week', 'Day', 'List'] as const) {
    await page.goto(calendarUrl(cal.id, 'month', day));
    await page.getByRole('button', { name: view, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`view=${view.toLowerCase()}`));
    await expect(chip(page, one)).toBeVisible();
    await expect(chip(page, series)).toBeVisible();
  }
});

test('the calendar filter hides and shows a calendar', async ({ page }) => {
  const a = await seedCalendar(page, { label: 'Alpha', color: '#dc2626' });
  const b = await seedCalendar(page, { label: 'Beta', color: '#16a34a' });
  const day = wednesday();
  const first = `A-${uniqueSlug('e')}`;
  const second = `B-${uniqueSlug('e')}`;
  await seedOne(page, a.id, first, day);
  await seedOne(page, b.id, second, day);
  await page.goto(`${calendarUrl(a.id, 'month', day)}&calendar=${b.id}`);
  await expect(chip(page, first)).toBeVisible();
  await expect(chip(page, second)).toBeVisible();
  const box = page.getByRole('checkbox', { name: new RegExp(a.name) });
  await box.uncheck();
  await expect(chip(page, first)).toHaveCount(0);
  await expect(chip(page, second)).toBeVisible();
  await box.check();
  await expect(chip(page, first)).toBeVisible();
});

test('the detail popover shows title, time, calendar and status', async ({ page }) => {
  const { cal, day, one } = await seedWeek(page);
  await page.goto(calendarUrl(cal.id, 'week', day));
  await chip(page, one).click();
  const detail = page.getByTestId('calendar-detail');
  await expect(detail).toContainText(one);
  await expect(detail).toContainText('10:00');
  await expect(detail).toContainText('Draft');
  await expect(page.getByRole('dialog', { name: 'Event details' })).toContainText(cal.name);
});

test('a click on an empty slot creates a draft through quick create', async ({ page }) => {
  const cal = await seedCalendar(page);
  const day = wednesday();
  await page.goto(calendarUrl(cal.id, 'week', day));
  await expect(page.getByText('10am', { exact: true })).toBeVisible();
  const { column, wedX, topOfTen } = await gridSize(page);
  await page.mouse.click(wedX - column, topOfTen + 10);
  const dialog = page.getByRole('dialog');
  await expect(dialog).toHaveCount(1);
  const title = `Created ${uniqueSlug('q')}`;
  await dialog.getByLabel('Title').fill(title);
  await dialog.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(chip(page, title)).toBeVisible();
  const events = await listEvents(page, cal.id);
  expect(events.map((e) => [e.title, e.status])).toEqual([[title, 'draft']]);
  expect(events[0]?.start_local).toBe(`${addDays(day, -1)}T10:00`);
});

test('the keyboard reaches an event; Escape returns to it; Move... moves it', async ({ page }) => {
  const { cal, day, one, oneOff } = await seedWeek(page);
  await page.goto(calendarUrl(cal.id, 'week', day));
  const target = chip(page, one);
  await expect(target).toBeVisible();
  await tabTo(page, target);
  await expect(target).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('calendar-detail')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('calendar-detail')).toHaveCount(0);
  await expect(target).toBeFocused();

  await page.keyboard.press('Enter');
  await page.getByRole('button', { name: 'Move…' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Move or resize' })).toBeVisible();
  const next = addDays(day, 1);
  await dialog.getByLabel('Start').fill(`${next}T14:00`);
  await dialog.getByLabel('End', { exact: true }).fill(`${next}T15:00`);
  await dialog.getByRole('button', { name: 'Move', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.reload();
  await expect(chip(page, one)).toContainText('2:00');
  const saved = await apiEvent(page, oneOff.id);
  expect([saved.start_local, saved.end_local]).toEqual([`${next}T14:00`, `${next}T15:00`]);
});

test('a pointer drag moves an event to another day and a resize changes its end', async ({
  page,
}) => {
  const { cal, day, one, oneOff } = await seedWeek(page);
  await page.goto(calendarUrl(cal.id, 'week', day));
  await expect(chip(page, one)).toBeVisible();
  const { column, hour } = await gridSize(page);
  await dragBy(page, chip(page, one), column, 0);
  const next = addDays(day, 1);
  await expect
    .poll(async () => (await apiEvent(page, oneOff.id)).start_local)
    .toBe(`${next}T10:00`);
  await page.reload();
  await expect(chip(page, one)).toBeVisible();

  await resizeBy(page, chip(page, one), hour);
  await expect.poll(async () => (await apiEvent(page, oneOff.id)).end_local).toBe(`${next}T12:00`);
  expect((await apiEvent(page, oneOff.id)).start_local).toBe(`${next}T10:00`);
});

test('dragging a series occurrence asks this one or all; this one moves only it', async ({
  page,
}) => {
  const { cal, day, series, weekly } = await seedWeek(page);
  await page.goto(calendarUrl(cal.id, 'week', day));
  const { column } = await gridSize(page);
  await dragBy(page, chip(page, series), column, 0);
  const prompt = page.getByRole('alertdialog');
  await expect(prompt).toContainText(series);
  await prompt.getByRole('button', { name: 'Only this occurrence' }).click();
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  const next = addDays(day, 1);
  await expect
    .poll(async () => (await apiEvent(page, weekly.id)).overrides.map((o) => o.kind))
    .toEqual(['moved']);
  const saved = await apiEvent(page, weekly.id);
  expect(saved.overrides[0]?.start_local).toBe(`${next}T13:00`);
  expect(saved.start_local).toBe(`${day}T13:00`);
});

test('a writer without publish cannot drag a published event, and is told why', async ({
  page,
  browser,
}) => {
  const { cal, day, one, oneOff } = await seedWeek(page);
  await publish(page, oneOff);
  const email = await seedWriter(page);

  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const writer = await context.newPage();
  guard(writer, problems);
  await login(writer, { email, password: 'changeme1' });
  await writer.goto(calendarUrl(cal.id, 'week', day));
  const target = chip(writer, one);
  await expect(target).toBeVisible();
  await expect(target.getByRole('img', { name: /Locked/ })).toBeVisible();
  const { column } = await gridSize(writer);
  await dragBy(writer, target, column, 0);
  await writer.waitForTimeout(500);
  expect((await apiEvent(page, oneOff.id)).start_local).toBe(`${day}T10:00`);
  await target.click();
  await expect(writer.getByTestId('calendar-detail')).toContainText(
    'Published: only a publisher can change it',
  );
  await expect(writer.getByRole('button', { name: 'Move…' })).toHaveCount(0);
  await context.close();
});

test.describe('the grid time zone', () => {
  test.use({ timezoneId: 'America/New_York' });

  test('calendar time shows Vienna 10:00; my time shows the New York hour', async ({ page }) => {
    const { cal, day, one } = await seedWeek(page);
    const hour = viennaTenInNewYork(day);
    expect(['4', '5']).toContain(hour);

    await page.goto(calendarUrl(cal.id, 'week', day));
    await expect(chip(page, one)).toContainText('10:00');
    await page.getByRole('button', { name: /^My time/ }).click();
    await expect(page.getByRole('button', { name: /^My time/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await expect(chip(page, one)).toContainText(`${hour}:00`);
    await expect(chip(page, one)).not.toContainText('10:00');
    await page.getByRole('button', { name: /^Calendar time/ }).click();
    await expect(chip(page, one)).toContainText('10:00');
  });
});

test('German console: the week starts on Monday and times are 24-hour', async ({
  page,
  context,
}) => {
  const { cal, day, series } = await seedWeek(page);
  const origin = new URL('/', page.url()).toString();
  await context.addCookies([{ name: 'locale', value: 'de', url: origin }]);
  try {
    await page.goto(calendarUrl(cal.id, 'week', day));
    const headers = page.getByText(/^(Mo|Di|Mi|Do|Fr|Sa|So)\.? \d+$/);
    await expect(headers.first()).toHaveText(/^Mo\.? \d+$/);
    await expect(chip(page, series)).toContainText('13:00');
    await page.goto(calendarUrl(cal.id, 'month', day));
    await expect(page.getByText(/^Mo\.?$/).first()).toBeVisible();
  } finally {
    await context.addCookies([{ name: 'locale', value: 'en', url: origin }]);
  }
});

test('the calendar chunk loads on the calendar and not on the other screens', async ({ page }) => {
  const loaded: string[] = [];
  page.on('request', (request) => {
    if (/FullCalendarGrid/.test(request.url())) loaded.push(request.url());
  });
  for (const path of ['/admin/events/calendars', '/admin/events/list']) {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
  }
  expect(loaded).toEqual([]);
  await page.goto('/admin/events/');
  await expect.poll(() => loaded.length).toBeGreaterThan(0);
});
