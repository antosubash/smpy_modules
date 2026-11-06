/**
 * The newsletter end to end: a list, a Mailchimp import through the screen,
 * the suppressions it leaves, a campaign with an article card, preview, test
 * send, a send to one tag, delivery, the report and an unsubscribe.
 *
 * Runs only with E2E_NEWSLETTER=1 (CI's `E2E (newsletter)` job): sending needs
 * the dispatch hook (R17), which exists only on a development or testing host
 * with Celery eager and the console transport. The spec writes the settings it
 * needs and puts back exactly those in `afterAll`, through a fresh session
 * (R18, D7).
 */

import { expect, test } from '@playwright/test';

import { paragraphBody, seedArticle } from './article-helpers';
import { login } from './helpers';
import { articleCard, setBody, reportTile as tile } from './newsletter-campaign';
import {
  type Cleanup,
  configureNewsletter,
  importCount as count,
  exportFile as file,
  importViaApi,
  lookupSuppressions,
  NEWSLETTER_SETTINGS,
  newsletterSettings,
  outbox,
  pick,
  progress,
  restoreSettings,
  searchSubscribers,
  tickUntil,
} from './newsletter-helpers';

const rand = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
const address = (name: string) => `${name}-${rand}@example.org`;
const [ada, bob, carl, cy, dee] = ['ada', 'bob', 'carl', 'cy', 'dee'].map(address);
const subject = `E2E issue ${rand}`;

test.describe('Newsletter', () => {
  const cleanup: Cleanup = {};

  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    await login(page);
    await restoreSettings(page, cleanup);
    await page.close();
  });

  test('restore handles a partial setup', async ({ page, baseURL }) => {
    await login(page);
    const original = pick(await newsletterSettings(page));
    await expect(
      configureNewsletter(page, cleanup, { baseURL: baseURL ?? '', failAfter: 'newsletter' }),
    ).rejects.toThrow(/failAfter/);
    expect(pick(await newsletterSettings(page))).toEqual(NEWSLETTER_SETTINGS);

    await restoreSettings(page, cleanup);
    expect(pick(await newsletterSettings(page))).toEqual(original);
    expect(cleanup.host).toBeUndefined();
  });

  test('import, suppress, send to a tag, report and unsubscribe', async ({ page, baseURL }) => {
    test.setTimeout(240_000);
    let listKey = '';
    let campaignId = 0;
    let article = { articleId: 0, title: '' };

    await test.step('setup', async () => {
      await login(page);
      await configureNewsletter(page, cleanup, { baseURL: baseURL ?? '' });
      article = await seedArticle(page, {
        titlePrefix: 'Newsletter card',
        publish: true,
        body: paragraphBody('A story for the newsletter.'),
      });
    });

    await test.step('create a list', async () => {
      await page.goto('/admin/newsletter/import');
      await page.getByRole('button', { name: 'New list' }).click();
      const dialog = page.getByRole('dialog', { name: 'New list' });
      await dialog.getByLabel('Name').fill(`E2E list ${rand}`);
      listKey = `e2e_list_${rand}`;
      await expect(dialog.getByLabel('Key')).toHaveValue(listKey);
      await dialog.getByRole('button', { name: 'Create list' }).click();
      await expect(dialog).toHaveCount(0);
      await expect(page.getByLabel('Newsletter list')).toHaveValue(listKey);
    });

    await test.step('a suppressed vip subscriber, before the main import', async () => {
      const subscribed = await importViaApi(page, listKey, [
        file('subscribed_members_export_carl.csv', [{ email: carl, first: 'Carl', tags: ['vip'] }]),
      ]);
      expect(subscribed.created).toBe(1);
      await importViaApi(page, listKey, [
        file('cleaned_members_export_carl.csv', [{ email: carl, first: 'Carl' }]),
      ]);
      const held = await searchSubscribers(page, listKey, carl);
      expect(held.map((s) => [s.status, s.tags])).toEqual([['confirmed', ['vip']]]);
      expect((await lookupSuppressions(page, carl)).map((s) => s.reason)).toContain(
        'imported_cleaned',
      );
    });

    await test.step('import through the screen', async () => {
      const files = [
        file('subscribed_members_export_e2e.csv', [
          { email: ada, first: 'Ada', tags: ['vip'] },
          { email: bob, first: 'Bob', tags: ['other'] },
          { email: carl, first: 'Carl', tags: ['vip'] },
        ]),
        file('unsubscribed_members_export_e2e.csv', [{ email: cy, first: 'Cy' }]),
        file('cleaned_members_export_e2e.csv', [{ email: dee, first: 'Dee' }]),
      ];
      await page
        .getByLabel('Mailchimp export')
        .setInputFiles(
          files.map((f) => ({ name: f.name, mimeType: 'text/csv', buffer: Buffer.from(f.csv) })),
        );
      await page.getByRole('button', { name: 'Upload' }).click();

      for (const kind of ['Subscribed', 'Unsubscribed', 'Cleaned']) {
        await expect(page.getByRole('cell', { name: kind, exact: true })).toBeVisible();
      }
      await expect(page.getByText(/^vip \(\d+\)$/)).toBeVisible();
      await expect(page.getByText(/^other \(1\)$/)).toBeVisible();
      await expect(page.getByLabel('First Name', { exact: true })).toHaveValue('first_name');
      await expect(page.getByRole('switch', { name: 'Import tags' })).toBeChecked();

      await page.getByRole('button', { name: 'Start import' }).click();
      await expect(page.getByText('The import is finished.')).toBeVisible();
      await expect(count(page, 'Created')).toHaveText('2');
      await expect(count(page, 'Skipped')).toHaveText('1');
      await expect(count(page, 'Suppressed')).toHaveText('2');
    });

    await test.step('the suppressions, on their own', async () => {
      const cyRows = await lookupSuppressions(page, cy);
      expect(cyRows).toContainEqual(
        expect.objectContaining({
          reason: 'unsubscribed',
          source: 'import',
          list_type_key: listKey,
        }),
      );
      expect((await lookupSuppressions(page, dee)).map((s) => s.reason)).toContain(
        'imported_cleaned',
      );
      expect((await lookupSuppressions(page, carl)).map((s) => s.reason)).toContain(
        'imported_cleaned',
      );

      await page.goto(`/admin/newsletter/subscribers?list=${listKey}`);
      await page.getByRole('button', { name: /^Unsubscribed \(\d+\)$/ }).click();
      await expect(page.getByRole('cell', { name: cy })).toBeVisible();
      await page.getByRole('button', { name: /^All \(\d+\)$/ }).click();
      await page.getByRole('searchbox', { name: 'Search subscribers' }).fill(dee);
      await expect(page.getByText('No subscribers match.')).toBeVisible();
    });

    await test.step('a campaign with an article card', async () => {
      await page.goto('/admin/newsletter/');
      await page.getByRole('button', { name: 'New campaign' }).click();
      const dialog = page.getByRole('dialog', { name: 'New campaign' });
      await dialog.getByLabel('Name').fill(`E2E campaign ${rand}`);
      await dialog.getByLabel('Newsletter list').selectOption(listKey);
      await dialog.getByRole('button', { name: 'Create', exact: true }).click();
      await page.waitForURL(/\/admin\/newsletter\/campaigns\/\d+$/);
      campaignId = Number(new URL(page.url()).pathname.split('/').pop());

      // Seeded with another article's card (the suite seeds bodies rather than
      // dragging blocks); the picker on the canvas then swaps in the real one.
      const decoy = await seedArticle(page, { titlePrefix: 'Newsletter decoy', publish: true });
      await setBody(page, campaignId, [await articleCard(page, 'card1', decoy.articleId)]);
      await page.reload();

      await page.getByLabel('Subject', { exact: true }).fill(subject);
      await page.frameLocator('#preview-frame').locator('[data-puck-component="card1"]').click();
      await page.getByRole('searchbox', { name: 'Search', exact: true }).fill(article.title);
      // The unfiltered hits (decoy included) show first and are replaced once the
      // debounced search answers; clicking before that can land on a moving list.
      const hits = page
        .getByRole('list')
        .filter({ has: page.getByRole('button', { name: new RegExp(article.title) }) })
        .getByRole('button');
      await expect(hits).toHaveCount(1);
      await hits.click();
      await expect
        .poll(async () => {
          const c = await (
            await page.request.get(`/api/newsletter/campaigns/${campaignId}`)
          ).json();
          return [c.subject, c.body[0]?.props?.source_id];
        })
        .toEqual([subject, article.articleId]);
    });

    await test.step('preview', async () => {
      await page.getByRole('button', { name: 'Preview', exact: true }).click();
      const frame = page.frameLocator('iframe[title="Email preview"]');
      await expect(frame.getByText(article.title)).toBeVisible();
    });

    await test.step('test send', async () => {
      const tester = address('tester');
      await page.getByRole('button', { name: 'Send test' }).click();
      const dialog = page.getByRole('dialog', { name: 'Send a test email' });
      await dialog.getByLabel('Recipients').fill(tester);
      await dialog.getByRole('button', { name: 'Send', exact: true }).click();
      await expect(dialog.getByRole('list', { name: 'Test results' })).toContainText('Accepted');
      await dialog.getByRole('button', { name: 'Close', exact: true }).first().click();
      const sent = (await outbox(page)).filter((m) => m.to === tester);
      expect(sent).toHaveLength(1);
      expect(sent[0].subject.startsWith('[TEST]')).toBeTruthy();
    });

    await test.step('send to the vip tag', async () => {
      await page.getByRole('radio', { name: 'A tag' }).click();
      await page.getByLabel('Tag', { exact: true }).selectOption({ label: 'vip' });
      await page.getByRole('button', { name: 'Send…' }).click();
      const dialog = page.getByRole('dialog', { name: 'Send campaign' });
      await dialog.getByRole('radio', { name: 'Send now' }).check();
      await dialog.getByRole('button', { name: 'Send', exact: true }).click();
      await expect(dialog).toHaveCount(0);
      expect((await progress(page, campaignId)).status).toBe('scheduled');
      await expect(page.getByText('Scheduled', { exact: true })).toBeVisible();
    });

    await test.step('dispatch and progress', async () => {
      const done = await tickUntil(
        page,
        campaignId,
        (p) => p.queued === 0 && p.sent === 1 && p.status === 'sent',
      );
      expect(done.suppressed).toBe(1);
      await page.reload();
      await expect(page.getByText('Sent', { exact: true })).toBeVisible();
      await expect(page.getByText(/1 suppressed/)).toBeVisible();
    });

    let unsubscribeUrl = '';
    await test.step('the suppression holds in delivery', async () => {
      const mine = (await outbox(page)).filter((m) => m.subject === subject);
      expect(mine.map((m) => m.to)).toEqual([ada]);
      const header = mine[0].headers['List-Unsubscribe'] ?? '';
      unsubscribeUrl = header.match(/<(https?:\/\/[^>]+)>/)?.[1] ?? '';
      expect(unsubscribeUrl.startsWith(`${baseURL}/`)).toBeTruthy();
    });

    await test.step('report', async () => {
      await page.goto(`/admin/newsletter/campaigns/${campaignId}/report`);
      await expect(tile(page, 'Accepted')).toHaveText('1');
      await expect(tile(page, 'Suppressed')).toHaveText('1');
    });

    await test.step('unsubscribe', async () => {
      await page.goto(unsubscribeUrl);
      await page.getByRole('button', { name: 'Unsubscribe' }).click();
      await expect(
        page.getByText('Done. You will not receive these emails any more.'),
      ).toBeVisible();

      await page.goto(`/admin/newsletter/subscribers?list=${listKey}`);
      await page.getByRole('button', { name: /^Unsubscribed \(\d+\)$/ }).click();
      await expect(page.getByRole('cell', { name: ada })).toBeVisible();

      await page.goto(`/admin/newsletter/campaigns/${campaignId}/report`);
      await expect(tile(page, 'Unsubscribed')).toHaveText('1');
    });
  });
});
