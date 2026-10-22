import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import { apiCreateRecord, apiCreateType, uniqueTypeKey } from './records-helpers';

/**
 * Records follows the active organisation, the same one pages and news do
 * (#112): the admin API and screens bind the tenant the framework resolved
 * from the membership, not the user's own `tenant_id`.
 *
 *   admin creates org A → creates a type and a record there → creates org B
 *   (now active) → neither the API nor the screen knows the type → switches
 *   back to A → both are there again.
 *
 * Multi-tenant only, like billing-tenant and news-tenant:
 *
 *   E2E_MULTI_TENANT=1 npx playwright test records-tenant
 */

test.skip(!process.env.E2E_MULTI_TENANT, 'needs E2E_MULTI_TENANT=1 (multi-tenant host)');

type Tenant = { id: string; slug: string };

/** Create an organisation; creating one also makes it the active one. */
async function createOrg(page: Page, name: string): Promise<Tenant> {
  const created = await page.request.post('/api/tenants/', { data: { name } });
  expect(created.status(), await created.text()).toBe(201);
  return (await created.json()) as Tenant;
}

async function switchTo(page: Page, org: Tenant): Promise<void> {
  const switched = await page.request.post(`/api/tenants/${org.id}/switch`);
  expect(switched.status(), await switched.text()).toBe(204);
}

async function typeKeys(page: Page): Promise<string[]> {
  const res = await page.request.get('/api/records/types', {
    headers: { Accept: 'application/json' },
  });
  expect(res.status(), await res.text()).toBe(200);
  return ((await res.json()) as { items: { key: string }[] }).items.map((t) => t.key);
}

/** The record list screen: says which tenant it is in, and links the record. */
async function expectListed(page: Page, key: string, uuid: string, org: Tenant): Promise<void> {
  await page.goto(`/admin/records/${key}`);
  await expect(page.getByText(`Tenant: ${org.id}`)).toBeVisible();
  await expect(page.locator(`a[href="/admin/records/${key}/${uuid}"]`).first()).toBeVisible();
}

test("one organisation's records are not another's", async ({ page }) => {
  await login(page);
  const stamp = Date.now();
  const orgA = await createOrg(page, `Records A ${stamp}`);

  const key = uniqueTypeKey('tenant');
  await apiCreateType(page, {
    key,
    label: 'Tenant thing',
    label_plural: 'Tenant things',
    fields: [{ key: 'title', type: 'text', label: 'Title' }],
  });
  const record = await apiCreateRecord(page, key, { data: { title: 'Only in A' } });
  expect(await typeKeys(page)).toContain(key);
  await expectListed(page, key, record.uuid, orgA);

  // Org B, now the active one: the type and its record do not exist here.
  await createOrg(page, `Records B ${stamp}`);
  expect(await typeKeys(page)).not.toContain(key);
  const detail = await page.request.get(`/api/records/types/${key}/records/${record.uuid}`, {
    headers: { Accept: 'application/json' },
  });
  expect(detail.status()).toBe(404);
  const screen = await page.goto(`/admin/records/${key}`);
  expect(screen?.status()).toBe(404);

  // Back in A, it is there again: B's view was scoping, not loss.
  await switchTo(page, orgA);
  expect(await typeKeys(page)).toContain(key);
  await expectListed(page, key, record.uuid, orgA);
});
