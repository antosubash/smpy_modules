import { expect, type Page, test } from '@playwright/test';

import { login, moduleCsrfHeader, uniqueSlug } from './helpers';

/**
 * The editor's schedule fields, in a browser that is not on UTC.
 *
 * The stored instant is UTC, but SQLite hands it back without an offset. The
 * editor used to read that zoneless string as local time, so in Vienna a
 * schedule redisplayed two hours early and every unchanged re-save moved it
 * back another two. Asserted as what a writer sees after a reload, and as the
 * instant the server holds after saving twice.
 */

test.use({ timezoneId: 'Europe/Vienna' });

async function openSchedule(page: Page, id: number) {
  await page.goto(`/pagebuilder/${id}/edit`);
  await page.getByRole('button', { name: /^settings$/i }).click();
  await page.getByTestId('inspector-tab-seo').click();
}

test('a saved schedule keeps the time that was entered', async ({ page }) => {
  await login(page);
  const slug = uniqueSlug('schedule-tz');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers: await moduleCsrfHeader(page, '/pagebuilder/'),
    data: {
      title: `Schedule ${slug}`,
      slug,
      draft_data: { root: { props: { title: slug, width: 'full' } }, content: [], zones: {} },
    },
  });
  const { id } = (await created.json()) as { id: number };

  // Days ahead so no scheduler tick can publish it mid-test. Built in the
  // page's own clock, the zone the input is read in.
  const when = await page.evaluate(() => {
    const d = new Date(Date.now() + 3 * 86_400_000);
    d.setHours(23, 30, 0, 0);
    return d.toISOString();
  });
  const entered = await page.evaluate((iso) => {
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }, when);
  expect(entered).toMatch(/T23:30$/);

  await openSchedule(page, id);
  const input = page.getByTestId('schedule-publish-at');
  await input.fill(entered);
  for (let save = 0; save < 2; save++) {
    const saved = page.waitForResponse((r) => r.url().endsWith(`/pages/${id}/schedule`));
    await page.getByTestId('schedule-save').click();
    expect((await saved).ok()).toBe(true);
    await expect(input).toHaveValue(entered);
  }

  await openSchedule(page, id);
  await expect(page.getByTestId('schedule-publish-at')).toHaveValue(entered);

  const stored = await page.request.get(`/api/pagebuilder/pages/${id}`);
  const { publish_at } = (await stored.json()) as { publish_at: string };
  expect(new Date(publish_at).toISOString()).toBe(when);
});
