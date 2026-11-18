import { type Browser, expect, type Page, test } from '@playwright/test';
import {
  type BlocksSeed,
  blockPage,
  calendarBlock,
  seedBlocks,
  setVisibility,
  unpublishEvent,
  upcoming,
} from './events-blocks-helpers';
import { guardPublic } from './events-public-helpers';
import { shoot } from './events-shots';
import { login } from './helpers';

/**
 * The events blocks on public pagebuilder pages, on the production bundle, seen by an anonymous
 * visitor. Standalone: the data is seeded through the admin API in beforeAll, the pages are
 * created through the pagebuilder API (the suite seeds blocks rather than dragging them), and
 * every page runs under the page / console / CSP guard.
 */
test.skip(
  process.env.E2E_BUNDLE !== '1',
  'the nonce policy and the lazy chunk exist only in the bundle',
);
test.describe.configure({ mode: 'serial' });

let seed: BlocksSeed;
let both: { slug: string; id: number };
let listOnly: { slug: string; id: number };
let market: { slug: string; id: number };
let problems: string[] = [];

test.beforeAll(async ({ browser }) => {
  const admin = await browser.newPage();
  await login(admin);
  seed = await seedBlocks(admin);
  const chosen = [{ slug: seed.community.slug }];
  both = await blockPage(
    admin,
    [upcoming({ layout: 'cards' }), calendarBlock({ calendars: chosen })],
    { german: true },
  );
  listOnly = await blockPage(admin, [upcoming({ heading: 'Next up', count: 3 })]);
  market = await blockPage(admin, [
    upcoming({ calendars: [{ slug: seed.market.slug }], heading: 'At the market' }),
    calendarBlock({ calendars: [{ slug: seed.market.slug }] }),
  ]);
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
const list = (page: Page) => page.getByRole('region', { name: 'Upcoming events' });

test('the editor offers both blocks, translated, and only public calendars', async ({ page }) => {
  await login(page);
  await page.goto(`/pagebuilder/${both.id}/edit`);
  await expect(page.getByText('Upcoming events', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Events calendar', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Events', { exact: true }).first()).toBeVisible(); // the group
  await page.getByRole('navigation').getByText('Outline', { exact: true }).click();
  await page.getByRole('button', { name: 'Upcoming events' }).last().click();
  await expect(page.getByText('Number of events').locator('visible=true').first()).toBeVisible();
  await page.getByRole('button', { name: 'Add item' }).locator('visible=true').first().click();
  // A row is collapsed to its summary, which is text and not a catalogue key.
  const row = page.getByText('Calendar', { exact: true }).locator('visible=true').last();
  await expect(page.getByText('events.blocks.fields.calendar')).toHaveCount(0);
  await row.click();
  const picker = page
    .getByRole('combobox', { name: 'Calendar', exact: true })
    .locator('visible=true')
    .first();
  await expect(picker).toBeVisible();
  const labels = await picker
    .locator('option')
    .evaluateAll((els) => els.map((el) => (el as HTMLOptionElement).label));
  expect(labels).toContain('All public calendars');
  expect(labels).toContain(seed.community.name);
  expect(labels).toContain(seed.library.name);
  expect(labels).not.toContain(seed.staff.name);
  await shoot(page, '01-editor-upcoming-block');
});

test('the list shows public published events in the event clock, and nothing hidden', async ({
  page,
}) => {
  await page.goto(`/p/${both.slug}`);
  const events = list(page);
  await expect(events.getByRole('link', { name: 'Writing circle' }).first()).toBeVisible();
  await expect(events.getByRole('link', { name: 'Poetry night' })).toBeVisible();
  await expect(events.getByRole('link', { name: 'Transatlantic call' })).toBeVisible();
  await expect(events).toContainText('Seminar room');
  await expect(events).toContainText('Cancelled');
  // Each on its own clock: 10:00 in Vienna, 14:00 in New York.
  await expect(
    events
      .locator('time')
      .filter({ hasText: /10:00|10:00 AM/ })
      .first(),
  ).toBeVisible();
  await expect(
    events
      .locator('time')
      .filter({ hasText: /14:00|2:00 PM/ })
      .first(),
  ).toBeVisible();
  for (const hidden of [seed.draft.title, seed.hidden.title]) {
    await expect(body(page)).not.toContainText(hidden);
  }
  const href = await events.getByRole('link', { name: 'Poetry night' }).getAttribute('href');
  expect(href).toMatch(/^\/events\/poetry-night/);
  await expect(
    page.locator('[data-events-calendar]').getByTestId('calendar-title'),
  ).not.toBeEmpty();
  await expect(
    page.locator('[data-events-calendar]').getByText('Writing circle').first(),
  ).toBeVisible();
  await shoot(page, '02-public-upcoming', { fullPage: true });
});

test('the calendar block is read-only and shows only the chosen calendar', async ({ page }) => {
  const chunks: string[] = [];
  page.on('response', (r) => {
    if (/FullCalendar|fullcalendar/i.test(r.url()) && r.url().endsWith('.js')) chunks.push(r.url());
  });
  await page.goto(`/p/${listOnly.slug}`);
  await expect(page.getByRole('region', { name: 'Next up' })).toBeVisible();
  await page.waitForLoadState('networkidle');
  expect(chunks, 'a page without a calendar block must not load the calendar').toEqual([]);

  await page.goto(`/p/${both.slug}`);
  const grid = page.locator('[data-events-calendar]');
  await expect(grid.getByTestId('calendar-title')).not.toBeEmpty();
  expect(chunks.length).toBeGreaterThan(0);
  await expect(grid.getByRole('button', { name: /new event|create/i })).toHaveCount(0);
  await expect(grid.getByText(/Library programme/)).toHaveCount(0); // not a chosen calendar
  await expect(grid.getByText(seed.community.name)).toBeVisible(); // the filter names the one
  await page.getByRole('button', { name: 'List', exact: true }).click();
  await expect(grid.getByText('Writing circle').first()).toBeVisible();
  await expect(grid).not.toContainText('Poetry night');
  await shoot(page, '03-public-calendar-block', { fullPage: true });
});

test('the German page reads in German', async ({ page }) => {
  await page.goto(`/de/p/${both.slug}`);
  await expect(page.locator('html')).toHaveAttribute('lang', 'de');
  const events = page.getByRole('region', { name: 'Upcoming events' });
  await expect(events.getByRole('link', { name: seed.writing.deTitle }).first()).toBeVisible();
  await expect(events).toContainText('Abgesagt');
  await expect(events.getByRole('link', { name: 'Poetry night' })).toHaveAttribute('lang', 'en');
  await expect(events.getByRole('link', { name: seed.writing.deTitle }).first()).toHaveAttribute(
    'href',
    /^\/de\/events\//,
  );
  await shoot(page, '04-public-de', { fullPage: true });
});

test('390 px wide: nothing scrolls sideways', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/p/${both.slug}`);
  await expect(list(page).getByRole('link', { name: 'Poetry night' })).toBeVisible();
  await expect(
    page.locator('[data-events-calendar]').getByTestId('calendar-title'),
  ).not.toBeEmpty();
  expect(await noSideScroll(page)).toBe(true);
  await shoot(page, '05-phone', { fullPage: true });
});

test('no event id appears in the document, the page data or any response', async ({ page }) => {
  const seen: string[] = [];
  page.on('response', async (r) => {
    if (r.url().includes('/api/events/public/')) seen.push(await r.text());
  });
  await page.goto(`/p/${both.slug}`);
  await expect(list(page).getByRole('link', { name: 'Poetry night' })).toBeVisible();
  await expect(
    page.locator('[data-events-calendar]').getByTestId('calendar-title'),
  ).not.toBeEmpty();
  await page.waitForLoadState('networkidle');
  const document = await (await page.request.get(`/p/${both.slug}`)).text();
  expect(seen.length).toBeGreaterThan(1);
  for (const text of [document, await page.content(), ...seen]) {
    for (const id of seed.ids) {
      expect(text).not.toContain(id);
      expect(text).not.toContain(id.replaceAll('-', ''));
    }
  }
});

/** A visitor who has not seen the page yet (no HTTP cache): the answer a block's route gives now.
 *  A repeat visitor may see the previous answer for the route's short cache (60 s at most). */
async function freshVisitor(browser: Browser, url: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  guardPublic(page, problems);
  await page.goto(url);
  return { page, close: () => context.close() };
}

test('unpublishing an event removes it on the next load: nothing is stored in the page', async ({
  page,
  browser,
}) => {
  const url = `/p/${listOnly.slug}`;
  await page.goto(url);
  await expect(
    page.getByRole('region', { name: 'Next up' }).getByRole('link', { name: 'Poetry night' }),
  ).toHaveCount(1);
  const admin = await browser.newPage();
  await login(admin);
  await unpublishEvent(admin, seed.poetry);
  await admin.close();
  const next = await freshVisitor(browser, url);
  await expect(next.page.getByRole('region', { name: 'Next up' })).toBeVisible();
  await expect(next.page.locator('body')).not.toContainText('Poetry night');
  await next.close();
});

test('a calendar made internal empties its blocks without an error', async ({ page, browser }) => {
  const url = `/p/${market.slug}`;
  await page.goto(url);
  await expect(page.getByRole('region', { name: 'At the market' })).toContainText(seed.stall.title);
  await expect(page.locator('[data-events-calendar]')).toBeVisible();
  const admin = await browser.newPage();
  await login(admin);
  await setVisibility(admin, seed.market.id, 'internal');
  await admin.close();
  const next = await freshVisitor(browser, url);
  await expect(next.page.getByRole('heading', { name: 'What is on' })).toBeVisible();
  await expect(next.page.getByRole('region', { name: 'At the market' })).toHaveCount(0);
  await expect(next.page.locator('[data-events-calendar]')).toHaveCount(0);
  for (const text of [seed.stall.title, seed.market.name, seed.market.slug]) {
    await expect(next.page.locator('body')).not.toContainText(text);
  }
  await next.close();
});
