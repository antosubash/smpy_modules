import { expect, test } from '@playwright/test';

import { clickAndConfirm, login } from './helpers';

/**
 * Billing's platform-admin screens on the default (manual-provider) host:
 * create a plan through the editor, see the editor's own validation, archive
 * it, and check the Stripe secret is never echoed back.
 */

test.describe('Billing admin', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('create, validate and archive a plan', async ({ page }) => {
    const key = `team-${Date.now()}`;
    await page.goto('/admin/billing/plans');
    await expect(page.getByRole('heading', { name: 'Billing' })).toBeVisible();
    await expect(page.getByRole('cell', { name: /Free/ }).first()).toBeVisible();

    await page.getByRole('button', { name: 'New plan' }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Key').fill(key);
    await dialog.getByLabel('Name').fill('Team E2E');
    await dialog.getByLabel('Pricing').selectOption('flat');
    await dialog.getByRole('button', { name: 'Create plan' }).click();
    await expect(dialog.getByRole('alert')).toHaveText(/needs at least one Stripe price/);

    await dialog.getByLabel('Stripe price ID (monthly)').fill(`price_${key}`);
    await dialog.getByLabel('Monthly amount (display)').fill('19');
    await dialog.getByRole('button', { name: /tenants\.seats/ }).click();
    await dialog.getByLabel('Limit for tenants.seats').fill('3');
    await dialog.getByRole('button', { name: 'Create plan' }).click();
    await expect(page.getByText('Plan created')).toBeVisible();
    await expect(dialog).toHaveCount(0);

    const row = page.getByRole('row', { name: new RegExp(key) });
    await expect(row).toContainText('€19.00 / month');
    await expect(row).toContainText('3');

    await clickAndConfirm(page, row.getByRole('button', { name: 'Archive' }), /^archive$/i);
    await expect(row).toContainText('Archived');
  });

  test('subscriptions screen lists organisations under the manual provider', async ({ page }) => {
    await page.goto('/admin/billing/subscriptions');
    await expect(page.getByText(/Assign plans by hand; nobody is charged/)).toBeVisible();
    await expect(page.getByLabel('Status')).toBeVisible();
  });

  test('stripe secret is stored masked', async ({ page }) => {
    await page.goto('/admin/billing/connection');
    await expect(page.getByText('The manual provider is active')).toBeVisible();
    await expect(page.getByText(/\/billing\/webhooks\/stripe/)).toBeVisible();
    await page.getByLabel('Secret key (sk_…)').fill('sk_test_e2e_secret');
    await page.getByRole('button', { name: 'Save connection' }).click();
    await expect(page.getByText('Stripe connection saved')).toBeVisible();
    await page.reload();
    const field = page.getByLabel('Secret key (sk_…)');
    await expect(field).toHaveValue('');
    await expect(field).toHaveAttribute('placeholder', /leave blank to keep/);
    expect(await page.content()).not.toContain('sk_test_e2e_secret');
  });
});
