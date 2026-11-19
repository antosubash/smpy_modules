import { expect, test } from '@playwright/test';

import { guard } from './events-calendar-helpers';
import {
  csrf,
  enableReminders,
  followUrl,
  openPopover,
  readerPage,
  resetReminders,
  seedPublished,
} from './events-reminders-helpers';
import { shoot } from './events-shots';
import { login } from './helpers';

/**
 * Follows are one person's own. A second user can neither see nor touch the first's (by a
 * follow id they could never have learned, the answer is the missing-id 404), and a user who
 * loses access sees an opaque row and can remove it. Standalone: seeds its own people and data.
 */

test.use({ viewport: { width: 1440, height: 1000 } });
let problems: string[] = [];

test.beforeEach(async ({ page }) => {
  problems = [];
  guard(page, problems);
  await login(page);
});
test.afterEach(async ({ page }) => {
  expect(problems).toEqual([]);
  await resetReminders(page);
});

const mine = async (page: import('@playwright/test').Page) =>
  (await (await page.request.get('/api/events/reminders/mine')).json()) as {
    items: { follow_id: string; hidden: boolean; title: string | null }[];
    total: number;
    hidden: number;
  };

test("a second user cannot see or touch the first user's follows", async ({
  page,
  browser,
  baseURL,
}) => {
  await enableReminders(page, baseURL as string);
  const seeded = await seedPublished(page, 'Book club');
  const put = await page.request.put(followUrl(seeded.id), {
    headers: await csrf(page),
    data: { leads: [60] },
  });
  expect(put.status(), await put.text()).toBe(200);
  const adminFollow = (await mine(page)).items[0].follow_id;

  const reader = await readerPage(browser, baseURL as string);
  try {
    expect(await mine(reader.page)).toMatchObject({ total: 0, items: [] });
    const headers = await csrf(reader.page);
    const theirs = await reader.page.request.delete(
      `/api/events/reminders/follows/${adminFollow}`,
      { headers },
    );
    const missing = await reader.page.request.delete(
      '/api/events/reminders/follows/00000000-0000-4000-8000-000000000001',
      { headers },
    );
    expect(theirs.status()).toBe(404);
    expect(await theirs.text()).toBe(await missing.text());
    await reader.page.goto('/admin/events/reminders');
    await expect(reader.page.getByText('You are not following any events')).toBeVisible();
    await expect(reader.page.getByText(seeded.title)).toHaveCount(0);
  } finally {
    await reader.context.close();
  }
  expect((await mine(page)).total).toBe(1); // untouched
});

test('a user who loses access sees an opaque row and can remove it', async ({
  page,
  browser,
  baseURL,
}) => {
  await enableReminders(page, baseURL as string);
  const seeded = await seedPublished(page, 'Board retreat');
  const reader = await readerPage(browser, baseURL as string);
  try {
    const put = await reader.page.request.put(followUrl(seeded.id), {
      headers: await csrf(reader.page),
      data: { leads: [60] },
    });
    expect(put.status(), await put.text()).toBe(200);
    await reader.page.goto('/admin/events/reminders');
    await expect(reader.page.getByRole('row', { name: new RegExp(seeded.title) })).toBeVisible();
    // The calendar goes private: the follow stays, but nothing about the event is theirs to read.
    const hide = await page.request.put(`/api/events/calendars/${seeded.cal.id}/visibility`, {
      headers: await csrf(page),
      data: { visibility: 'private' },
    });
    expect(hide.status(), await hide.text()).toBe(200);
    await reader.page.reload();
    const opaque = reader.page.getByTestId('hidden-follow');
    await expect(opaque).toContainText('An event you can no longer see');
    await expect(reader.page.locator('body')).not.toContainText(seeded.title);
    await shoot(reader.page, '03-hidden-follow-row', { fullPage: true });
    await opaque.getByRole('button', { name: /Remove reminders for/ }).click();
    await expect(reader.page.getByText('You are not following any events')).toBeVisible();
    expect((await mine(reader.page)).total).toBe(0);
  } finally {
    await reader.context.close();
  }
});

test('a user the worker cannot verify is told, and the follow is kept', async ({
  page,
  baseURL,
}) => {
  // A single-tenant host cannot make an account whose live rights the worker cannot read (that
  // needs a membership role, upstream #1005): the API side is the Python suite's. Here the
  // server's answer is fixed, and what the person sees is what is checked.
  await enableReminders(page, baseURL as string);
  const seeded = await seedPublished(page, 'Wine tasting');
  await page.route('**/api/events/events/*/follow', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    return route.fulfill({
      json: {
        leads: [60],
        defaults: [60],
        next_due: { '60': null },
        deliverable: false,
        code: 'reminders_no_access',
      },
    });
  });
  const detail = await openPopover(page, seeded);
  await expect(detail.getByRole('button', { name: 'Reminding: 1 h' })).toBeVisible();
  await expect(detail.getByRole('status')).toContainText(
    'Reminders cannot be sent for this event with your current access.',
  );
  await detail.getByRole('button', { name: 'Reminding: 1 h' }).click();
  await shoot(detail, '04-no-access-message');
});

test('the Reminders page tells everyone when reminders are unavailable, the reason only managers', async ({
  page,
  browser,
  baseURL,
}) => {
  await resetReminders(page); // no public address saved: the default host cannot deliver
  const reader = await readerPage(browser, baseURL as string);
  try {
    await reader.page.goto('/admin/events/reminders');
    const note = reader.page.getByTestId('reminders-unavailable');
    await expect(note).toContainText('Reminders are not available on this site right now.');
    await expect(reader.page.locator('body')).not.toContainText('public address is not set');
    await shoot(reader.page, '04-unavailable', { fullPage: true });
  } finally {
    await reader.context.close();
  }
  await page.goto('/admin/events/reminders');
  await expect(page.getByTestId('reminders-unavailable')).toBeVisible();
  await expect(page.getByText(/public address is not set/)).toBeVisible();
});
