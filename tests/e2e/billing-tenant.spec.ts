import { expect, test } from '@playwright/test';

import { login } from './helpers';

/**
 * The tenant side of billing, end to end on the manual provider:
 *
 *   admin creates a 1-seat plan → assigns it to an organisation → the
 *   organisation's billing page shows it → inviting a second member is
 *   refused by the tenants module with the plan's limit → "unpaid" suspends.
 *
 * Needs an active organisation, so it only runs with multi-tenancy on. News is
 * left out because its startup reconcile does not yet run under strict
 * tenant isolation (the framework's module-adoption work, not billing's):
 *
 *   E2E_MULTI_TENANT=1 SM_MODULES_ENABLED='["Ai","Auth","Billing","Branding",
 *     "Dashboard","FileStorage","PageBuilder","Permissions","Records","Settings",
 *     "Tenants","Users"]' npx playwright test billing-tenant
 */

test.skip(!process.env.E2E_MULTI_TENANT, 'needs E2E_MULTI_TENANT=1 (multi-tenant host)');

test('a plan assigned by an admin is what the organisation gets', async ({ page }) => {
  await login(page);
  const stamp = Date.now();

  // An organisation the admin owns (self-service is on by default).
  const created = await page.request.post('/api/tenants/', { data: { name: `Org ${stamp}` } });
  expect(created.status(), await created.text()).toBe(201);
  const tenant = (await created.json()) as { id: string };

  // A one-seat plan. The owner already fills it.
  await page.goto('/admin/billing/plans');
  await page.getByRole('button', { name: 'New plan' }).click();
  const editor = page.getByRole('dialog');
  await editor.getByLabel('Key').fill(`solo-${stamp}`);
  await editor.getByLabel('Name').fill(`Solo ${stamp}`);
  await editor.getByRole('button', { name: /tenants\.seats/ }).click();
  await editor.getByLabel('Limit for tenants.seats').fill('1');
  await editor.getByRole('button', { name: 'Create plan' }).click();
  await expect(page.getByText('Plan created')).toBeVisible();

  // Assign it by hand.
  await page.goto('/admin/billing/subscriptions');
  const row = page.getByRole('row', { name: new RegExp(`Org ${stamp}`) });
  await row.getByRole('button', { name: 'Assign plan' }).click();
  const assign = page.getByRole('dialog');
  await assign.getByLabel('Plan').selectOption({ label: `Solo ${stamp}` });
  await assign.getByRole('button', { name: 'Assign' }).click();
  await expect(page.getByText(`Plan assigned to Org ${stamp}`)).toBeVisible();
  await expect(row).toContainText(`Solo ${stamp}`);

  // The organisation sees it.
  await page.goto('/billing/');
  await expect(page.getByRole('heading', { name: 'Billing' })).toBeVisible();
  await expect(page.getByText('1 of 1 seat used')).toBeVisible();
  await expect(page.getByText(/Online payment is not set up here/)).toBeVisible();

  // And the tenants module enforces it: a second member does not fit.
  const invite = await page.request.post('/api/tenants/current/invitations', {
    data: { email: `extra-${stamp}@example.com` },
  });
  expect(invite.status()).toBe(402);
  expect((await invite.json()).key).toBe('tenants.seats');

  // "Unpaid" suspends the organisation; "Active" lifts it again.
  await page.goto('/admin/billing/subscriptions');
  await row.getByRole('button', { name: 'Assign plan' }).click();
  await assign.getByLabel('Status').selectOption('unpaid');
  await assign.getByRole('button', { name: 'Assign' }).click();
  await expect(row).toContainText('Suspended (unpaid)');

  // The owner can still open billing, pay-only. With no payment provider
  // there is nothing to pay through, so it says who to contact instead.
  await page.goto('/billing/');
  await expect(page.getByText('This organisation is suspended for non-payment')).toBeVisible();
  await expect(page.getByText(/Contact the site administrator/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Pay now' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Plans' })).toBeHidden();

  await page.goto('/admin/billing/subscriptions');
  await row.getByRole('button', { name: 'Assign plan' }).click();
  await assign.getByLabel('Status').selectOption('active');
  await assign.getByRole('button', { name: 'Assign' }).click();
  await expect(row).not.toContainText('Suspended');
  expect(tenant.id).toBeTruthy();
});
