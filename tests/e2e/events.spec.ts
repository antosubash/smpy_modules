import { expect, type Page, test } from '@playwright/test';

import { postCalendar } from './events-seed';
import { clickAndConfirm, login, uniqueSlug } from './helpers';

/**
 * The events console, end to end: sidebar, calendars (create, edit, visibility,
 * trash, restore), form validation, categories, sharing with a second user and
 * the German console.
 *
 * Standalone: every name is unique per run and each test seeds what it needs.
 */

const CALENDARS = '/admin/events/calendars';
const CATEGORIES = '/admin/events/categories';

let problems: string[] = [];

test.beforeEach(async ({ page }) => {
  problems = [];
  page.on('pageerror', (error) => problems.push(String(error)));
  page.on('console', (message) => {
    if (message.text().includes('Content Security Policy')) problems.push(message.text());
  });
  await login(page);
});

test.afterEach(() => {
  expect(problems).toEqual([]);
});

const row = (page: Page, text: string) => page.getByRole('row').filter({ hasText: text });

async function openNewCalendar(page: Page) {
  await page.goto(CALENDARS);
  await page.getByRole('button', { name: 'New calendar', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'New calendar' })).toBeVisible();
  return dialog;
}

test('the sidebar lists Events with Calendar, Calendars and Categories, and /admin/events/ is the calendar', async ({
  page,
}) => {
  await page.goto('/admin/events/');
  await expect(page).toHaveURL(/\/admin\/events\/(\?.*)?$/);
  await expect(page.getByRole('heading', { name: 'Calendar', level: 1 })).toBeVisible();
  const sidebar = page.locator('aside');
  await expect(sidebar.getByText('Events', { exact: true }).first()).toBeVisible();
  await expect(sidebar.locator('a[href^="/admin/events"]').first()).toHaveAttribute(
    'href',
    '/admin/events/',
  );
  // Named apart from News' "Categories", which news-admin.spec.ts finds by name.
  await expect(
    sidebar.locator(`a[href="${CALENDARS}"]`).getByText('Calendars', { exact: true }),
  ).toBeVisible();
  await expect(
    sidebar.locator(`a[href="${CATEGORIES}"]`).getByText('Event categories', { exact: true }),
  ).toBeVisible();
});

test('create, edit, change visibility, trash and restore a calendar', async ({ page }) => {
  const sfx = uniqueSlug('cal');
  const name = `Team ${sfx}`;
  const dialog = await openNewCalendar(page);
  await dialog.getByLabel('Name', { exact: true }).fill(name);
  await dialog.getByLabel('Colour').fill('#16a34a');
  await dialog.getByLabel('Description').fill('Shared team events');
  await dialog.getByLabel('Timezone').fill('Europe/Vienna');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(row(page, name)).toContainText('Private');
  await expect(row(page, name)).toContainText('Europe/Vienna');

  const renamed = `${name} renamed`;
  await page.getByRole('button', { name: `Edit ${name}`, exact: true }).click();
  const edit = page.getByRole('dialog');
  await expect(edit.getByRole('heading', { name: 'Edit calendar' })).toBeVisible();
  await edit.getByLabel('Name', { exact: true }).fill(renamed);
  await edit.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(row(page, renamed)).toBeVisible();

  await page.getByRole('button', { name: `Change visibility of ${renamed}` }).click();
  const visibility = page.getByRole('dialog');
  await visibility.getByLabel('Visibility', { exact: true }).selectOption('internal');
  await visibility.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(row(page, renamed)).toContainText('Internal');

  await clickAndConfirm(
    page,
    page.getByRole('button', { name: `Move ${renamed} to trash` }),
    'Move to trash',
    async (confirm) => {
      await expect(confirm).toContainText(renamed);
    },
  );
  await expect(row(page, renamed)).toHaveCount(0);
  await page.getByRole('button', { name: 'Trash', exact: true }).click();
  await expect(row(page, renamed)).toBeVisible();
  await page.getByRole('button', { name: `Restore ${renamed}` }).click();
  await expect(row(page, renamed)).toHaveCount(0);
  await page.getByRole('button', { name: 'Active', exact: true }).click();
  await expect(row(page, renamed)).toContainText('Internal');
});

test('calendar form validation: empty name, bad timezone, taken slug', async ({ page }) => {
  const existing = `Taken ${uniqueSlug('cal')}`;
  const { slug } = await postCalendar(page, { name: existing });

  const dialog = await openNewCalendar(page);
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  const nameField = dialog.getByLabel('Name', { exact: true });
  await expect(nameField).toHaveAccessibleDescription('This field is required.');
  await expect(nameField).toBeFocused();

  await nameField.fill(`Zone ${uniqueSlug('cal')}`);
  const zone = dialog.getByLabel('Timezone');
  await zone.fill('Mars/Phobos');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(zone).toHaveAccessibleDescription(
    'Choose a timezone from the list, for example Europe/Vienna.',
  );
  await expect(zone).toHaveAttribute('aria-invalid', 'true');

  await zone.fill('Europe/Vienna');
  await nameField.fill(`Dup ${uniqueSlug('cal')}`);
  await dialog.getByLabel('Slug (optional)').fill(slug);
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog.getByText('That slug is already in use.')).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(row(page, slug)).toHaveCount(1);
});

test('create, edit and delete a category', async ({ page }) => {
  const name = `Workshop ${uniqueSlug('cat')}`;
  await page.goto(CATEGORIES);
  await expect(page.getByRole('heading', { name: 'Categories', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'New category', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog
    .getByLabel(/^Name \(/)
    .first()
    .fill(name);
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(row(page, name)).toBeVisible();

  const renamed = `${name} v2`;
  await page.getByRole('button', { name: `Edit ${name}`, exact: true }).click();
  const edit = page.getByRole('dialog');
  await expect(edit.getByLabel('Slug', { exact: true })).toHaveAttribute('readonly', '');
  await edit
    .getByLabel(/^Name \(/)
    .first()
    .fill(renamed);
  await edit.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(row(page, renamed)).toBeVisible();

  await clickAndConfirm(
    page,
    page.getByRole('button', { name: `Delete ${renamed}` }),
    /^delete$/i,
    async (confirm) => {
      await expect(confirm).toContainText(renamed);
    },
  );
  await expect(row(page, renamed)).toHaveCount(0);
});

test('share a calendar: masked addresses, exact-address lookup, grant and revoke', async ({
  page,
}) => {
  const sfx = uniqueSlug('shr').replace(/-/g, '');
  const fullName = `Mira Quokka ${sfx}`;
  const email = `events-share-${sfx}@example.com`;
  const created = await page.request.post('/api/users/admin', {
    headers: { 'content-type': 'application/json' },
    data: { email, password: 'changeme1', full_name: fullName, role_names: [] },
  });
  expect(created.status(), await created.text()).toBe(201);
  const calendar = `Shared ${sfx}`;
  await postCalendar(page, { name: calendar });

  await page.goto(CALENDARS);
  await page.getByRole('button', { name: `Share ${calendar}`, exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Not shared with anyone yet.')).toBeVisible();
  const search = dialog.getByLabel('Find a person');
  const candidate = dialog.getByRole('button', { name: `Share with ${fullName}` });

  await search.fill(`Quokka ${sfx}`);
  await expect(candidate).toBeVisible();
  await expect(dialog).toContainText(`e***@example.com`);
  await expect(dialog).not.toContainText(email);

  await search.fill(`events-share-${sfx}`);
  await expect(dialog.getByText('No one found.')).toBeVisible();
  await expect(candidate).toHaveCount(0);

  await search.fill(email);
  await expect(candidate).toBeVisible();
  await expect(dialog).toContainText(email);

  await dialog.getByLabel('Access').selectOption('view');
  await candidate.click();
  const grants = dialog.getByRole('region', { name: 'Shared with' });
  await expect(grants).toContainText(`${fullName} · Can view`);

  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: `Share ${calendar}`, exact: true }).click();
  const reopened = page.getByRole('dialog');
  await expect(reopened.getByRole('region', { name: 'Shared with' })).toContainText(fullName);

  await reopened.getByRole('button', { name: `Remove access for ${fullName}` }).click();
  await expect(reopened.getByText('Not shared with anyone yet.')).toBeVisible();
  await expect(reopened.getByRole('region', { name: 'Shared with' })).not.toContainText(fullName);
});

test('the calendars screen reads German and switches back', async ({ page, context }) => {
  const origin = new URL('/', page.url()).toString();
  await context.addCookies([{ name: 'locale', value: 'de', url: origin }]);
  await page.goto(CALENDARS);
  await expect(page.getByRole('heading', { name: 'Kalender', level: 1 })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Neuer Kalender', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Papierkorb', exact: true })).toBeVisible();
  await expect(page.getByRole('columnheader', { name: 'Sichtbarkeit' })).toBeVisible();

  await context.addCookies([{ name: 'locale', value: 'en', url: origin }]);
  await page.goto(CALENDARS);
  await expect(page.getByRole('heading', { name: 'Calendars', level: 1 })).toBeVisible();
  await expect(page.getByRole('button', { name: 'New calendar', exact: true })).toBeVisible();
});
