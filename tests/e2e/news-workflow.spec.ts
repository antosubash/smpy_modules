import { expect, test } from '@playwright/test';

import { seedArticle, shot, walkthroughBody } from './article-helpers';
import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * One article, start to finish, through the screens an author actually uses.
 *
 * Every other news spec proves one rule in isolation — that a filter survives a
 * reload, that a rename records a redirect, that a draft is not served. This
 * one exists because none of them prove the rules hold *together*: an author
 * creating an article, writing it, naming it, publishing it and reading it back
 * crosses six screens and four routers, and the seams between them are exactly
 * where a module that has just stopped depending on its neighbour is most
 * likely to have lost something. It found two such holes on its first run.
 *
 * It is also the run that produces the walkthrough screenshots, when
 * `WALKTHROUGH_SHOTS` names a directory. Assertions first; the pictures are a
 * by-product, which is why nothing here is arranged for the camera.
 */
test.describe('News — the full editorial workflow', () => {
  test.describe.configure({ mode: 'serial' });

  const headline = 'Sensor rollout reaches the north site';
  const renamed = 'Sensor rollout completes at the north site';
  const lead = 'The last of the canopy sensors went live this week, two months ahead of schedule.';

  let articleId: number;
  let slug: string;
  let firstSlug: string;

  test('an author creates an article from the sidebar', async ({ page }) => {
    await login(page);
    await page.goto('/dashboard/');

    // The leaf, not the group: "News" is the sidebar section holding Articles
    // and Categories.
    await page.getByRole('link', { name: 'Articles', exact: true }).click();
    await expect(page).toHaveURL(/\/news\/?$/);
    await shot(page, '01-admin-list');

    await page.getByRole('button', { name: 'New article' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    slug = uniqueSlug('walkthrough');
    firstSlug = slug;
    await dialog.getByLabel('Headline').fill(headline);
    // Typed rather than derived, so the rest of the walkthrough can address the
    // article by a slug it already holds.
    await dialog.getByLabel('URL').fill(slug);
    await dialog.getByLabel('Publish date').fill('2026-08-26');
    await shot(page, '02-new-article-dialog');

    // Creating opens the body canvas — one motion, not two.
    await dialog.getByRole('button', { name: /^create/i }).click();
    await page.waitForURL(/\/admin\/news\/articles\/\d+\/body$/);
    // Thrown rather than asserted with `!`: everything after this addresses the
    // article by id, and a NaN would fail eight tests later at a URL that looks
    // like a routing bug.
    const landed = page.url().match(/articles\/(\d+)\/body/);
    if (!landed) throw new Error(`Expected the body canvas, landed on ${page.url()}`);
    articleId = Number(landed[1]);

    await expect(page.getByTestId('article-body-title')).toHaveText(headline);
  });

  test('the body canvas saves what is written on it', async ({ page }) => {
    await login(page);

    // Blocks go in through the body API, which is the convention the rest of
    // this suite follows — Puck's palette is dnd-kit and dragging it under
    // Playwright is flaky enough to become the only thing this ever fails on.
    const headers = await csrfHeader(page);
    const seeded = await page.request.put(`/api/news/articles/${articleId}/body`, {
      headers,
      data: { draft_data: walkthroughBody(lead) },
    });
    expect(seeded.status(), await seeded.text()).toBe(200);

    await page.goto(`/admin/news/articles/${articleId}/body`);
    // Puck renders the canvas in an iframe, so the blocks are behind it.
    const canvas = page.frameLocator('#preview-frame');
    await expect(canvas.getByText(lead)).toBeVisible();
    await expect(canvas.getByRole('heading', { name: 'What changed' })).toBeVisible();
    await shot(page, '03-body-canvas');

    // Seeding proves nothing about whether *editing* saves, which is the part
    // worth driving through the real surface.
    await canvas.getByText('Placeholder body copy.').click();
    const text = page.getByRole('textbox', { name: 'Text' });
    await expect(text).toBeVisible();
    await text.fill('Coverage now spans all four plots, including the two added in June.');

    // Autosave is debounced, so this waits for the state the header reports
    // rather than for a fixed delay.
    await expect(page.getByText('Saved', { exact: true })).toBeVisible({ timeout: 15_000 });

    const detail = await (await page.request.get(`/api/news/articles/${articleId}/detail`)).json();
    expect(JSON.stringify(detail.draft_data)).toContain('including the two added in June');
  });

  test('the article screen owns everything except the body', async ({ page }) => {
    await login(page);
    await page.goto(`/admin/news/articles/${articleId}/edit`);

    await page.getByLabel('Author').fill('A. Subash');
    const tags = page.getByLabel('Add a tag');
    await tags.fill('sensors');
    await tags.press('Enter');
    await tags.fill('canopy');
    await tags.press('Enter');
    await page.getByLabel('Pin to the top of listings').check();
    await shot(page, '04-article-screen');

    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();

    const listed = await (await page.request.get(`/api/news/articles?q=${slug}`)).json();
    expect(listed.items[0].author).toBe('A. Subash');
    expect(listed.items[0].pinned).toBe(true);
    expect(listed.items[0].tags.sort()).toEqual(['canopy', 'sensors']);
  });

  test('renaming the article moves its address and forwards the old one', async ({ page }) => {
    // The headline and the URL are edited here, on the article screen. They
    // used to belong to a page, so this panel said "change it in the page
    // editor" — a screen that no longer exists, which left an article
    // unrenameable anywhere in the console.
    await login(page);
    await page.goto(`/admin/news/articles/${articleId}/edit`);

    const nextSlug = `${slug}-complete`;
    await page.getByLabel('Headline').fill(renamed);
    await page.getByLabel('URL', { exact: true }).fill(nextSlug);
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();

    slug = nextSlug;
    const listed = await (await page.request.get(`/api/news/articles?q=${slug}`)).json();
    expect(listed.items[0].title).toBe(renamed);
    expect(listed.items[0].slug).toBe(slug);
  });

  test('review, then publish', async ({ page }) => {
    await login(page);
    const headers = await csrfHeader(page);

    // Submit and approve have no screens yet — the console publishes directly.
    // They are driven over the API here so the walkthrough covers the path a
    // host that separates editors from publishers actually takes.
    const submitted = await page.request.post(`/api/news/articles/${articleId}/submit`, {
      headers,
      data: {},
    });
    expect(submitted.status(), await submitted.text()).toBe(200);
    expect((await submitted.json()).status).toBe('submitted_for_review');

    // Sent back with a note, which the canvas surfaces to the author.
    const rejected = await page.request.post(`/api/news/articles/${articleId}/reject`, {
      headers,
      data: { note: 'Add the plot count to the standfirst.' },
    });
    expect(rejected.status(), await rejected.text()).toBe(200);

    await page.goto(`/admin/news/articles/${articleId}/body`);
    await expect(page.getByText('Add the plot count to the standfirst.')).toBeVisible();
    await shot(page, '05-sent-back');

    await page.request.post(`/api/news/articles/${articleId}/submit`, { headers, data: {} });
    const approved = await page.request.post(`/api/news/articles/${articleId}/approve`, {
      headers,
      data: {},
    });
    expect(approved.status(), await approved.text()).toBe(200);
    expect((await approved.json()).status).toBe('published');
  });

  test('the article serves at its own address, with its own headers', async ({ page }) => {
    await login(page);
    const url = `/news/${slug}`;

    const served = await page.request.get(url);
    expect(served.status()).toBe(200);
    expect(served.headers().etag).toBeTruthy();
    expect(served.headers()['cache-control']).toContain('public');
    expect(await served.text()).toContain(lead);

    // A conditional request short-circuits on the same ETag.
    const conditional = await page.request.get(url, {
      headers: { 'If-None-Match': served.headers().etag },
    });
    expect(conditional.status()).toBe(304);

    // The address the article was created at still answers, one hop away.
    const moved = await page.request.get(`/news/${firstSlug}`, { maxRedirects: 0 });
    expect(moved.status()).toBe(301);
    expect(moved.headers().location).toBe(url);

    // It is not a page, so pagebuilder's prefix does not answer for it.
    expect((await page.request.get(`/p/${slug}`, { maxRedirects: 0 })).status()).toBe(404);

    // And it is in news' own sitemap, which is how it reaches a crawler now.
    expect(await (await page.request.get('/news/sitemap.xml')).text()).toContain(url);

    await page.goto(url);
    await expect(page.getByRole('heading', { name: renamed, level: 1 })).toBeVisible();

    // The palette renders through the viewer, not just on the canvas. These are
    // the blocks whose output is structural rather than a run of text, so a
    // config that registered them but rendered nothing would still pass every
    // assertion above.
    await expect(page.getByRole('table')).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Sensors' })).toBeVisible();
    await expect(page.getByText('What you need to know')).toBeVisible();
    await expect(page.getByText('Correction')).toBeVisible();
    await expect(page.getByText('How it went in')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Rollout report' })).toHaveAttribute(
      'href',
      'https://example.org/report',
    );
    // A source with nowhere to point is still a source.
    await expect(page.getByText('Interview, March 2024')).toBeVisible();

    await shot(page, '06-public-article');
  });

  test('an anonymous reader gets the article; a draft gets nothing', async ({ browser, page }) => {
    await login(page);
    const url = new URL(`/news/${slug}`, page.url()).toString();

    const anon = await browser.newContext();
    expect((await anon.request.get(url, { maxRedirects: 0 })).status()).toBe(200);

    // Taking it down takes it down for readers too — published_data is what is
    // served, and unpublishing stops serving it.
    const headers = await csrfHeader(page);
    await page.request.post(`/api/news/articles/${articleId}/unpublish`, { headers, data: {} });
    expect((await anon.request.get(url, { maxRedirects: 0 })).status()).toBe(404);
    await anon.close();

    // Every transition was recorded on the way here, in order. Listed
    // newest-first, so reversing it reads as the path the article took.
    //
    // There is no `publish` among them, and that is right: `approve` publishes
    // as one action — a reviewer who has to approve and then publish separately
    // eventually forgets the second half — so in the review path `approve` *is*
    // the event that put the article in front of readers.
    const revisions = await (
      await page.request.get(`/api/news/articles/${articleId}/revisions`)
    ).json();
    const events = (revisions as { event: string }[]).map((r) => r.event).reverse();
    expect(events).toEqual(['submit', 'reject', 'submit', 'approve', 'unpublish']);
  });

  test('the trash holds an article and gives it back', async ({ page }) => {
    await login(page);
    const headers = await csrfHeader(page);

    const trashed = await page.request.post(`/api/news/articles/${articleId}/trash`, {
      headers,
      data: {},
    });
    expect(trashed.status(), await trashed.text()).toBe(204);

    // Out of the list, and its address stops answering.
    const gone = await (await page.request.get(`/api/news/articles?q=${slug}`)).json();
    expect(gone.items).toHaveLength(0);
    expect((await page.request.get(`/news/${slug}`)).status()).toBe(404);

    const restored = await page.request.post(`/api/news/articles/${articleId}/restore`, {
      headers,
      data: {},
    });
    expect(restored.status(), await restored.text()).toBe(200);
    const back = await (await page.request.get(`/api/news/articles?q=${slug}`)).json();
    expect(back.items[0].title).toBe(renamed);
  });

  test('a second article is a second row, not a second page', async ({ page }) => {
    // The hazard the split removed: `page_id` pointed into a table this module
    // could not constrain, and SQLite reuses a deleted row's id — so deleting
    // one article's document re-attached its metadata to whatever was created
    // next. There is one row now, and deleting it deletes the article.
    await login(page);
    const doomed = await seedArticle(page, { prefix: 'walkthrough-second', publish: true });
    expect((await page.request.get(doomed.url)).status()).toBe(200);

    const headers = await csrfHeader(page);
    expect(
      (await page.request.delete(`/api/news/articles/${doomed.articleId}`, { headers })).status(),
    ).toBe(204);
    expect((await page.request.get(doomed.url)).status()).toBe(404);

    // The first article is untouched by the second's deletion.
    const survivors = await (await page.request.get(`/api/news/articles?q=${slug}`)).json();
    expect(survivors.items[0].id).toBe(articleId);
  });
});
