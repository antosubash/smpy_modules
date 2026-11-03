import { type Browser, expect, type Page, test } from '@playwright/test';

import { login, moduleCsrfHeader, uniqueSlug } from './helpers';
import { apiCreateRecord, seedTextType } from './records-helpers';

/**
 * The RecordStats block: a live count of the published records of a public
 * type, read by an anonymous visitor from the public stats route.
 *
 * Standalone: each test seeds a type of its own, so the count is exactly the
 * records it created. Assertions are on the visible number, retried.
 */

const BLOCK = 'Live record numbers';
const LABEL = 'Widgets';

async function publishStatsPage(page: Page, typeKey: string): Promise<string> {
  const headers = await moduleCsrfHeader(page, '/pagebuilder/');
  const slug = uniqueSlug('e2e-records-stats');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title: 'Record numbers',
      slug,
      draft_data: {
        root: { props: { title: 'Record numbers', width: 'full' } },
        content: [
          {
            type: 'RecordStats',
            props: {
              id: 'RecordStats-test',
              title: 'In numbers',
              subtitle: '',
              surface: 'cards',
              items: [
                {
                  typeKey,
                  metric: 'count',
                  field: '',
                  filter: '',
                  label: LABEL,
                  prefix: '',
                  suffix: '',
                },
              ],
              locale: '',
              tenant: '',
              apiPrefix: '/api/records/public',
            },
          },
        ],
      },
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  const { id } = (await created.json()) as { id: number };
  // The 201 can arrive before the row is committed (upstream GH #257).
  await expect
    .poll(async () => (await page.request.get(`/api/pagebuilder/pages/${id}`)).status())
    .toBe(200);
  const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, { headers });
  expect(published.status(), await published.text()).toBe(200);
  return slug;
}

/** What a first-time anonymous visitor sees once the block has asked. The
 *  public answer is cacheable, so a returning browser may hold an old number by
 *  design; a fresh context has no cache, which is what a mutation is measured
 *  against. */
async function visitorSees(browser: Browser, slug: string): Promise<string> {
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    const answered = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith('/stats'));
    await page.goto(`/p/${slug}`);
    await answered;
    const number = page.locator('dd').first();
    // The dash is the loading state too; wait for a number to replace it.
    await expect(number).not.toHaveText('–');
    return ((await number.textContent()) ?? '').trim();
  } finally {
    await context.close();
  }
}

test.describe('Record stats block', () => {
  test('is offered in the page palette', async ({ page }) => {
    await login(page);
    await page.goto('/pagebuilder/new');
    await expect(
      page.locator('[class*="DrawerItem-name"]').filter({ hasText: BLOCK }).first(),
    ).toBeAttached();
  });

  test('is not offered in the site-layout palette', async ({ page }) => {
    await login(page);
    await page.goto('/pagebuilder/layout');
    await expect(page.locator('[class*="DrawerItem-name"]').filter({ hasText: BLOCK })).toHaveCount(
      0,
    );
  });

  test('an anonymous visitor sees the count, and it follows a new record', async ({
    page,
    browser,
  }) => {
    await login(page);
    const key = await seedTextType(page, 'stat', { is_public: true });
    await apiCreateRecord(page, key, { data: { title: 'One' }, status: 'published' });
    await apiCreateRecord(page, key, { data: { title: 'Two' }, status: 'published' });
    // A draft is not part of the public count.
    await apiCreateRecord(page, key, { data: { title: 'Draft' }, status: 'draft' });
    const slug = await publishStatsPage(page, key);

    const anon = await (await browser.newContext()).newPage();
    try {
      await anon.goto(`/p/${slug}`);
      await expect(anon.locator('dd').first()).toHaveText('2');
      await expect(anon.getByText(LABEL, { exact: true })).toBeVisible();
    } finally {
      await anon.context().close();
    }

    await apiCreateRecord(page, key, { data: { title: 'Three' }, status: 'published' });
    await expect.poll(() => visitorSees(browser, slug), { timeout: 20_000 }).toBe('3');
  });

  test('a record of a private type is not counted: the block shows a dash', async ({
    page,
    browser,
  }) => {
    await login(page);
    const key = await seedTextType(page, 'privstat', { is_public: false });
    await apiCreateRecord(page, key, { data: { title: 'Hidden' }, status: 'published' });
    const slug = await publishStatsPage(page, key);

    const anon = await (await browser.newContext()).newPage();
    try {
      // A private type is a 404 from the public route, not a zero.
      const answered = anon.waitForResponse((r) => new URL(r.url()).pathname.endsWith('/stats'));
      await anon.goto(`/p/${slug}`);
      expect((await answered).status()).toBe(404);
      await expect(anon.locator('dd').first()).toHaveText('–');
    } finally {
      await anon.context().close();
    }
  });
});
