import { expect, test } from '@playwright/test';

import {
  apiAct,
  apiCalendar,
  apiEvent,
  apiGet,
  apiPublished,
  apiViewer,
  edit,
  field,
  freshCalendar,
  LIST,
  NEW_YORK,
  row,
  save,
  setupSpec,
  watch,
} from './events-editor-helpers';
import { login, uniqueSlug } from './helpers';

/**
 * The event editor's workflow, conflict handling, leave guard, rights and German.
 * Standalone: every test seeds its own calendar and events through the API.
 */

const problems = setupSpec();

test('the workflow: submit, reject with a note, approve, unpublish, history', async ({ page }) => {
  const calendar = await freshCalendar(page);
  const event = await apiEvent(page, calendar, `Flow ${uniqueSlug('ev')}`);
  await page.goto(edit(event.id));
  const bar = page.getByRole('region', { name: 'Publishing' });
  await bar.getByRole('button', { name: 'Submit for review' }).click();
  await expect(bar).toContainText('In review');

  await bar.getByRole('button', { name: 'Reject…' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Reject', exact: true }).click();
  await expect(dialog.getByLabel('Note')).toHaveAccessibleDescription(/required/i);
  await dialog.getByLabel('Note').fill('Needs a venue');
  await dialog.getByRole('button', { name: 'Reject', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(bar).toContainText('Draft');

  await bar.getByRole('button', { name: 'Submit for review' }).click();
  await expect(bar).toContainText('In review');
  await bar.getByRole('button', { name: 'Approve…' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(bar).toContainText('Published');
  await bar.getByRole('button', { name: 'Unpublish' }).click();
  await expect(bar).toContainText('Draft');

  await page.getByRole('button', { name: 'History', exact: true }).click();
  const history = page.getByRole('dialog');
  for (const step of [
    'Submitted for review',
    'Rejected',
    'Approved and published',
    'Unpublished',
  ]) {
    await expect(history.getByRole('listitem').filter({ hasText: step }).first()).toContainText(
      'You',
    );
  }
  await expect(history).toContainText('Needs a venue');
});

test('a stale save shows the conflict panel; Save mine keeps both edits', async ({ page }) => {
  const calendar = await freshCalendar(page);
  const event = await apiEvent(page, calendar, `Race ${uniqueSlug('ev')}`, { venue: 'Hall A' });
  const other = await page.context().newPage();
  watch(other, problems);
  await page.goto(edit(event.id));
  await other.goto(edit(event.id));
  await expect(field(other, 'Venue')).toHaveValue('Hall A');

  await field(other, 'Venue').fill('Hall B');
  await save(other).click();
  await expect(save(other)).toBeDisabled();
  const title = `Race mine ${uniqueSlug('ev')}`;
  await field(page, 'Title').fill(title);
  await save(page).click();
  await expect(
    page.getByRole('region', { name: 'Someone else saved this event first' }),
  ).toBeVisible();
  await expect(save(page)).toBeDisabled();

  await page.getByRole('button', { name: 'Save mine over theirs' }).click();
  await expect.poll(async () => (await apiGet(page, event.id)).texts.en?.title).toBe(title);
  expect((await apiGet(page, event.id)).venue_name).toBe('Hall B');
  await other.close();
});

test('the leave guard: Stay, held Back, Leave, and no dialog after a save', async ({ page }) => {
  const calendar = await freshCalendar(page);
  const title = `Guard ${uniqueSlug('ev')}`;
  const event = await apiEvent(page, calendar, title);
  const open = async () => {
    await page.goto(LIST);
    await page.getByLabel('Search titles').fill(title);
    await page.getByRole('link', { name: `Edit ${title}` }).click();
    await expect(field(page, 'Title')).toHaveValue(title);
  };
  const dialog = page.getByRole('alertdialog', { name: 'Leave without saving?' });
  await open();
  await field(page, 'Title').fill(`${title} edited`);
  await page.getByRole('link', { name: 'Back to events' }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Stay and keep editing' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(field(page, 'Title')).toHaveValue(`${title} edited`);

  // Back from the browser: the step is held (it never completes), so it is asked for, not awaited.
  await page.evaluate(() => window.history.back());
  await expect(dialog).toBeVisible();
  await expect(page).toHaveURL(/\/admin\/events\/edit\//); // held: still on the editor
  await expect(field(page, 'Title')).toHaveValue(`${title} edited`);
  await dialog.getByRole('button', { name: 'Leave and discard changes' }).click();
  await expect(page).toHaveURL(new RegExp(`${LIST}`));

  await open();
  await field(page, 'Title').fill(`${title} saved`);
  await save(page).click();
  await expect(save(page)).toBeDisabled();
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`${LIST}`));
  await expect(dialog).toHaveCount(0);
  expect((await apiGet(page, event.id)).texts.en?.title).toBe(`${title} saved`);
});

test('a viewer sees published events on an internal calendar, never its drafts', async ({
  page,
  browser,
}) => {
  const sfx = uniqueSlug('vw').replace(/-/g, '');
  const email = await apiViewer(page, sfx);
  const calendar = await apiCalendar(page, `Internal ${sfx}`, 'internal');
  const shown = await apiPublished(page, calendar, `Shown ${sfx}`);
  const hidden = await apiEvent(page, calendar, `Hidden ${sfx}`);
  const context = await browser.newContext({ timezoneId: NEW_YORK });
  const viewer = await context.newPage();
  watch(viewer, problems);
  await login(viewer, { email, password: 'changeme1' });
  await viewer.goto(LIST);
  await expect(row(viewer, `Shown ${sfx}`)).toBeVisible();
  await expect(row(viewer, `Hidden ${sfx}`)).toHaveCount(0);
  expect((await viewer.request.get(`/api/events/events/${shown.id}`)).status()).toBe(200);
  expect((await viewer.request.get(`/api/events/events/${hidden.id}`)).status()).toBe(404);
  await context.close();
});

test('the list and editor read German and switch back', async ({ page, context }) => {
  const title = `Deutsch ${uniqueSlug('ev')}`;
  const event = await apiPublished(page, await freshCalendar(page), title);
  const origin = new URL('/', page.url()).toString();
  await context.addCookies([{ name: 'locale', value: 'de', url: origin }]);
  await page.goto(LIST);
  await expect(page.getByRole('heading', { name: 'Veranstaltungen', level: 1 })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Neue Veranstaltung' })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Titel' })).toBeVisible();
  await page.goto(edit(event.id));
  await expect(page.getByRole('button', { name: 'Veröffentlichung zurückziehen' })).toBeVisible();
  await expect(field(page, 'Veranstaltungsort')).toBeVisible();

  await context.addCookies([{ name: 'locale', value: 'en', url: origin }]);
  await page.goto(LIST);
  await expect(page.getByRole('heading', { name: 'Events', level: 1 })).toBeVisible();
  await apiAct(page, event.id, 'unpublish');
});
