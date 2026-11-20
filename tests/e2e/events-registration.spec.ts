import { expect, type Page, test } from '@playwright/test';

import { addDays, seedCalendar, wednesday } from './events-calendar-helpers';
import { guardPublic } from './events-public-helpers';
import { postEvent, publishEvent, slugOf } from './events-seed';
import { shoot } from './events-shots';
import { login, uniqueSlug } from './helpers';

/**
 * Event registration through records, on the production bundle: an organiser picks (and creates)
 * a registration form in the event editor and sets the seats; an anonymous visitor registers on
 * the public event page; a signed-in visitor sees "My registrations".
 *
 * The form is double opt-in (records' default), so the visitor is told to check the inbox: the
 * confirmation mail itself is covered by the Python suites. Standalone: every test seeds its own
 * calendar and event through the admin API; every page runs under the public guard (no page
 * error, console error or CSP violation).
 */
test.skip(
  process.env.E2E_BUNDLE !== '1',
  'the nonce policy and the lazy chunks exist only in the bundle',
);

let problems: string[] = [];
test.beforeEach(({ page }) => {
  problems = [];
  guardPublic(page, problems);
});
test.afterEach(() => {
  expect(problems).toEqual([]);
});

async function seedEvent(admin: Page, title: string) {
  const calendar = await seedCalendar(admin, { visibility: 'public', label: title, plain: true });
  const day = addDays(wednesday(3), 0);
  const event = await postEvent(admin, {
    calendar: calendar.id,
    title,
    start: `${day}T18:00`,
    end: `${day}T19:00`,
    venue: 'Studio',
    description: '<p>Bring a friend.</p>',
  });
  const revision = await publishEvent(admin, event);
  return { ...event, revision, slug: await slugOf(admin, event.id) };
}

test('the organiser creates a form and sets the seats; a visitor registers; the page shows states', async ({
  page,
  browser,
}) => {
  await login(page);
  const title = `Workshop ${uniqueSlug('reg')}`;
  const event = await seedEvent(page, title);

  await page.goto(`/admin/events/edit/${event.id}`);
  const section = page.getByTestId('registration-section');
  await section.getByLabel('On this site').check();
  await section.getByRole('button', { name: 'Create a registration form' }).click();
  await expect(section.getByLabel('Registration form')).not.toHaveValue('');
  await section.getByLabel('Seats').fill('2');
  await section.getByLabel('Show the remaining seats on the public page').check();
  await shoot(section, '01-editor-registration');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();

  const visitor = await (await browser.newContext()).newPage();
  guardPublic(visitor, problems);
  await visitor.goto(`/events/${event.slug}`);
  const panel = visitor.getByTestId('registration-panel');
  await expect(panel.getByText(`Registering for ${title}`)).toBeVisible();
  await expect(panel.getByText('2 seats left.')).toBeVisible();
  await shoot(visitor, '02-public-panel', { fullPage: true });

  await panel.getByLabel(/name/i).first().fill('Ada Visitor');
  await panel
    .getByLabel(/email/i)
    .first()
    .fill(`ada-${uniqueSlug('v')}@example.org`);
  await visitor.waitForTimeout(3500); // the form's minimum fill time
  await panel.getByRole('button', { name: 'Register' }).click();
  await expect(panel.getByText('Check your inbox')).toBeVisible();
  await expect(panel).not.toContainText(/already registered/i);
  await shoot(visitor, '03-checked-inbox');

  // The organiser sees counts, never people, in the editor.
  await page.reload();
  await expect(page.getByTestId('registration-counts')).toBeVisible();
  await visitor.context().close();
});

test('an event without registration shows no panel', async ({ page, browser }) => {
  await login(page);
  const title = `Plain ${uniqueSlug('reg')}`;
  const event = await seedEvent(page, title);
  const anon = await (await browser.newContext()).newPage();
  guardPublic(anon, problems);
  await anon.goto(`/events/${event.slug}`);
  await expect(anon.getByRole('heading', { name: title, level: 1 })).toBeVisible();
  await expect(anon.getByTestId('registration-panel')).toHaveCount(0);
  await anon.context().close();
});

test('My registrations is in the menu and says why an unverified address sees no list', async ({
  page,
}) => {
  await login(page);
  await page.goto('/admin/records/');
  const link = page.locator('aside').getByRole('link', { name: 'My registrations' });
  await expect(link).toBeVisible();
  await link.click();
  await expect(page.getByRole('heading', { name: 'My registrations', level: 1 })).toBeVisible();
  await expect(
    page
      .getByTestId('mine-list')
      .or(page.getByTestId('mine-empty'))
      .or(page.getByTestId('mine-unverified')),
  ).toBeVisible();
});
