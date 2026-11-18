import { expect, type Page, test } from '@playwright/test';

import { postCalendar, postEvent } from './events-seed';
import { login, moduleCsrfHeader, uniqueSlug } from './helpers';

/** Seeding and guards for events-editor.spec.ts. Everything goes through the API. */

const VIEW = '/admin/events/list';

export type Seeded = { id: string; revision: number; calendar_id: string };

/** Collect page errors and CSP violations of `page` into `problems`. */
export function watch(page: Page, problems: string[]) {
  page.on('pageerror', (error) => problems.push(String(error)));
  page.on('console', (message) => {
    if (message.text().includes('Content Security Policy')) problems.push(message.text());
  });
}

export async function apiCalendar(
  page: Page,
  name: string,
  visibility: 'private' | 'internal' | 'public' = 'private',
): Promise<string> {
  return (await postCalendar(page, { name, visibility })).id;
}

export function apiEvent(
  page: Page,
  calendarId: string,
  title: string,
  extra: { start?: string; end?: string; rrule?: string; venue?: string } = {},
): Promise<Seeded> {
  return postEvent(page, {
    calendar: calendarId,
    title,
    start: extra.start ?? '2027-01-12T10:00',
    end: extra.end ?? '2027-01-12T11:00',
    rrule: extra.rrule,
    venue: extra.venue,
    description: '',
  });
}

export async function apiGet(page: Page, id: string) {
  const got = await page.request.get(`/api/events/events/${id}`);
  expect(got.status(), await got.text()).toBe(200);
  return (await got.json()) as {
    revision: number;
    status: string;
    starts_at: string;
    ends_at: string;
    venue_name: string | null;
    texts: Record<string, { title: string; description: string }>;
    overrides: { kind: string; original_start: string }[];
  };
}

/** A workflow action (`submit`, `approve`, …) on the event's current revision. */
export async function apiAct(page: Page, id: string, action: string) {
  const { revision } = await apiGet(page, id);
  const done = await page.request.post(`/api/events/events/${id}/${action}`, {
    headers: await moduleCsrfHeader(page, VIEW),
    data: { expected_revision: revision },
  });
  expect(done.status(), await done.text()).toBeLessThan(300);
}

export async function apiPublished(page: Page, calendarId: string, title: string) {
  const event = await apiEvent(page, calendarId, title);
  await apiAct(page, event.id, 'submit');
  await apiAct(page, event.id, 'approve');
  return event;
}

export async function apiOverride(
  page: Page,
  id: string,
  original_start: string,
  kind: 'skipped' | 'cancelled',
) {
  const { revision } = await apiGet(page, id);
  const done = await page.request.post(`/api/events/events/${id}/overrides`, {
    headers: await moduleCsrfHeader(page, VIEW),
    data: { expected_revision: revision, original_start, kind },
  });
  expect(done.status(), await done.text()).toBeLessThan(300);
}

export const freshCalendar = (page: Page) => apiCalendar(page, `Cal ${uniqueSlug('c')}`);

/** A user holding only `events.view`; returns the address (the password is `changeme1`). */
export async function apiViewer(page: Page, sfx: string): Promise<string> {
  const email = `events-view-${sfx}@example.com`;
  const json = { 'content-type': 'application/json' };
  const created = await page.request.post('/api/users/admin', {
    headers: json,
    data: { email, password: 'changeme1', role_names: [] },
  });
  expect(created.status(), await created.text()).toBe(201);
  const users = (await (await page.request.get('/api/users/admin?per_page=100')).json()) as {
    id: string;
    email: string;
  }[];
  const id = users.find((u) => u.email === email)?.id;
  const granted = await page.request.put(`/api/permissions/users/${id}`, {
    headers: json,
    data: { permissions: ['events.view'] },
  });
  expect(granted.status(), await granted.text()).toBe(200);
  return email;
}

export const LIST = '/admin/events/list';
export const NEW_YORK = 'America/New_York';
export const edit = (id: string) => `/admin/events/edit/${id}`;
export const row = (page: Page, text: string) => page.getByRole('row').filter({ hasText: text });
export const save = (page: Page) => page.getByRole('button', { name: 'Save', exact: true });
export const field = (page: Page, name: string) => page.getByLabel(name, { exact: true });

/**
 * Registers, for the spec file calling it: a New York browser clock (so a time
 * shifted into the browser's zone shows), a sign-in per test, and a failure on
 * any page error or CSP violation. Returns the list extra pages report into.
 */
export function setupSpec(): string[] {
  const problems: string[] = [];
  test.use({ timezoneId: NEW_YORK });
  test.beforeEach(async ({ page }) => {
    problems.length = 0;
    watch(page, problems);
    await login(page);
  });
  test.afterEach(() => {
    expect(problems).toEqual([]);
  });
  return problems;
}
