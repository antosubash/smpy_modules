import { expect, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * An article has its own public address.
 *
 * It used to share pagebuilder's generic page prefix, so every article on the
 * site sat at `/p/{slug}` beside the contact page and the privacy notice — the
 * URL said nothing about what the document was.
 *
 * Claiming the address means giving it up elsewhere, and that half only exists
 * end to end: the 404 at `/p` comes from pagebuilder's viewer consulting a
 * registry news writes to at startup, so nothing below the running app proves
 * the two modules are actually wired together.
 */
test.describe('News — the public article address', () => {
  test('serves at /news/{slug}, and no longer at /p/{slug}', async ({ page }) => {
    await login(page);
    const title = `Public address ${Date.now().toString(36)}`;
    const created = await page.request.post('/api/news/articles/with-page', {
      headers: await csrfHeader(page),
      data: { title, published_at: '2026-02-01T00:00:00Z' },
    });
    expect(created.status(), await created.text()).toBe(201);
    const article = await created.json();

    // The API reports the news address, not pagebuilder's.
    expect(article.url).toBe(`/news/${article.slug}`);

    await page.request.post(`/api/news/articles/${article.id}/publish`, {
      headers: await csrfHeader(page),
      data: {},
    });

    const served = await page.request.get(article.url);
    expect(served.status()).toBe(200);
    // Rendered by pagebuilder's viewer, so it keeps that module's public
    // headers rather than growing a second viewer that drifts from it.
    expect(served.headers().etag).toBeTruthy();
    expect(served.headers()['cache-control']).toContain('public');

    // And the address it gave up. 404 rather than a redirect: the two were
    // never equivalent, so there is no old address to forward from.
    const old = await page.request.get(`/p/${article.slug}`, { maxRedirects: 0 });
    expect(old.status()).toBe(404);
  });

  test('an ordinary page still serves at /p/{slug}', async ({ page }) => {
    // The claim moves one document's address; it must not shut the viewer off.
    await login(page);
    const headers = await csrfHeader(page);
    const slug = uniqueSlug('e2e-plain');
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers,
      data: { title: slug, slug, draft_data: { root: {}, content: [], zones: {} } },
    });
    const { id } = await created.json();
    await page.request.post(`/api/pagebuilder/pages/${id}/publish`, { headers, data: {} });

    expect((await page.request.get(`/p/${slug}`)).status()).toBe(200);
    // …and it is not an article, so the news prefix does not answer for it.
    expect((await page.request.get(`/news/${slug}`)).status()).toBe(404);
  });

  test('the sitemap advertises the address the article actually serves at', async ({ page }) => {
    // Without the claim reaching the sitemap, a crawler is pointed at the exact
    // URL the viewer now refuses.
    await login(page);
    const title = `Sitemap address ${Date.now().toString(36)}`;
    const created = await page.request.post('/api/news/articles/with-page', {
      headers: await csrfHeader(page),
      data: { title },
    });
    const article = await created.json();
    await page.request.post(`/api/news/articles/${article.id}/publish`, {
      headers: await csrfHeader(page),
      data: {},
    });

    const body = await (await page.request.get('/sitemap.xml')).text();

    expect(body).toContain(`/news/${article.slug}`);
    expect(body).not.toContain(`/p/${article.slug}`);
  });

  test('an anonymous reader can open an article', async ({ browser, page }) => {
    // The public prefix has to be exempt from AuthMiddleware, or every article
    // 302s a reader to the login screen — which would make the address useless.
    await login(page);
    const title = `Anonymous read ${Date.now().toString(36)}`;
    const created = await page.request.post('/api/news/articles/with-page', {
      headers: await csrfHeader(page),
      data: { title },
    });
    const article = await created.json();
    await page.request.post(`/api/news/articles/${article.id}/publish`, {
      headers: await csrfHeader(page),
      data: {},
    });

    const anon = await browser.newContext();
    const response = await anon.request.get(new URL(article.url, page.url()).toString(), {
      maxRedirects: 0,
    });
    expect(response.status()).toBe(200);
    await anon.close();
  });
});

test.describe('News — renaming an article', () => {
  test('the old address forwards to the new one', async ({ page }) => {
    // A rename is not a private edit: the old URL is already in bookmarks and
    // in a search index that has not recrawled. Pagebuilder records a redirect
    // for it, and the news address has to honour the same one — otherwise a
    // rename silently breaks every link already published to the article.
    await login(page);
    const headers = await csrfHeader(page);
    const title = `Renamed ${Date.now().toString(36)}`;
    const created = await page.request.post('/api/news/articles/with-page', {
      headers,
      data: { title },
    });
    const article = await created.json();
    const oldSlug = article.slug;
    const newSlug = `${oldSlug}-moved`;

    const renamed = await page.request.put(`/api/pagebuilder/pages/${article.page_id}`, {
      headers,
      data: { slug: newSlug },
    });
    expect(renamed.status(), await renamed.text()).toBe(200);
    await page.request.post(`/api/news/articles/${article.id}/publish`, {
      headers,
      data: {},
    });

    const moved = await page.request.get(`/news/${oldSlug}`, { maxRedirects: 0 });
    expect(moved.status()).toBe(301);
    expect(moved.headers().location).toBe(`/news/${newSlug}`);
    expect((await page.request.get(`/news/${newSlug}`)).status()).toBe(200);
  });
});
