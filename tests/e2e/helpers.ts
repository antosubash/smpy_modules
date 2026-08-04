import { expect, type Page } from '@playwright/test';

import { TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD } from '../../playwright.config';

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
