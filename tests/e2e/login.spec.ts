import { expect, test } from '@playwright/test';

import { ADMIN_EMAIL, ADMIN_PASSWORD, login, logout } from './helpers';

test.describe('Authentication', () => {
  test('unauthenticated visits are redirected to the login page', async ({ page }) => {
    await page.goto('/pagebuilder/');
    await expect(page).toHaveURL(/\/users\/login/);
    await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  });

  test('login page renders the expected form fields', async ({ page }) => {
    await page.goto('/users/login');
    await expect(page.getByLabel('Email')).toBeVisible();
    await expect(page.getByLabel('Password', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: /log in/i })).toBeVisible();
  });

  test('rejects bad credentials', async ({ page }) => {
    await page.goto('/users/login');
    await page.getByLabel('Email').fill('nobody@example.com');
    await page.getByLabel('Password', { exact: true }).fill('wrong-password');
    await page.getByRole('button', { name: /log in/i }).click();
    await expect(page.getByText('Invalid email or password.')).toBeVisible();
    await expect(page).toHaveURL(/\/users\/login/);
  });

  test('bootstrapped admin can log in and reach the dashboard', async ({ page }) => {
    await login(page, { email: ADMIN_EMAIL, password: ADMIN_PASSWORD });
    await expect(page).not.toHaveURL(/\/users\/login/);
    // login_redirect_url defaults to /dashboard/. The dashboard module
    // ships its own page; we only assert the URL to stay decoupled from
    // its exact copy.
    await expect(page).toHaveURL(/\/(dashboard|)\/?$/);
  });

  test('logout clears the session and protects /pagebuilder again', async ({ page }) => {
    await login(page);
    await logout(page);
    await page.goto('/pagebuilder/');
    await expect(page).toHaveURL(/\/users\/login/);
  });
});
