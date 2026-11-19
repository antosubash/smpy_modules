import { expect, test } from '@playwright/test';
import {
  calendarUrl,
  chip,
  guard,
  seedCalendar,
  seedEvent,
  wednesday,
} from './events-calendar-helpers';
import {
  enableReminders,
  followUrl,
  openPopover,
  resetReminders,
  seedPublished,
  setBaseUrl,
} from './events-reminders-helpers';
import { shoot } from './events-shots';
import { login } from './helpers';

/**
 * Reminders as a person uses them: the control in the calendar popover and the editor, the
 * Reminders page, changing and stopping, what is said when reminders cannot be delivered, the
 * German console and a phone. Delivery is the Python suite's and the smoke's (see the helpers).
 * Standalone: every test seeds its own calendar and events.
 */

test.use({ viewport: { width: 1440, height: 1000 } });
let problems: string[] = [];
const BASE = process.env.E2E_BASE_URL ?? '';

test.beforeEach(async ({ page }) => {
  problems = [];
  guard(page, problems);
  await login(page);
});
test.afterEach(async ({ page }) => {
  expect(problems).toEqual([]);
  await resetReminders(page);
});

test('while reminders cannot be delivered the popover says why in words and offers no dead control', async ({
  page,
  baseURL,
}) => {
  const seeded = await seedPublished(page, `Garden talk ${Date.now()}`);
  const detail = await openPopover(page, seeded);
  await expect(detail.getByTestId('remind-unavailable')).toContainText('public address is not set');
  await expect(detail.getByRole('button', { name: 'Remind me' })).toHaveCount(0);
  await page.goto('/admin/events/reminders');
  await expect(page.getByTestId('delivery-card')).toContainText('public address is not set');
  // The address is set, but mail is still the console backend, which only logs.
  await setBaseUrl(page, baseURL as string);
  await page.reload();
  await expect(page.getByTestId('delivery-card')).toContainText('console backend');
  await shoot(page, '02b-delivery-reason');
  const again = await openPopover(page, seeded);
  await expect(again.getByTestId('remind-unavailable')).toContainText('console backend');
});

test('follow from the popover, see it on the page, change the times, stop', async ({
  page,
  baseURL,
}) => {
  await enableReminders(page, baseURL as string);
  const seeded = await seedPublished(page, `Harvest supper ${Date.now()}`);
  const detail = await openPopover(page, seeded);
  const control = detail.getByRole('button', { name: 'Remind me' });
  await control.click();
  await expect(detail.getByRole('checkbox', { name: '1 hour before' })).toBeChecked();
  await detail.getByRole('checkbox', { name: '1 day before' }).click();
  await shoot(detail, '01-remind-me-control');
  await detail.getByRole('button', { name: 'Save' }).click();
  await expect(detail.getByRole('button', { name: 'Reminding: 1 h, 1 day' })).toBeVisible();

  await page.goto('/admin/events/reminders');
  const row = page.getByRole('row', { name: new RegExp(seeded.title) });
  await expect(row).toContainText('1 h, 1 day');
  await expect(row).toContainText(seeded.cal.name);
  await shoot(page, '02-reminders-page', { fullPage: true });

  await row.getByRole('button', { name: /Change reminder times for/ }).click();
  await row.getByRole('checkbox', { name: '1 day before' }).click();
  await row.getByRole('button', { name: 'Save' }).click();
  await expect(row).toContainText('1 h');
  await expect(row).not.toContainText('1 day');

  await row.getByRole('button', { name: /Remove reminders for/ }).click();
  await expect(row).toHaveCount(0);
  expect((await page.request.get(followUrl(seeded.id))).status()).toBe(200);
  expect(
    ((await (await page.request.get(followUrl(seeded.id))).json()) as { leads: number[] }).leads,
  ).toEqual([]);
});

test('the editor header has the control for a published event, and a draft has none', async ({
  page,
  baseURL,
}) => {
  await enableReminders(page, baseURL as string);
  const seeded = await seedPublished(page, `Editor follow ${Date.now()}`);
  await page.goto(`/admin/events/edit/${seeded.id}`);
  await page.getByRole('button', { name: 'Remind me' }).click();
  await page.getByRole('checkbox', { name: '15 minutes before' }).click();
  await page.getByRole('button', { name: 'Save' }).first().click();
  await expect(page.getByRole('button', { name: /Reminding: 15 min/ })).toBeVisible();
  const draftCal = await seedCalendar(page, { visibility: 'internal' });
  const day = wednesday();
  const draft = await seedEvent(page, {
    calendar: draftCal.id,
    title: 'Unpublished idea',
    start: `${day}T09:00`,
    end: `${day}T10:00`,
  });
  await page.goto(`/admin/events/edit/${draft.id}`);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Remind me' })).toHaveCount(0);
  await page.goto(calendarUrl(draftCal.id, 'week', day));
  await chip(page, 'Unpublished idea').click();
  await expect(
    page.getByTestId('calendar-detail').getByRole('button', { name: 'Remind me' }),
  ).toHaveCount(0);
});

test('calendar defaults are what the control preselects', async ({ page, baseURL }) => {
  await enableReminders(page, baseURL as string);
  const seeded = await seedPublished(page, `Defaults ${Date.now()}`);
  await page.goto('/admin/events/calendars');
  const row = page.getByRole('row', { name: new RegExp(seeded.cal.name) });
  await row.getByRole('button', { name: /^Edit/ }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('checkbox', { name: 'Use the site default' }).click();
  await dialog.getByRole('checkbox', { name: '15 minutes before' }).click();
  await dialog.getByRole('checkbox', { name: '1 week before' }).click();
  await shoot(dialog, '05-calendar-defaults');
  await dialog.getByRole('button', { name: 'Save' }).click();
  await expect(dialog).toBeHidden();
  const detail = await openPopover(page, seeded);
  await detail.getByRole('button', { name: 'Remind me' }).click();
  await expect(detail.getByRole('checkbox', { name: '15 minutes before' })).toBeChecked();
  await expect(detail.getByRole('checkbox', { name: '1 week before' })).toBeChecked();
  await expect(detail.getByRole('checkbox', { name: '1 hour before' })).not.toBeChecked();
});

test('German, and a phone', async ({ page, context, baseURL }) => {
  await enableReminders(page, baseURL as string);
  const seeded = await seedPublished(page, `Gartenfest ${Date.now()}`);
  await context.addCookies([{ name: 'locale', value: 'de', url: baseURL as string }]);
  try {
    const detail = await openPopover(page, seeded);
    await detail.getByRole('button', { name: 'Erinnern' }).click();
    await detail.getByRole('button', { name: 'Speichern' }).click();
    await page.goto('/admin/events/reminders');
    await expect(page.getByRole('heading', { name: 'Erinnerungen', level: 1 })).toBeVisible();
    await expect(page.getByText('Meine Erinnerungen')).toBeVisible();
    await shoot(page, '06-de', { fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await expect(page.getByText('Meine Erinnerungen')).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await shoot(page, '07-phone');
  } finally {
    await context.addCookies([{ name: 'locale', value: 'en', url: baseURL as string }]);
  }
  expect(BASE).toBeDefined();
});
