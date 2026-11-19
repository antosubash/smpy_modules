import { expect, type Page } from '@playwright/test';

import {
  calendarUrl,
  chip,
  seedCalendar,
  seedEvent,
  seedWriter,
  wednesday,
} from './events-calendar-helpers';
import { publishEvent } from './events-seed';
import { login, moduleCsrfHeader } from './helpers';

/** Seeds and settings for the reminders specs. Everything goes through the API with unique
 *  names, so each spec file stands alone. Delivery itself (the beat, the mail) is covered by the
 *  Python suite and scripts/bg_tasks_smoke.py: this host runs tasks eagerly on the console mail
 *  transport, and the plan has no dev-only tick hook. */

const SETTINGS = '/api/settings/modules';
const CSRF_VIEW = '/admin/events/reminders';
export const REMINDERS = '/api/events/reminders';

/** A mail transport that "delivers" (nothing listens: no tick runs here) and a public address,
 *  which is all `availability` asks of the web process. Put back by `resetReminders`. */
export async function enableReminders(page: Page, baseURL: string): Promise<void> {
  const headers = await moduleCsrfHeader(page, CSRF_VIEW);
  const host = await page.request.put(`${SETTINGS}/host`, {
    headers,
    data: { public_base_url: baseURL },
  });
  expect(host.ok(), await host.text()).toBeTruthy();
  const mail = await page.request.put(`${SETTINGS}/mail`, {
    headers,
    data: { backend: 'smtp', smtp_host: '127.0.0.1', smtp_port: 9, smtp_tls: false },
  });
  expect(mail.ok(), await mail.text()).toBeTruthy();
  await expect
    .poll(async () => JSON.stringify(await (await page.request.get(`${REMINDERS}/status`)).json()))
    .toContain('"available":true');
}

/** Only the public address (mail stays the console backend). */
export async function setBaseUrl(page: Page, baseURL: string): Promise<void> {
  const res = await page.request.put(`${SETTINGS}/host`, {
    headers: await moduleCsrfHeader(page, CSRF_VIEW),
    data: { public_base_url: baseURL },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
}

export async function resetReminders(page: Page): Promise<void> {
  const headers = await moduleCsrfHeader(page, CSRF_VIEW);
  await page.request.delete(`${SETTINGS}/host/public_base_url`, { headers });
  for (const field of ['backend', 'smtp_host', 'smtp_port', 'smtp_tls']) {
    await page.request.delete(`${SETTINGS}/mail/${field}`, { headers });
  }
}

export type Published = {
  cal: { id: string; name: string };
  id: string;
  title: string;
  day: string;
};

/** A published one-hour event three weeks out, in its own internal calendar. */
export async function seedPublished(
  page: Page,
  title: string,
  visibility: 'internal' | 'private' = 'internal',
  calendarName = 'Town events',
) {
  // A realistic name (the screenshots show it); the event's title tells the tests apart.
  const cal = await seedCalendar(page, { visibility, label: calendarName, plain: true });
  const day = wednesday();
  const event = await seedEvent(page, {
    calendar: cal.id,
    title,
    start: `${day}T09:00`,
    end: `${day}T10:00`,
  });
  await publishEvent(page, event);
  return { cal, id: event.id, title, day } satisfies Published;
}

/** Open the event's popover on the console calendar. */
export async function openPopover(page: Page, seeded: Published) {
  await page.goto(calendarUrl(seeded.cal.id, 'week', seeded.day));
  await chip(page, seeded.title).click();
  return page.getByTestId('calendar-detail');
}

/** A second signed-in person, in a context of their own: `events.view` only. */
export async function readerPage(browser: import('@playwright/test').Browser, baseURL: string) {
  const admin = await browser.newContext({ baseURL });
  const adminPage = await admin.newPage();
  await login(adminPage);
  const email = await seedWriter(adminPage, ['events.view']);
  await admin.close();
  const context = await browser.newContext({ baseURL });
  const page = await context.newPage();
  await login(page, { email, password: 'changeme1' });
  return { context, page, email };
}

export const followUrl = (id: string) => `/api/events/events/${id}/follow`;
export const csrf = (page: Page) => moduleCsrfHeader(page, CSRF_VIEW);
