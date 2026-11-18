import { expect, test } from '@playwright/test';

import { calendarUrl, guard, seedWeek, seedWriter } from './events-calendar-helpers';
import { login } from './helpers';

/**
 * The console calendar's edges on the production bundle: what a view-only user may start,
 * the phone layout and the Move dialog's keyboard path. Standalone: each test seeds its own
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
