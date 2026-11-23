import { expect, type Page, test } from '@playwright/test';
import { guardPublic, type PublicSeed, seedPublic, XSS_TITLE } from './events-public-helpers';
import { shoot } from './events-shots';
import { login } from './helpers';

/**
 * The public events site on the production bundle, seen by an anonymous visitor. Standalone: the
 * data is seeded through the admin API in beforeAll (see events-public-helpers.ts) and every page
 * opened runs under a guard that fails on a page error, a console error or a CSP violation.
 */
test.skip(
  process.env.E2E_BUNDLE !== '1',
  'the nonce policy and the lazy chunk exist only in the bundle',
);
test.describe.configure({ mode: 'serial' });

let seed: PublicSeed;
let problems: string[] = [];

test.beforeAll(async ({ browser }) => {
  const admin = await browser.newPage();
  await login(admin);
  seed = await seedPublic(admin);
  await admin.close();
});

test.beforeEach(({ page }) => {
  problems = [];
  guardPublic(page, problems);
});
test.afterEach(() => expect(problems).toEqual([]));

const body = (page: Page) => page.locator('body');
const noSideScroll = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);

test('the list shows public published events only', async ({ page }) => {
  await page.goto('/events/');
  await expect(page.getByRole('heading', { level: 1, name: 'Events' })).toBeVisible();
  await expect(page.getByRole('link', { name: seed.conference.title })).toBeVisible();
  await expect(page.getByRole('link', { name: seed.weekly.title }).first()).toBeVisible();
  await expect(body(page)).not.toContainText(seed.draft.title);
  await expect(body(page)).not.toContainText(seed.hidden.title);
  await shoot(page, '01-index-list', { fullPage: true });
});

test('the calendar chunk loads only for the grid view, which is read-only', async ({ page }) => {
  const chunks: string[] = [];
  page.on('response', (r) => {
    if (!/FullCalendar|fullcalendar/i.test(r.url()) || !r.url().endsWith('.js')) return;
    chunks.push(r.url());
  });
  await page.goto('/events/');
  await expect(page.getByRole('link', { name: seed.conference.title })).toBeVisible();
  await page.waitForLoadState('networkidle');
  expect(chunks, 'the list page must not load the calendar').toEqual([]);

  await expect(page.getByRole('link', { name: 'Calendar', exact: true }).first()).toHaveAttribute(
    'href',
    /view=calendar/,
  );
  // The series starts in a later month than "today": open the grid on it, as a copied link would.
  // The grid shows its calendar's zone only while every calendar on it shares one; other specs
  // leave public calendars in other zones in this database, so this one opens its own calendar.
  await page.goto(`/events/c/${seed.pub.slug}?view=calendar&date=${seed.start}`);
  await expect(page.getByTestId('calendar-title')).not.toBeEmpty();
  await page.getByRole('button', { name: 'List', exact: true }).click();
  await expect(page.getByText(seed.weekly.title).first()).toBeVisible();
  // The grid opens in the calendar's zone, so it shows the hour the list shows (10:00 Vienna).
  await expect(page.getByRole('button', { name: /^Calendar time/ })).toContainText('Europe/Vienna');
  await expect(page.getByText(/10:00.*Writing circle/).first()).toBeVisible();
  expect(chunks.length).toBeGreaterThan(0);
  await expect(body(page)).not.toContainText(seed.draft.title);
  await expect(page.getByRole('button', { name: /Move/ })).toHaveCount(0);
  await shoot(page, '02-index-grid', { fullPage: true });
  await page.getByText(seed.weekly.title).first().click();
  await expect(page.getByRole('link', { name: 'View event' })).toBeVisible();
  await expect(body(page)).not.toContainText('Open in editor');
});

test('a calendar page narrows the list and offers the feed', async ({ page }) => {
  await page.goto(`/events/c/${seed.pub.slug}`);
  await expect(page.getByRole('heading', { level: 1, name: seed.pub.name })).toBeVisible();
  await expect(page.getByRole('link', { name: seed.conference.title })).toBeVisible();
  await expect(page.getByRole('link', { name: /Open in your calendar app/ })).toHaveAttribute(
    'href',
    /^webcal:\/\/.+\.ics$/,
  );
  await shoot(page, '03-calendar', { fullPage: true });
});

test('an event page: place, description, sub-events, JSON-LD with a nonce', async ({
  page,
  request,
}) => {
  await page.goto(`/events/${seed.conference.slug}`);
  await expect(page.getByRole('heading', { level: 1, name: seed.conference.title })).toBeVisible();
  await expect(page.getByText('Main hall')).toBeVisible();
  for (const talk of seed.talks) await expect(page.getByRole('link', { name: talk })).toBeVisible();
  await shoot(page, '04-event', { fullPage: true });

  const source = await (await request.get(`/events/${seed.conference.slug}`)).text();
  const scripts = source.match(/<script[^>]*application\/ld\+json[^>]*>[\s\S]*?<\/script>/g) ?? [];
  expect(scripts).toHaveLength(1);
  expect(scripts[0]).toMatch(/nonce="[\w-]+"/);
  const json = JSON.parse(scripts[0]?.replace(/^<script[^>]*>|<\/script>$/g, '') ?? '');
  expect(json['@type']).toBe('Event');
  expect(json.name).toBe(seed.conference.title);
});

test('lists in a description keep their bullets', async ({ page }) => {
  await page.goto(`/events/${seed.weekly.slug}`);
  const list = page.locator('ul', { hasText: 'A story to share' });
  await expect(list).toBeVisible();
  expect(await list.evaluate((el) => getComputedStyle(el).listStyleType)).toBe('disc');
  expect(
    await list.evaluate((el) => Number.parseFloat(getComputedStyle(el).paddingLeft)),
  ).toBeGreaterThan(8);
});

test('a talk names its parent', async ({ page }) => {
  await page.goto(`/events/${seed.conference.slug}`);
  await page.getByRole('link', { name: seed.talks[0] ?? '' }).click();
  await expect(page.getByRole('link', { name: `Part of ${seed.conference.title}` })).toBeVisible();
});

test('series: the bare page, a moved and a cancelled date, a skipped one is the 404', async ({
  page,
}) => {
  const { slug, dates } = seed.weekly;
  await page.goto(`/events/${slug}`);
  await expect(page.getByRole('heading', { name: 'Next dates' })).toBeVisible();
  await expect(page.locator(`a[href$="?date=${dates[0]}"]`)).toBeVisible();
  await expect(page.locator(`a[href$="?date=${dates[3]}"]`)).toHaveCount(0); // skipped

  await page.goto(`/events/${slug}?date=${dates[1]}`);
  await expect(page.getByText('Rescheduled from')).toBeVisible();
  await page.goto(`/events/${slug}?date=${dates[2]}`);
  await expect(page.getByRole('status')).toHaveText('This date has been cancelled');
  await shoot(page, '05-event-series-date', { fullPage: true });

  const skipped = await page.goto(`/events/${slug}?date=${dates[3]}`);
  expect(skipped?.status()).toBe(404);
});

test('German: the prefix, the language and the alternate links', async ({ page }) => {
  await page.goto(`/de/events/${seed.conference.deSlug}`);
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  await expect(
    page.getByRole('heading', { level: 1, name: seed.conference.deTitle }),
  ).toBeVisible();
  // The chrome speaks the page's language although the browser is English and has no cookie.
  await expect(page.getByRole('heading', { name: 'Wann' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Programmpunkte' })).toBeVisible();
  // The server writes the tags into the document; Inertia's <Head> repeats them (data-inertia).
  const origin = new URL(page.url()).origin;
  const en = `${origin}/events/${seed.conference.slug}`;
  const de = `${origin}/de/events/${seed.conference.deSlug}`;
  await expect(page.locator('link[rel=canonical]:not([data-inertia])')).toHaveAttribute('href', de);
  await expect(page.locator('link[hreflang=en]:not([data-inertia])')).toHaveAttribute('href', en);
  await expect(page.locator('link[hreflang=de]:not([data-inertia])')).toHaveAttribute('href', de);
  await expect(page.locator('link[hreflang=x-default]:not([data-inertia])')).toHaveAttribute(
    'href',
    en,
  );
  await shoot(page, '06-event-de', { fullPage: true });
  await page.goto('/de/events/');
  await expect(page.getByRole('link', { name: seed.conference.deTitle })).toBeVisible();
  await expect(page.locator('a[lang=en]').first()).toBeVisible(); // an event with no German text
});

test('the .ics links are calendar files', async ({ page, request }) => {
  await page.goto(`/events/${seed.conference.slug}`);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('link', { name: 'Add to calendar' }).click(),
  ]);
  expect(download.suggestedFilename()).toBe(`${seed.conference.slug}.ics`);
  for (const path of ['/events/calendar.ics', `/events/${seed.weekly.slug}.ics`]) {
    const res = await request.get(path);
    expect(res.headers()['content-type']).toContain('text/calendar');
    const text = await res.text();
    expect(text).toContain('BEGIN:VCALENDAR');
    expect(text).not.toContain(seed.draft.title);
    expect(text).not.toContain(seed.hidden.title);
  }
  const series = await (await request.get(`/events/${seed.weekly.slug}.ics`)).text();
  for (const needle of [
    'RRULE:',
    'EXDATE;TZID=Europe/Vienna',
    'RECURRENCE-ID;TZID=Europe/Vienna',
    'STATUS:CANCELLED',
  ]) {
    expect(series).toContain(needle);
  }
});

test('a draft, an internal event and an internal calendar are the module 404', async ({ page }) => {
  const missing = await page.goto('/events/no-such-event-at-all');
  expect(missing?.status()).toBe(404);
  const heading = await page.getByRole('heading', { level: 1 }).first().innerText();
  await shoot(page, '07-not-found', { fullPage: true });
  for (const path of [`/events/${seed.draft.slug}`, `/events/${seed.hidden.slug}`]) {
    const response = await page.goto(path);
    expect(response?.status(), path).toBe(404);
    await expect(page.getByRole('heading', { level: 1 }).first()).toHaveText(heading);
    await expect(body(page)).not.toContainText(seed.draft.title);
    await expect(body(page)).not.toContainText(seed.hidden.title);
  }
  const calendar = await page.goto(`/events/c/${seed.internal.slug}`);
  expect(calendar?.status()).toBe(404);
});

test('an old slug redirects, event and calendar', async ({ page }) => {
  const event = await page.goto(`/events/${seed.renamed.oldSlug}`);
  expect(event?.request().redirectedFrom()).not.toBeNull();
  await expect(page).toHaveURL(new RegExp(`/events/${seed.renamed.newSlug}$`));
  await expect(page.getByRole('heading', { level: 1, name: seed.renamed.title })).toBeVisible();
  const calendar = await page.goto(`/events/c/${seed.oldCalendarSlug}`);
  expect(calendar?.request().redirectedFrom()).not.toBeNull();
  await expect(page).toHaveURL(new RegExp(`/events/c/${seed.newCalendarSlug}$`));
});

test('dark scheme: the pages stay legible', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto(`/events/${seed.conference.slug}`);
  await expect(page.getByRole('heading', { level: 1, name: seed.conference.title })).toBeVisible();
  await shoot(page, '08-dark-event', { fullPage: true });
  await page.goto('/events/');
  await expect(page.getByRole('link', { name: seed.conference.title })).toBeVisible();
  await shoot(page, '08-dark-index', { fullPage: true });
});

test('390 px wide: nothing scrolls sideways', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of [
    '/events/',
    `/events/c/${seed.pub.slug}`,
    `/events/${seed.conference.slug}`,
    `/events/${seed.weekly.slug}`,
    '/events/?view=calendar',
  ]) {
    await page.goto(path);
    await page.waitForLoadState('networkidle');
    expect(await noSideScroll(page), path).toBe(true);
  }
  await page.goto('/events/');
  await shoot(page, '09-phone', { fullPage: true });
});

test('markup in a title is text', async ({ page, browser }) => {
  const admin = await browser.newPage();
  await login(admin);
  const slug = await seed.xssEvent(admin);
  await admin.close();
  await page.goto(`/events/${slug}`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(XSS_TITLE);
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  await page.goto('/events/');
  await expect(page.getByRole('link', { name: /onerror=alert/ })).toBeVisible();
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
});
