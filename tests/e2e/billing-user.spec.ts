import { type Browser, expect, type Page, test } from '@playwright/test';

import { login, moduleCsrfHeader } from './helpers';

/**
 * Billing in `user` mode (#274): every signed-in user is their own billing
 * subject (`user:<uuid>`), on a single-tenant host.
 *
 *   a plain user opens Billing and sees the default plan and their own usage →
 *   the admin assigns them a plan on Subscriptions, which lists them by email →
 *   the user sees it → the admin's own Billing is untouched.
 *
 * `subject_mode` is read once at boot, so this runs against its own host
 * (start-test-server.sh sets it; CI's `E2E (billing per user)` job):
 *
 *   E2E_BILLING_USER=1 npx playwright test billing-user
 *
 * The default suite ignores this file (playwright.config.ts). Stands alone: it
 * creates its own user and plan.
 */

test.skip(!process.env.E2E_BILLING_USER, 'needs E2E_BILLING_USER=1 (billing subject_mode=user)');

const COUNTER = 'demo.exports';
const ADMIN_API = '/api/billing/admin';

async function createPlainUser(admin: Page, stamp: number) {
  const email = `billing-user-${stamp}@example.com`;
  const password = 'changeme1';
  const created = await admin.request.post('/api/users/admin', {
    headers: { 'content-type': 'application/json' },
    // The framework's ordinary role: user mode maps billing's permissions onto it.
    data: { email, password, role_names: ['user'] },
  });
  expect(created.status(), await created.text()).toBe(201);
  const users = (await (await admin.request.get('/api/users/admin?per_page=100')).json()) as {
    id: string;
    email: string;
  }[];
  const id = users.find((u) => u.email === email)?.id;
  expect(id, 'the user just created should be listed').toBeTruthy();
  return { id: id as string, email, password };
}

/** The Current plan card's title: the plan in force (the plan list repeats names). */
const currentPlan = (page: Page) => page.locator('[data-slot="card-title"]').first();

async function planName(page: Page) {
  const status = await page.request.get('/api/billing/status');
  expect(status.status(), await status.text()).toBe(200);
  return ((await status.json()) as { plan: { name: string } }).plan.name;
}

async function signedIn(browser: Browser, who: { email: string; password: string }) {
  const page = await (await browser.newContext()).newPage();
  await login(page, who);
  return page;
}

test('a user is billed as themselves, and an admin assigns them a plan', async ({
  page,
  browser,
}) => {
  await login(page);
  const stamp = Date.now();
  const user = await createPlainUser(page, stamp);
  const subject = `user:${user.id}`;

  // A plan limiting the demo counter, and two units of usage on the user's
  // own subject (the admin's Adjust takes any existing user in this mode).
  const headers = await moduleCsrfHeader(page, '/admin/billing/usage');
  const personal = `Personal ${stamp}`;
  const plan = await page.request.post(`${ADMIN_API}/plans`, {
    headers,
    data: {
      key: `personal-${stamp}`,
      name: personal,
      pricing_model: 'free',
      limits: { [COUNTER]: 10 },
    },
  });
  expect(plan.status(), await plan.text()).toBe(201);
  const adjusted = await page.request.post(`${ADMIN_API}/usage/${subject}/adjust`, {
    headers,
    data: { meter: COUNTER, quantity: 2, reason: 'e2e user usage' },
  });
  expect(adjusted.status(), await adjusted.text()).toBe(200);

  // The plain user opens Billing: the default plan, and their own usage — not
  // the `default` subject's, where start-test-server.sh seeded three.
  const member = await signedIn(browser, user);
  try {
    await member.goto('/billing/');
    await expect(member.getByRole('heading', { name: 'Billing' })).toBeVisible();
    await expect(currentPlan(member)).toContainText('Free');
    expect(await planName(member)).toBe('Free');
    const counter = member.getByTestId('usage-card').locator(`[data-meter="${COUNTER}"]`);
    await expect(counter).toContainText('2 used');

    // The admin's Subscriptions screen lists users by email; assign by hand.
    // Searched for: the list is paged, so the user may sit on a later page.
    await page.goto(`/admin/billing/subscriptions?q=${encodeURIComponent(user.email)}`);
    await expect(page.getByRole('columnheader', { name: 'User' })).toBeVisible();
    const row = page.getByRole('row', { name: new RegExp(user.email) });
    await row.getByRole('button', { name: 'Assign plan' }).click();
    const assign = page.getByRole('dialog');
    await assign.getByLabel('Plan').selectOption({ label: personal });
    await assign.getByRole('button', { name: 'Assign' }).click();
    await expect(page.getByText(`Plan assigned to ${user.email}`)).toBeVisible();
    await expect(row).toContainText(personal);

    // The user reloads and has it, with the plan's limit on their usage.
    await member.reload();
    await expect(currentPlan(member)).toContainText(personal);
    expect(await planName(member)).toBe(personal);
    await expect(counter).toContainText('2 of 10');
  } finally {
    await member.context().close();
  }

  // The admin's own Billing is the admin's subject: still the default plan,
  // and none of the user's usage.
  await page.goto('/billing/');
  await expect(page.getByRole('heading', { name: 'Billing' })).toBeVisible();
  await expect(currentPlan(page)).toContainText('Free');
  expect(await planName(page)).toBe('Free');
  await expect(page.locator(`[data-meter="${COUNTER}"]`)).toHaveCount(0);
});

test('the Subscriptions list pages past 50 users, keeping the search', async ({ page }) => {
  await login(page);
  const stamp = Date.now();
  const post = async (email: string) => {
    const created = await page.request.post('/api/users/admin', {
      headers: { 'content-type': 'application/json' },
      data: { email, password: 'changeme1', role_names: ['user'] },
    });
    expect(created.status(), await created.text()).toBe(201);
  };
  // The search target always exists; top up so the list cannot fit one page,
  // whatever other specs left.
  const target = `pager-${stamp}-00`;
  await post(`${target}@example.com`);
  const listed = await page.request.get('/api/users/admin?per_page=100');
  expect(listed.status(), await listed.text()).toBe(200);
  const missing = Math.max(0, 52 - ((await listed.json()) as unknown[]).length);
  for (let i = 1; i <= missing; i++) {
    await post(`pager-${stamp}-${String(i).padStart(2, '0')}@example.com`);
  }

  await page.goto('/admin/billing/subscriptions');
  await expect(page.getByText(/^Showing 1–50 of \d+/)).toBeVisible();
  await expect(page.locator('tbody tr')).toHaveCount(50);
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.getByText(/^Showing 51–/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Previous' })).toBeEnabled();

  // A search goes back to page 1 and keeps the pager out of a short result.
  await page.locator('#subscriptions-search').fill(target);
  await page.getByRole('button', { name: 'Search' }).click();
  await expect(page).not.toHaveURL(/page=/);
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Next' })).toHaveCount(0);
});
