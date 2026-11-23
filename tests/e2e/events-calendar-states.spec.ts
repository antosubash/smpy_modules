import { expect, test } from '@playwright/test';

import {
  calendarUrl,
  chip,
  guard,
  seedWeek,
  seedWriter,
  viennaTenInNewYork,
} from './events-calendar-helpers';
import { login } from './helpers';

/**
 * The console calendar's edges on the production bundle: what a view-only user may start,
 * the phone layout, the Move dialog's keyboard path, the grid time zone and the German console. Standalone: each test seeds its own
 * calendar and events through the API.
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

test('a view-only user gets no create dialog from a click on an empty slot', async ({
  page,
  browser,
}) => {
  const { cal, day } = await seedWeek(page);
  const email = await seedWriter(page, ['events.view']);
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const viewer = await context.newPage();
  guard(viewer, problems);
  await login(viewer, { email, password: 'changeme1' });
  await viewer.goto(calendarUrl(cal.id, 'week', day));
  const slot = viewer.getByText('3pm', { exact: true });
  await expect(slot).toBeVisible();
  const box = (await slot.boundingBox()) ?? { x: 0, y: 0, width: 0, height: 0 };
  await viewer.mouse.click(box.x + 400, box.y + 4);
  await viewer.mouse.click(box.x + 600, box.y + 4);
  await expect(viewer.getByRole('dialog')).toHaveCount(0);
  await context.close();
});

for (const width of [390, 360]) {
  test(`the toolbar wraps at ${width} px wide: no sideways scroll, List reachable`, async ({
    page,
  }) => {
    const { cal, day } = await seedWeek(page);
    await page.setViewportSize({ width, height: 844 });
    for (const view of ['month', 'week', 'list'] as const) {
      await page.goto(calendarUrl(cal.id, view, day));
      await expect(page.getByTestId('calendar-title')).toBeVisible();
      await expect(page.getByRole('button', { name: 'List', exact: true })).toBeVisible();
      const fits = await page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      );
      expect(fits, `${view} at ${width}`).toBe(true);
    }
  });
}

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
