/**
 * The newsletter's Event card end to end: the picker offers only upcoming public events, the
 * preview shows the date in the event's own zone, a scheduled email carries the card with links on
 * the tenant's public origin and no event id, and unpublishing the event afterwards changes
 * nothing already scheduled while a refresh in a new draft reports the source gone.
 *
 * Runs only with E2E_NEWSLETTER=1 (CI's `E2E (newsletter)` job, a non-bundle development host with
 * Celery eager and the console transport), like newsletter.spec.ts, and writes and restores the
 * same settings. Standalone: it seeds its own list, subscriber, calendar and events.
 */

import { expect, test } from '@playwright/test';

import { addDays, wednesday } from './events-calendar-helpers';
import { postCalendar, postEvent, publishEvent, slugOf, uploadSiteImage } from './events-seed';
import { shoot } from './events-shots';
import { login, moduleCsrfHeader } from './helpers';
import { eventCard, setBody } from './newsletter-campaign';
import {
  type Cleanup,
  configureNewsletter,
  csrf,
  exportFile,
  importViaApi,
  outbox,
  restoreSettings,
  tickUntil,
} from './newsletter-helpers';

const rand = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
const subscriber = `reader-${rand}@example.org`;
const subject = "What's on in December";
const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;

test.describe('Newsletter event card', () => {
  const cleanup: Cleanup = {};

  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    await login(page);
    await restoreSettings(page, cleanup);
    await page.close();
  });

  test('pick, preview, schedule, unpublish and refresh', async ({ page, baseURL }) => {
    test.setTimeout(240_000);
    // The editor's picker once logged `NaN is an invalid value for the css style property top`.
    const nan: string[] = [];
    page.on('console', (m) => {
      if (/NaN/.test(m.text())) nan.push(m.text());
    });
    const day = wednesday(2);
    // Unique per run, so a CI retry on the same database can create it again; the plain key is only for
    // the PR screenshots.
    const listKey = process.env.E2E_SHOTS_DIR ? 'members' : `members_${Date.now().toString(36)}`;
    let campaignId = 0;
    let event = { id: '', revision: 0 };
    let slug = '';
    let image = '';
    const hiddenIds: string[] = [];

    await test.step('setup: a list with one reader, a public event and some that are not', async () => {
      await login(page);
      await configureNewsletter(page, cleanup, { baseURL: baseURL ?? '' });
      const created = await page.request.post('/api/newsletter/lists', {
        headers: await csrf(page),
        data: { key: listKey, label: 'Members' },
      });
      expect(created.status(), await created.text()).toBe(201);
      const job = await importViaApi(page, listKey, [
        exportFile('subscribed_members_export_events.csv', [{ email: subscriber, first: 'Rae' }]),
      ]);
      expect(job.created).toBe(1);

      image = await uploadSiteImage(page);
      const calendars = {
        public: await postCalendar(page, { name: 'Open studio programme', visibility: 'public' }),
        internal: await postCalendar(page, { name: 'Studio staff', visibility: 'internal' }),
      };
      const seed = {
        calendar: calendars.public.id,
        start: `${day}T10:00`,
        end: `${day}T11:30`,
        description: '<p>Meet the makers and see the new kiln.</p>',
        venue: 'Studio 3, Kiln Lane',
        image,
      };
      const made = await postEvent(page, { ...seed, title: 'Open studio day' });
      event = { id: made.id, revision: await publishEvent(page, made) };
      slug = await slugOf(page, made.id);
      const draft = await postEvent(page, { ...seed, title: 'Open draft rehearsal' });
      const staff = await postEvent(page, {
        ...seed,
        calendar: calendars.internal.id,
        title: 'Open staff retreat',
      });
      await publishEvent(page, staff);
      const past = await postEvent(page, {
        ...seed,
        title: 'Open last year',
        start: `${addDays(day, -400)}T10:00`,
        end: `${addDays(day, -400)}T11:00`,
      });
      await publishEvent(page, past);
      hiddenIds.push(event.id, draft.id, staff.id, past.id);
    });

    await test.step('a campaign with a card for another event, then the picker swaps it', async () => {
      const decoy = await postEvent(page, {
        calendar: (await postCalendar(page, { name: 'Lecture series', visibility: 'public' })).id,
        title: 'Winter lecture',
        start: `${addDays(day, 1)}T18:00`,
        end: `${addDays(day, 1)}T19:00`,
      });
      await publishEvent(page, decoy);
      await page.goto('/admin/newsletter/');
      await page.getByRole('button', { name: 'New campaign' }).click();
      const dialog = page.getByRole('dialog', { name: 'New campaign' });
      await dialog.getByLabel('Name').fill('December programme');
      await dialog.getByLabel('Newsletter list').selectOption(listKey);
      await dialog.getByRole('button', { name: 'Create', exact: true }).click();
      await page.waitForURL(/\/admin\/newsletter\/campaigns\/\d+$/);
      campaignId = Number(new URL(page.url()).pathname.split('/').pop());
      await setBody(page, campaignId, [await eventCard(page, 'card1', decoy.id)]);
      await page.reload();
      await page.getByLabel('Subject', { exact: true }).fill(subject);

      await page.frameLocator('#preview-frame').locator('[data-puck-component="card1"]').click();
      await page.getByRole('searchbox', { name: 'Search', exact: true }).fill('Open');
      const hits = page.getByRole('list').filter({
        has: page.getByRole('button', { name: /Open studio day/ }),
      });
      await expect(hits.getByRole('button')).toHaveCount(1); // not the draft, the staff event or last year's
      // The server words the time, so the picker names the zone the email does.
      await expect(hits).toContainText(/10:00 AM.{1,3}11:30 AM (CET|CEST)/);
      await expect(hits).not.toContainText('GMT');
      await shoot(page, '06-newsletter-card-picker');
      await hits.getByRole('button').click();
      await expect
        .poll(async () => {
          const c = await (
            await page.request.get(`/api/newsletter/campaigns/${campaignId}`)
          ).json();
          return c.body[0]?.props?.source_id;
        })
        .toBe(event.id);
    });

    await test.step('a forged card cannot be saved: it must link only into the site', async () => {
      const current = await (
        await page.request.get(`/api/newsletter/campaigns/${campaignId}`)
      ).json();
      const card = current.body[0];
      for (const change of [
        { url: 'https://evil.example/' },
        { ics_url: 'mailto:a@evil.example' },
        { image_url: 'https://evil.example/x.png' },
      ]) {
        const forged = await page.request.patch(`/api/newsletter/campaigns/${campaignId}`, {
          headers: await csrf(page),
          data: {
            expected_revision: current.revision,
            body: [{ ...card, props: { ...card.props, ...change } }],
          },
        });
        expect(forged.status(), JSON.stringify(change)).toBe(422);
        expect((await forged.json()).code).toBe('invalid_body');
      }
    });

    await test.step('the preview names the time in the event zone and the zone', async () => {
      await page.getByRole('button', { name: 'Preview', exact: true }).click();
      const frame = page.frameLocator('iframe[title="Email preview"]');
      await expect(frame.getByText('Open studio day')).toBeVisible();
      await expect(frame.getByText(/10:00 AM.*11:30 AM (CET|CEST)/)).toBeVisible();
      await expect(frame.getByText('Studio 3, Kiln Lane')).toBeVisible();
      await expect(frame.getByRole('link', { name: 'Add to calendar' })).toHaveAttribute(
        'href',
        new RegExp(`^${baseURL}/events/${slug}\\.ics$`),
      );
      // A tall window, so the card's text under its image is in the picture too.
      const size = page.viewportSize();
      await page.setViewportSize({ width: 1280, height: 1900 });
      await shoot(page, '07-newsletter-preview');
      if (size) await page.setViewportSize(size);
    });

    let sent = '';
    await test.step('schedule, dispatch, and read the delivered email', async () => {
      await page.getByRole('button', { name: 'Send…' }).click();
      const dialog = page.getByRole('dialog', { name: 'Send campaign' });
      await dialog.getByRole('radio', { name: 'Send now' }).check();
      await dialog.getByRole('button', { name: 'Send', exact: true }).click();
      await expect(dialog).toHaveCount(0);
      await tickUntil(
        page,
        campaignId,
        (p) => p.queued === 0 && p.sent === 1 && p.status === 'sent',
      );
      const mine = (await outbox(page)).filter((m) => m.subject === subject);
      expect(mine.map((m) => m.to)).toEqual([subscriber]);
      sent = mine[0].html;
      if (process.env.E2E_SHOTS_DIR) {
        const mail = await page.context().newPage();
        await mail.setViewportSize({ width: 800, height: 1400 });
        await mail.setContent(sent);
        await mail.waitForLoadState('load');
        await shoot(mail, '08-newsletter-email', { fullPage: true });
        await mail.close();
      }
      expect(sent).toContain('Open studio day');
      // Click tracking rewrote the links: each one redirects to the campaign tenant's own address.
      const tracked = [...sent.matchAll(/href="([^"]*\/newsletter\/c\/[^"]+)"/g)].map((m) => m[1]);
      const targets: string[] = [];
      for (const link of new Set(tracked)) {
        const hop = await page.request.get(link, { maxRedirects: 0 });
        expect(hop.status()).toBeGreaterThanOrEqual(300);
        targets.push(hop.headers().location ?? '');
      }
      expect(targets.sort()).toEqual([
        `${baseURL}/events/${slug}`,
        `${baseURL}/events/${slug}.ics`,
      ]);
      expect(sent).toMatch(/10:00 AM.{1,3}11:30 AM (CET|CEST)/);
      // Nothing in the email points off the site: every address is on the tenant's origin.
      const addresses = [...sent.matchAll(/(?:href|src)="([^"]*)"/g)].map((m) => m[1]);
      expect(addresses.length).toBeGreaterThan(3);
      for (const address of addresses)
        expect(address.startsWith(`${baseURL}/`), address).toBe(true);
      expect(sent).toContain(`<img src="${baseURL}${image}"`);
      for (const id of hiddenIds) expect(sent + mine[0].text).not.toContain(id);
      expect([...(sent + mine[0].text).matchAll(UUID)].map((m) => m[0])).toEqual([]);
      expect(sent).not.toContain('Open draft rehearsal');
    });

    await test.step('unpublish: the scheduled email stays as it was, a new draft refresh is gone', async () => {
      const unpublished = await page.request.post(`/api/events/events/${event.id}/unpublish`, {
        headers: await moduleCsrfHeader(page, '/admin/events/calendars'),
        data: { expected_revision: event.revision },
      });
      expect(unpublished.ok(), await unpublished.text()).toBeTruthy();
      const again = (await outbox(page)).filter((m) => m.subject === subject);
      expect(again).toHaveLength(1);
      expect(again[0].html).toBe(sent);

      const kept = (
        await (await page.request.get(`/api/newsletter/campaigns/${campaignId}`)).json()
      ).body[0];
      const draft = await page.request.post('/api/newsletter/campaigns', {
        headers: await csrf(page),
        data: { name: `Second issue ${rand}`, list_type_key: listKey },
      });
      expect(draft.status(), await draft.text()).toBe(201);
      const { id, revision } = (await draft.json()) as { id: number; revision: number };
      await setBody(page, id, [kept]);
      const current = await (await page.request.get(`/api/newsletter/campaigns/${id}`)).json();
      const gone = await page.request.post(`/api/newsletter/campaigns/${id}/cards/refresh`, {
        headers: await csrf(page),
        data: { block_id: kept.props.id, expected_revision: current.revision },
      });
      expect(gone.status()).toBe(409);
      expect((await gone.json()).code).toBe('card_source_gone');
      const after = await (await page.request.get(`/api/newsletter/campaigns/${id}`)).json();
      expect([after.revision, after.body]).toEqual([current.revision, current.body]);
      expect(revision).toBeGreaterThan(0);

      const search = await page.request.get('/api/newsletter/cards/events?q=Open');
      expect((await search.json()).map((h: { title: string }) => h.title)).toEqual([]);
    });

    expect(nan).toEqual([]);
  });
});
