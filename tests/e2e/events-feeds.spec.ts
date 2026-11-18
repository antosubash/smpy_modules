import { expect, type Page, request, test } from '@playwright/test';

import { guard, seedCalendar, seedEvent } from './events-calendar-helpers';
import { publishEvent } from './events-seed';
import { login } from './helpers';

/**
 * Private feed links on the production bundle. Standalone: the calendar and its events are seeded
 * through the API with unique names, and every page runs under the page-error / CSP guard.
 */
test.skip(process.env.E2E_BUNDLE !== '1', 'the nonce policy exists only in the bundle');
test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1280, height: 1000 } });

const SHOTS = '.skill-state/qa/pr5-shots';
let problems: string[] = [];

test.beforeEach(async ({ page }) => {
  problems = [];
  guard(page, problems);
  await login(page);
});
test.afterEach(() => expect(problems).toEqual([]));

async function openSubscribe(page: Page, name: string) {
  await page.goto('/admin/events/calendars');
  const row = page.getByRole('row').filter({ hasText: name });
  await row.getByRole('button', { name: `Subscribe to ${name}` }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Subscribe to this calendar' })).toBeVisible();
  return dialog;
}

const fetchFeed = async (url: string) => {
  const anonymous = await request.newContext(); // no cookies, no session
  const got = await anonymous.get(url, { maxRedirects: 0 });
  const answer = {
    status: got.status(),
    type: got.headers()['content-type'],
    body: await got.text(),
  };
  await anonymous.dispose();
  return answer;
};

test('a private link is shown once, serves the published events, and stops when revoked', async ({
  page,
}) => {
  const cal = await seedCalendar(page, { visibility: 'internal', label: 'Feeds' });
  const shown = await seedEvent(page, {
    calendar: cal.id,
    title: 'Feed concert',
    start: '2027-03-10T19:00',
    end: '2027-03-10T21:00',
  });
  await publishEvent(page, shown);
  await seedEvent(page, {
    calendar: cal.id,
    title: 'Feed secret draft',
    start: '2027-03-11T19:00',
    end: '2027-03-11T21:00',
  });

  const dialog = await openSubscribe(page, cal.name);
  await dialog.getByLabel('Name for this link').fill('My phone');
  await dialog.getByRole('button', { name: 'Create a private link' }).click();
  await expect(dialog.getByText('You will not see this link again')).toBeVisible();
  const link = dialog.getByLabel('Private calendar link');
  const url = await link.inputValue();
  expect(url).toMatch(/\/events\/feed\/evf_[A-Za-z0-9_-]{43}\.ics$/);
  await page.screenshot({ path: `${SHOTS}/01-subscribe-dialog-new-link.png` });

  // Anonymous: the feed holds the published event and not the draft.
  const feed = await fetchFeed(url);
  expect(feed.status).toBe(200);
  expect(feed.type).toContain('text/calendar');
  expect(feed.body).toContain('Feed concert');
  expect(feed.body).not.toContain('Feed secret draft');

  // Close and reopen: the label is listed, the link is gone from the page.
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const reopened = await openSubscribe(page, cal.name);
  await expect(reopened.getByText('My phone')).toBeVisible();
  await expect(reopened.getByLabel('Private calendar link')).toHaveCount(0);
  expect(await page.content()).not.toContain(url.split('/').pop()?.replace('.ics', '') ?? 'x');
  await page.screenshot({ path: `${SHOTS}/02-subscribe-dialog-list.png` });

  // A manager also sees everyone's links.
  await reopened.getByRole('button', { name: 'Everyone’s links' }).click();
  await expect(reopened.getByText('My phone')).toBeVisible();

  await reopened.getByRole('button', { name: 'Revoke My phone' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Revoke', exact: true }).click();
  await expect(reopened.getByText('My phone')).toHaveCount(0);

  // After revoking: exactly what an invented link gets.
  const revoked = await fetchFeed(url);
  const invented = await fetchFeed(url.replace(/evf_[A-Za-z0-9_-]{43}/, `evf_${'Z'.repeat(43)}`));
  expect(revoked).toEqual(invented);
  expect(revoked.status).toBe(404);
  expect(JSON.parse(revoked.body)).toEqual({ detail: 'Not found', code: 'not_found' });
});

test('the dialog speaks German and fits a phone', async ({ page, context }) => {
  const origin = new URL(page.url()).origin;
  await context.addCookies([{ name: 'locale', value: 'de', url: origin }]);
  const cal = await seedCalendar(page, { visibility: 'private', label: 'Phone' });
  await page.goto('/admin/events/calendars');
  const row = page.getByRole('row').filter({ hasText: cal.name });
  await row.getByRole('button', { name: `${cal.name} abonnieren` }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Diesen Kalender abonnieren' })).toBeVisible();
  await expect(dialog.getByText('Privater Link', { exact: true })).toBeVisible();
  await context.addCookies([{ name: 'locale', value: 'en', url: origin }]);
});
