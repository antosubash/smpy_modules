import { expect, type Page, test } from '@playwright/test';

import { login, moduleCsrfHeader } from './helpers';

/**
 * Usage metering's screens (#99): the admin Usage tab and the tenant's usage
 * card, against the demo host's meters (`host/demo_meters.py`).
 *
 * The admin half runs on the single-tenant host, where everything is metered
 * as the `default` tenant and `scripts/seed_usage.py` (run by
 * start-test-server.sh) has left three counter consumes and three gauge holds.
 * Its assertions are relative to what it finds, so a retry against the same
 * database still holds.
 *
 * The card needs an active organisation, so that half runs only with
 * multi-tenancy on (CI's `E2E (multi-tenant)` job):
 *
 *   E2E_MULTI_TENANT=1 npx playwright test billing-usage
 */

const COUNTER = 'demo.exports';
const GAUGE = 'demo.jobs';
const ADMIN_API = '/api/billing/admin';

async function openUsageTab(page: Page) {
  await page.goto('/admin/billing/subscriptions');
  await page
    .getByRole('navigation', { name: 'Billing administration' })
    .getByRole('link', { name: 'Usage' })
    .click();
  await expect(page).toHaveURL(/\/admin\/billing\/usage/);
  await expect(page.getByRole('heading', { name: 'Billing' })).toBeVisible();
}

test.describe('admin usage tab', () => {
  test.skip(!!process.env.E2E_MULTI_TENANT, 'meters the single-tenant host’s default tenant');

  test('release a hold, recount the gauge, adjust the counter with a reason', async ({ page }) => {
    await login(page);
    await openUsageTab(page);
    const rowFor = (meter: string) => page.getByRole('row').filter({ hasText: meter });
    await expect(rowFor(COUNTER)).toContainText('default');
    await expect(rowFor(GAUGE)).toContainText('Gauge');

    // The meter filter narrows the table to the gauge.
    await page.getByLabel('Meter', { exact: true }).selectOption(GAUGE);
    await expect(page).toHaveURL(/meter=demo\.jobs/);
    await expect(rowFor(COUNTER)).toHaveCount(0);

    await rowFor(GAUGE).getByRole('button', { name: 'Details' }).click();
    const drawer = page.getByRole('dialog', { name: /Usage of default/ });
    await expect(drawer.getByRole('heading', { name: 'Open holds' })).toBeVisible();
    const release = drawer.getByRole('button', { name: 'Release' });
    await expect(release.first()).toBeVisible();
    const before = await release.count();

    await release.first().click();
    await expect(page.getByText('Hold released')).toBeVisible();
    await expect(release).toHaveCount(before - 1);

    await drawer.getByRole('button', { name: `Recount ${GAUGE}` }).click();
    await expect(page.getByText(`${GAUGE} recounted: ${before - 1} in use.`)).toBeVisible();

    // Adjust needs a reason; the correction lands on the ledger with it.
    const reason = `e2e credit ${Date.now()}`;
    await drawer.getByRole('button', { name: 'Adjust' }).click();
    const adjust = page.getByRole('dialog', { name: `Adjust ${COUNTER}` });
    await adjust.getByLabel('Quantity').fill('-1');
    await adjust.getByRole('button', { name: 'Record adjustment' }).click();
    await expect(adjust.getByText('A reason is required.')).toBeVisible();
    await adjust.getByLabel('Reason').fill(reason);
    await adjust.getByRole('button', { name: 'Record adjustment' }).click();
    await expect(page.getByText(new RegExp(`${COUNTER} adjusted: -?\\d+ used\\.`))).toBeVisible();
    await expect(adjust).toBeHidden();
    // Focus goes back to what opened the dialog, not to the top of the page.
    await expect(drawer.getByRole('button', { name: 'Adjust' })).toBeFocused();

    await drawer.getByLabel('Meter', { exact: true }).selectOption(COUNTER);
    await drawer.getByLabel('Kind').selectOption('adjust');
    const entry = drawer.getByRole('row').filter({ hasText: reason });
    await expect(entry).toContainText('Adjusted');
    await expect(entry).toContainText('-1');

    // Closing the drawer returns focus to the row's Details button.
    await page.keyboard.press('Escape');
    await expect(drawer).toBeHidden();
    await expect(rowFor(GAUGE).getByRole('button', { name: 'Details' })).toBeFocused();
  });
});

test.describe('tenant usage card', () => {
  test.skip(!process.env.E2E_MULTI_TENANT, 'needs E2E_MULTI_TENANT=1 (an active organisation)');

  test('the organisation sees its usage against its plan', async ({ page }) => {
    await login(page);
    const stamp = Date.now();
    const name = `Metered ${stamp}`;
    const created = await page.request.post('/api/tenants/', { data: { name } });
    expect(created.status(), await created.text()).toBe(201);
    const tenant = (await created.json()) as { id: string };

    // A plan limiting both demo meters, assigned by hand (manual provider).
    const headers = await moduleCsrfHeader(page, '/admin/billing/usage');
    const plan = await page.request.post(`${ADMIN_API}/plans`, {
      headers,
      data: {
        key: `metered-${stamp}`,
        name: `Metered plan ${stamp}`,
        pricing_model: 'free',
        limits: { [COUNTER]: 10, [GAUGE]: 2 },
      },
    });
    expect(plan.status(), await plan.text()).toBe(201);
    const planId = ((await plan.json()) as { id: number }).id;
    const assigned = await page.request.post(`${ADMIN_API}/subscriptions/${tenant.id}/assign`, {
      headers,
      data: { plan_id: planId },
    });
    expect(assigned.status(), await assigned.text()).toBe(200);

    // Usage, through the admin's Adjust: 3 of the counter's 10.
    const adjusted = await page.request.post(`${ADMIN_API}/usage/${tenant.id}/adjust`, {
      headers,
      data: { meter: COUNTER, quantity: 3, reason: 'e2e usage' },
    });
    expect(adjusted.status(), await adjusted.text()).toBe(200);

    await page.goto('/billing/');
    const card = page.getByTestId('usage-card');
    await expect(card.getByText('Usage', { exact: true })).toBeVisible();
    const counter = card.locator(`[data-meter="${COUNTER}"]`);
    await expect(counter).toContainText('3 of 10');
    await expect(counter).toContainText(/Resets /);
    await expect(counter.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '30');
    const gauge = card.locator(`[data-meter="${GAUGE}"]`);
    await expect(gauge).toContainText('0 of 2');
    await expect(gauge).toContainText('In use now');

    // The admin sees the same numbers for that organisation.
    await openUsageTab(page);
    await page.getByLabel('Organisation').fill(name);
    await page.getByLabel('Organisation').press('Enter');
    const row = page.getByRole('row').filter({ hasText: name });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText('30%');
  });
});
