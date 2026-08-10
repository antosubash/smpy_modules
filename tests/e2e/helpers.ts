import { expect, type Locator, type Page } from '@playwright/test';

import { TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD } from '../../playwright.config';

/**
 * Click an action guarded by `ConfirmDialog` and confirm it.
 *
 * These used to be `window.confirm`, driven with `page.once('dialog', …)`.
 * They are Radix alert dialogs now: the trigger and the confirm button carry
 * the same label, so the confirm has to be scoped to the dialog itself.
 */
export async function clickAndConfirm(
  page: Page,
  trigger: Locator,
  label: RegExp | string = /^delete$/i,
) {
  await trigger.click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: label }).click();
  await expect(dialog).toHaveCount(0);
}

/**
 * Read the pagebuilder CSRF cookie the admin middleware mirrors for
 * the JS client, after touching an admin page so the cookie exists.
 * Pass the logged-in `page` so cookies + session share a jar.
 */
export async function csrfHeader(page: Page): Promise<Record<string, string>> {
  await page.goto('/pagebuilder/');
  const cookies = await page.context().cookies();
  const token = cookies.find((c) => c.name === 'pagebuilder_csrf')?.value;
  expect(token, 'expected pagebuilder_csrf cookie after admin GET').toBeTruthy();
  return { 'X-CSRF-Token': decodeURIComponent(token!) };
}

/**
 * Publish from the editor through the note dialog that replaced the
 * publish prompt. An empty `note` publishes without recording one.
 */
export async function publishWithNote(page: Page, note = '') {
  await page.getByRole('button', { name: /^publish$/i }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  if (note) await dialog.getByRole('textbox').fill(note);
  await dialog.getByRole('button', { name: /^publish$/i }).click();
  await expect(dialog).toHaveCount(0);
}

/** Open the publish dialog and back out of it — nothing should be published. */
export async function cancelPublish(page: Page) {
  await page.getByRole('button', { name: /^publish$/i }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: /^cancel$/i }).click();
  await expect(dialog).toHaveCount(0);
}

export const ADMIN_EMAIL = TEST_ADMIN_EMAIL;
export const ADMIN_PASSWORD = TEST_ADMIN_PASSWORD;

export async function login(
  page: Page,
  { email = ADMIN_EMAIL, password = ADMIN_PASSWORD }: { email?: string; password?: string } = {},
) {
  await page.goto('/users/login');
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await Promise.all([
    page.waitForURL((url) => !url.pathname.startsWith('/users/login'), { timeout: 15_000 }),
    page.getByRole('button', { name: /log in/i }).click(),
  ]);
}

export async function logout(page: Page) {
  // The session is cleared via POST /api/users/auth/logout. We hit the
  // logout view route (/users/logout) which clears the cookie + session.
  await page.request.post('/users/logout', {
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
  });
}

export function uniqueSlug(prefix = 'e2e-page') {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}
