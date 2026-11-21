import { expect, type Page, request, test } from '@playwright/test';

import { guard, seedCalendar, seedEvent } from './events-calendar-helpers';
import { publishEvent } from './events-seed';
import { shoot } from './events-shots';
import { login } from './helpers';

/**
 * Private feed links on the production bundle. Standalone: the calendar and its events are seeded
 * through the API with unique names, and every page runs under the page-error / CSP guard.
 */
test.skip(process.env.E2E_BUNDLE !== '1', 'the nonce policy exists only in the bundle');
test.describe.configure({ mode: 'serial' });
test.use({ viewport: { width: 1280, height: 1000 } });

let problems: string[] = [];

test.beforeEach(async ({ page }) => {
  problems = [];
  guard(page, problems);
  await login(page);
});
test.afterEach(() => expect(problems).toEqual([]));

/** A calendar's row by its slug: the name is plain (screenshots), so a retry's calendar shares it. */
const calendarRow = (page: Page, slug: string) =>
  page.getByRole('row').filter({ has: page.getByRole('cell', { name: slug, exact: true }) });

async function openSubscribe(page: Page, cal: { name: string; slug: string }) {
  await page.goto('/admin/events/calendars');
  const row = calendarRow(page, cal.slug);
  await row.getByRole('button', { name: `Subscribe to ${cal.name}` }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Subscribe to this calendar' })).toBeVisible();
  return dialog;
}

/** Headers that legitimately differ between two requests: the time, and a per-request id. */
const VARIES = new Set(['date', 'x-request-id', 'x-correlation-id']);

const fetchFeed = async (url: string) => {
  const anonymous = await request.newContext(); // no cookies, no session
  const got = await anonymous.get(url, { maxRedirects: 0 });
  const headers = Object.fromEntries(
    Object.entries(got.headers())
      .filter(([name]) => !VARIES.has(name))
      .map(([name, value]) => [name, value.replace(/'nonce-[^']+'/g, "'nonce-X'")]), // per-request
  );
  const answer = {
    status: got.status(),
    type: got.headers()['content-type'],
    headers,
    body: await got.text(),
  };
  await anonymous.dispose();
  return answer;
};

/** Two answers that must be byte-identical, or the whole difference in one message. */
function sameAnswer(a: Awaited<ReturnType<typeof fetchFeed>>, b: typeof a) {
  const names = new Set([...Object.keys(a.headers), ...Object.keys(b.headers)]);
  const diff = [...names]
    .filter((n) => a.headers[n] !== b.headers[n])
    .map((n) => `${n}: ${a.headers[n]} | ${b.headers[n]}`);
  if (a.status !== b.status) diff.push(`status: ${a.status} | ${b.status}`);
  if (a.body !== b.body) diff.push(`body: ${a.body} | ${b.body}`);
  expect(diff, 'a revoked link must answer exactly as an invented one').toEqual([]);
}

test('a private link is shown once, serves the published events, and stops when revoked', async ({
  page,
}) => {
  const cal = await seedCalendar(page, {
    visibility: 'internal',
    label: 'Team calendar',
    plain: true,
  });
  const shown = await seedEvent(page, {
    calendar: cal.id,
    title: 'Spring concert',
    start: '2027-03-10T19:00',
    end: '2027-03-10T21:00',
  });
  await publishEvent(page, shown);
  await seedEvent(page, {
    calendar: cal.id,
    title: 'Draft rehearsal',
    start: '2027-03-11T19:00',
    end: '2027-03-11T21:00',
  });

  const dialog = await openSubscribe(page, cal);
  await dialog.getByLabel('Name for this link').fill('My phone');
  await dialog.getByRole('button', { name: 'Create a private link' }).click();
  await expect(dialog.getByText('You will not see this link again')).toBeVisible();
  const link = dialog.getByLabel('Private calendar link');
  const url = await link.inputValue();
  expect(url).toMatch(/\/events\/feed\/evf_[A-Za-z0-9_-]{43}\.ics$/);
  await shoot(page, '01-subscribe-dialog-new-link');

  // Anonymous: the feed holds the published event and not the draft.
  const feed = await fetchFeed(url);
  expect(feed.status).toBe(200);
  expect(feed.type).toContain('text/calendar');
  expect(feed.body).toContain('Spring concert');
  expect(feed.body).not.toContain('Draft rehearsal');

  // Close and reopen: the label is listed, the link is gone from the page.
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  const reopened = await openSubscribe(page, cal);
  await expect(reopened.getByText('My phone')).toBeVisible();
  await expect(reopened.getByLabel('Private calendar link')).toHaveCount(0);
  expect(await page.content()).not.toContain(url.split('/').pop()?.replace('.ics', '') ?? 'x');
  await shoot(page, '02-subscribe-dialog-list');

  // A manager also sees everyone's links.
  await reopened.getByRole('button', { name: 'Everyone’s links' }).click();
  await expect(reopened.getByText('My phone')).toBeVisible();

  // The revoke is held back, as a slow commit does on CI. While the confirm is pending the
  // Subscribe dialog is `aria-hidden`, so `reopened` matches nothing and "My phone is gone"
  // would pass at once: only the DELETE's answer and the closed confirm prove it happened.
  await page.route('**/api/events/feed-tokens/*', async (route) => {
    if (route.request().method() === 'DELETE') await new Promise((r) => setTimeout(r, 750));
    await route.continue();
  });
  const revoking = page.waitForResponse(
    (r) => r.request().method() === 'DELETE' && r.url().includes('/api/events/feed-tokens/'),
  );
  await reopened.getByRole('button', { name: 'Revoke My phone' }).click();
  await page.getByRole('alertdialog').getByRole('button', { name: 'Revoke', exact: true }).click();
  expect((await revoking).status()).toBe(204);
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(reopened.getByRole('heading', { name: 'Subscribe to this calendar' })).toBeVisible();
  await expect(reopened.getByText('My phone')).toHaveCount(0);

  // After revoking: exactly what an invented link gets.
  const revoked = await fetchFeed(url);
  const junk = Array.from(
    { length: 43 },
    () => 'abcdefghijklmnopqrstuvwxyz'[Math.floor(Math.random() * 26)],
  ).join('');
  const invented = await fetchFeed(url.replace(/evf_[A-Za-z0-9_-]{43}/, `evf_${junk}`));
  sameAnswer(revoked, invented);
  expect(revoked.status).toBe(404);
  expect(JSON.parse(revoked.body)).toEqual({ detail: 'Not found', code: 'not_found' });
});

test('the dialog speaks German and fits a phone', async ({ page, context }) => {
  const origin = new URL(page.url()).origin;
  await context.addCookies([{ name: 'locale', value: 'de', url: origin }]);
  const cal = await seedCalendar(page, {
    visibility: 'private',
    label: 'Office calendar',
    plain: true,
  });
  await page.goto('/admin/events/calendars');
  const row = calendarRow(page, cal.slug);
  await row.getByRole('button', { name: `${cal.name} abonnieren` }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Diesen Kalender abonnieren' })).toBeVisible();
  await expect(dialog.getByText('Privater Link', { exact: true })).toBeVisible();
  await context.addCookies([{ name: 'locale', value: 'en', url: origin }]);
});
