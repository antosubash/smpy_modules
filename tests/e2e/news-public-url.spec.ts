import { expect, test } from '@playwright/test';

import { paragraphBody, seedArticle } from './article-helpers';
import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * An article has its own public address — and now its own viewer behind it.
 *
 * It used to share pagebuilder's generic page prefix, so every article on the
 * site sat at `/p/{slug}` beside the contact page and the privacy notice.
 * News took the *address* first while still handing the rendering back to that
 * module's viewer, which meant this file had a second job: proving the two
 * modules were wired together, because the 404 at `/p` came from pagebuilder
 * consulting a registry news wrote to at startup.
 *
 * That wiring is gone. An article is not a page, so there is no address to
 * claim back, no registry, and no hand-off. What is left to prove end to end is
 * that news' own viewer carries everything the borrowed one used to.
 */
test.describe('News — the public article address', () => {
  test('serves at /news/{slug}, with the headers a public URL needs', async ({ page }) => {
    await login(page);
    const { articleId, slug, url } = await seedArticle(page, {
      prefix: 'public-address',
      titlePrefix: 'Public address',
      publishedAt: '2026-02-01T00:00:00Z',
      body: paragraphBody('Read me at the news address.'),
      publish: true,
    });

    expect(url).toBe(`/news/${slug}`);

    const served = await page.request.get(url);
    expect(served.status()).toBe(200);
    // News' own viewer now, so these are its headers rather than a neighbour's.
    // They are asserted here precisely because a second viewer is exactly the
    // thing the old hand-off existed to avoid — if it drifts, it drifts here.
    expect(served.headers().etag).toBeTruthy();
    expect(served.headers()['cache-control']).toContain('public');
    expect(await served.text()).toContain('Read me at the news address.');

    // A conditional request short-circuits.
    const conditional = await page.request.get(url, {
      headers: { 'If-None-Match': served.headers().etag },
    });
    expect(conditional.status()).toBe(304);

    // And the article is not a page, so pagebuilder's prefix does not answer.
    const notAPage = await page.request.get(`/p/${slug}`, { maxRedirects: 0 });
    expect(notAPage.status()).toBe(404);

    // Nor is a draft served. Published-only is the whole point of the split
    // between draft_data and published_data.
    const headers = await csrfHeader(page);
    await page.request.post(`/api/news/articles/${articleId}/unpublish`, { headers, data: {} });
    expect((await page.request.get(url)).status()).toBe(404);
  });

  test('an ordinary page still serves at /p/{slug}', async ({ page }) => {
    // The two modules own separate prefixes over separate tables. Neither
    // answers for the other, and this is the half that used to need a claim.
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
    expect((await page.request.get(`/news/${slug}`)).status()).toBe(404);
  });

  test('news publishes a sitemap of its own', async ({ page }) => {
    // Articles used to reach a crawler through pagebuilder's sitemap, because
    // they were pages in it. They are not, so without one of news' own the
    // whole archive would silently drop out of every index.
    await login(page);
    const { slug } = await seedArticle(page, {
      prefix: 'sitemap-address',
      titlePrefix: 'Sitemap address',
      publish: true,
    });

    const body = await (await page.request.get('/news/sitemap.xml')).text();

    expect(body).toContain(`/news/${slug}`);
  });

  test('an anonymous reader can open an article', async ({ browser, page }) => {
    // The public prefix has to be exempt from AuthMiddleware, or every article
    // 302s a reader to the login screen — which would make the address useless.
    await login(page);
    const { url } = await seedArticle(page, {
      prefix: 'anonymous-read',
      titlePrefix: 'Anonymous read',
      publish: true,
    });

    const anon = await browser.newContext();
    const response = await anon.request.get(new URL(url, page.url()).toString(), {
      maxRedirects: 0,
    });
    expect(response.status()).toBe(200);
    await anon.close();
  });
});

test.describe('News — renaming an article', () => {
  test('the old address forwards to the new one', async ({ page }) => {
    // A rename is not a private edit: the old URL is already in bookmarks and
    // in a search index that has not recrawled. This used to be pagebuilder's
    // redirect table, read by news because the slug being renamed was a page's;
    // news keeps its own now, and the behaviour has to survive the move.
    await login(page);
    const headers = await csrfHeader(page);
    const { articleId, slug: oldSlug } = await seedArticle(page, {
      prefix: 'renamed',
      titlePrefix: 'Renamed',
      publish: true,
    });
    const newSlug = `${oldSlug}-moved`;

    // Renamed through news' own API — there is no page to rename.
    const renamed = await page.request.put(`/api/news/articles/${articleId}`, {
      headers,
      data: { slug: newSlug },
    });
    expect(renamed.status(), await renamed.text()).toBe(200);

    const moved = await page.request.get(`/news/${oldSlug}`, { maxRedirects: 0 });
    expect(moved.status()).toBe(301);
    expect(moved.headers().location).toBe(`/news/${newSlug}`);
    expect((await page.request.get(`/news/${newSlug}`)).status()).toBe(200);
  });
});
