import { type APIRequestContext, expect, type Page, test } from '@playwright/test';

import { paragraphBody, seedArticle } from './article-helpers';
import { login } from './helpers';

/**
 * News keeps each organisation's articles to itself, end to end.
 *
 *   admin creates org A → publishes an article there → creates org B → B's
 *   article list does not have it → B's public site answers 404 for its slug,
 *   while A's serves it.
 *
 * Multi-tenant only, like billing-tenant, and with every module enabled:
 *
 *   E2E_MULTI_TENANT=1 npx playwright test news-tenant
 *
 * The public half addresses each organisation by subdomain, which
 * `start-test-server.sh` turns on for multi-tenant runs (`subdomain_base` =
 * `localhost`). The subdomain goes in the Host header rather than the URL, so
 * the run does not depend on the machine resolving `*.localhost`.
 */

test.skip(!process.env.E2E_MULTI_TENANT, 'needs E2E_MULTI_TENANT=1 (multi-tenant host)');

type Tenant = { id: string; slug: string };

/** Create an organisation; creating one also makes it the active one. */
async function createOrg(page: Page, name: string): Promise<Tenant> {
  const created = await page.request.post('/api/tenants/', { data: { name } });
  expect(created.status(), await created.text()).toBe(201);
  return (await created.json()) as Tenant;
}

async function listedSlugs(page: Page): Promise<string[]> {
  const res = await page.request.get('/api/news/articles?limit=100', {
    headers: { Accept: 'application/json' },
  });
  expect(res.status(), await res.text()).toBe(200);
  return ((await res.json()) as { items: { slug: string }[] }).items.map((i) => i.slug);
}

/** An anonymous visitor's GET, on `<subdomain>.localhost` or plain localhost. */
function visit(request: APIRequestContext, host: string, path: string, subdomain?: string) {
  return request.get(path, {
    headers: subdomain ? { Host: `${subdomain}.${host}` } : {},
    maxRedirects: 0,
  });
}

const row = (page: Page, slug: string) =>
  page.locator(`[data-testid="article-row"][data-slug="${slug}"]`);

test("one organisation's article is not another's", async ({ page, request, baseURL }) => {
  await login(page);
  const stamp = Date.now();
  const { host } = new URL(baseURL ?? '');

  const orgA = await createOrg(page, `News A ${stamp}`);
  const article = await seedArticle(page, {
    prefix: 'tenant',
    titlePrefix: 'Tenant A',
    publishedAt: '2026-02-01T00:00:00Z',
    body: paragraphBody('Only organisation A publishes this.'),
    publish: true,
  });
  expect(await listedSlugs(page)).toContain(article.slug);
  await page.goto('/admin/news/');
  await expect(row(page, article.slug)).toBeVisible();

  // A's public site serves it to an anonymous visitor.
  const onA = await visit(request, host, article.url, orgA.slug);
  expect(onA.status()).toBe(200);
  expect(await onA.text()).toContain('Only organisation A publishes this.');

  // Org B, now the active one: neither the list nor the detail knows it.
  const orgB = await createOrg(page, `News B ${stamp}`);
  expect(await listedSlugs(page)).not.toContain(article.slug);
  const detail = await page.request.get(`/api/news/articles/${article.articleId}/detail`);
  expect(detail.status()).toBe(404);
  // Wait for the list's own fetch, so the empty assertion is not vacuous.
  const fetched = page.waitForResponse(
    (r) => new URL(r.url()).pathname === '/api/news/articles' && r.status() === 200,
  );
  await page.goto('/admin/news/');
  await fetched;
  await expect(row(page, article.slug)).toHaveCount(0);

  // B's public site answers 404 for the same slug, and so does a host that
  // names no organisation at all — there is no fallback tenant.
  expect((await visit(request, host, article.url, orgB.slug)).status()).toBe(404);
  expect((await visit(request, host, article.url)).status()).toBe(404);

  // Back in A, it is there again: B's view was scoping, not loss.
  const switched = await page.request.post(`/api/tenants/${orgA.id}/switch`);
  expect(switched.status(), await switched.text()).toBe(204);
  expect(await listedSlugs(page)).toContain(article.slug);
});
