import { expect, type Locator, test } from '@playwright/test';

import { seedArticle } from './article-helpers';
import { login } from './helpers';

/**
 * The contents list and the section anchors, in a browser.
 *
 * Both halves of this feature are things `vitest` cannot see. It runs in a
 * node environment with no DOM, so the unit tests around `blocks/outline.ts`
 * check the derivation — which heading gets which anchor — by calling the
 * functions directly. What they cannot check is the two places that derivation
 * has to survive:
 *
 *  - Puck's `metadata`. `Contents` lists blocks it is not allowed to see, so
 *    the outline reaches it through `<Puck metadata>`, a store input rather
 *    than a prop. Whether a store write actually re-renders a block mid-edit
 *    is a claim about `@puckeditor/core`, and reading its bundle is not the
 *    same as running it.
 *  - The reader's browser. A section link is resolved before React has drawn
 *    the heading it names, and without a real document there is nothing to
 *    scroll and nothing to miss. This is the failure that leaves no trace —
 *    the article renders perfectly, at the wrong scroll position.
 *
 * The third test is the seam between them: an anchor that works on the canvas
 * and not on the published page would be invisible to either side on its own.
 */

const CONTENTS_LABEL = 'In this article';

/**
 * A display date for every article seeded here.
 *
 * Not decoration. `seedArticle` leaves `published_at` null, and the admin list
 * floats undated articles to the top — that is the work-in-progress pile an
 * author came back to finish — twenty rows to a page. Four more undated
 * articles is enough to push a dated one off the first page, and
 * `news-fresh-session` asserts that the article it just created is on it.
 * Dating these keeps that pile the length the rest of the suite found it.
 *
 * Worth reading before copying this file as a template for a new spec: the
 * failure does not land here. It lands in whatever file happens to assert on
 * the first page of the admin list, which the author of the new spec will not
 * have touched and will have no reason to suspect. Date anything you seed
 * unless being undated is the thing under test.
 */
const SEED_DATE = '2026-02-11T00:00:00Z';
const LOREM =
  'The plots were surveyed on foot over three weeks, with two observers walking ' +
  'each transect independently so the counts could be compared before anything ' +
  'was written down.';

function heading(id: string, text: string, level: '2' | '3' = '2') {
  return { type: 'Heading', props: { id, text, level } };
}

function paragraph(id: string, text = LOREM) {
  return { type: 'Paragraph', props: { id, text, lead: false } };
}

/** Enough prose that the published article is several screens tall — without
 *  it, "scrolled to the right heading" and "did not scroll at all" look the
 *  same, because everything fits on one screen either way. */
function filler(id: string, count: number) {
  return Array.from({ length: count }, (_, i) => paragraph(`${id}-${i}`));
}

/** A body that opens with a `Contents` block over the blocks given. */
function contentsBody(content: Record<string, unknown>[]) {
  return {
    root: { props: { title: 'Contents' } },
    content: [
      { type: 'Contents', props: { id: 'toc', title: CONTENTS_LABEL, depth: '2' } },
      ...content,
    ],
    zones: {},
  };
}

/** The `#anchor`s the contents list points at, in the order it lists them. */
function hrefsOf(nav: Locator): Promise<string[]> {
  return nav.locator('a').evaluateAll((els) => els.map((el) => el.getAttribute('href') ?? ''));
}

/** The `id`s the headings actually render, in document order. */
function idsOf(headings: Locator): Promise<string[]> {
  return headings.evaluateAll((els) => els.map((el) => el.id));
}

test.describe('Contents and section anchors', () => {
  test('the contents list follows the headings as they are edited', async ({ page }) => {
    await login(page);
    const { articleId } = await seedArticle(page, {
      prefix: 'toc-live',
      publishedAt: SEED_DATE,
      body: contentsBody([
        heading('h-a', 'The survey'),
        paragraph('p-a'),
        heading('h-b', 'How it was done'),
        paragraph('p-b'),
        heading('h-c', 'What it found'),
      ]),
    });

    await page.goto(`/admin/news/articles/${articleId}/body`);
    // Puck renders the canvas in an iframe, so the document is behind it.
    const canvas = page.frameLocator('#preview-frame');
    const nav = canvas.locator(`nav[aria-label="${CONTENTS_LABEL}"]`);
    await expect(nav).toBeVisible();
    expect(await hrefsOf(nav)).toEqual(['#the-survey', '#how-it-was-done', '#what-it-found']);

    // A value a reload would wipe out. Everything below has to happen without
    // one — "the list updates after a save and a refresh" is the behaviour
    // this block was written to avoid, and it would pass every other
    // assertion here.
    await page.evaluate(() => {
      (window as unknown as { canvasMark?: string }).canvasMark = 'live';
    });

    // Rename a section from the inspector, the way a writer does.
    await canvas.getByRole('heading', { name: 'How it was done' }).click();
    const text = page.getByRole('textbox', { name: 'Text' });
    await expect(text).toHaveValue('How it was done');
    await text.fill('How we did it');

    await expect(nav.getByRole('link', { name: 'How we did it' })).toHaveAttribute(
      'href',
      '#how-we-did-it',
    );
    await expect(nav.getByRole('link', { name: 'How it was done' })).toHaveCount(0);
    // The other half of the same edit: the heading has to move its own id to
    // match, or the entry that just updated now points at nothing.
    await expect(canvas.locator('h2#how-we-did-it')).toHaveText('How we did it');

    // Deleting a section takes it out of the list too.
    await canvas.getByRole('heading', { name: 'What it found' }).click();
    await canvas.getByRole('button', { name: 'Delete' }).click();
    await expect(nav.getByRole('link')).toHaveCount(2);
    expect(await hrefsOf(nav)).toEqual(['#the-survey', '#how-we-did-it']);

    expect(
      await page.evaluate(() => (window as unknown as { canvasMark?: string }).canvasMark),
    ).toBe('live');
  });

  test('a heading duplicated on the canvas takes an anchor of its own', async ({ page }) => {
    // The case a counter gets wrong, driven through the editor rather than
    // asserted against `articleOutline` directly: two headings reading
    // "Background" have to end up at two addresses, and the contents list has
    // to point one entry at each — decided live, while the second one is being
    // created.
    await login(page);
    const { articleId } = await seedArticle(page, {
      prefix: 'toc-dup',
      publishedAt: SEED_DATE,
      body: contentsBody([
        heading('h-a', 'Background'),
        paragraph('p-a'),
        heading('h-b', 'What we found'),
      ]),
    });

    await page.goto(`/admin/news/articles/${articleId}/body`);
    const canvas = page.frameLocator('#preview-frame');
    const nav = canvas.locator(`nav[aria-label="${CONTENTS_LABEL}"]`);
    await expect(nav).toBeVisible();

    await canvas.getByRole('heading', { name: 'Background' }).click();
    await canvas.getByRole('button', { name: 'Duplicate' }).click();

    await expect(nav.getByRole('link')).toHaveCount(3);
    expect(await hrefsOf(nav)).toEqual(['#background', '#background-2', '#what-we-found']);
    // And the copy is a heading at that second address — not a second element
    // wearing the first one's id, which is what a document with two identical
    // headings gets when the anchor is derived from the text alone.
    expect(await idsOf(canvas.locator('h2[id]'))).toEqual([
      'background',
      'background-2',
      'what-we-found',
    ]);
  });

  test('the canvas and the published article agree on every anchor', async ({ page }) => {
    // A contents link that resolves on the canvas and lands nowhere on the
    // published page is the characteristic failure of deriving the outline
    // twice. Nothing else in the suite compares the two screens; each one only
    // ever checks that it agrees with itself.
    //
    // The headings are chosen to be the hard case: "Background", "Background"
    // and "Background 2" all reach for `background-2`, so the two screens have
    // to run the same disambiguation in the same order to end up in the same
    // place.
    await login(page);
    const { articleId, url } = await seedArticle(page, {
      prefix: 'toc-agree',
      publishedAt: SEED_DATE,
      publish: true,
      body: contentsBody([
        heading('h-a', 'Background'),
        paragraph('p-a'),
        heading('h-b', 'Background'),
        paragraph('p-b'),
        heading('h-c', 'Background 2'),
        paragraph('p-c'),
      ]),
    });

    await page.goto(`/admin/news/articles/${articleId}/body`);
    const canvas = page.frameLocator('#preview-frame');
    const canvasNav = canvas.locator(`nav[aria-label="${CONTENTS_LABEL}"]`);
    await expect(canvasNav).toBeVisible();
    const canvasHrefs = await hrefsOf(canvasNav);
    const canvasIds = await idsOf(canvas.locator('h2[id]'));

    await page.goto(url);
    const publicNav = page.locator(`nav[aria-label="${CONTENTS_LABEL}"]`);
    await expect(publicNav).toBeVisible();
    const publicHrefs = await hrefsOf(publicNav);
    const publicIds = await idsOf(page.locator('h2[id]'));

    // Spelled out as well as compared: two screens that had both drifted the
    // same way would still be equal to each other.
    expect(canvasHrefs).toEqual(['#background', '#background-2', '#background-2-2']);
    expect(publicHrefs).toEqual(canvasHrefs);
    expect(canvasIds).toEqual(['background', 'background-2', 'background-2-2']);
    expect(publicIds).toEqual(canvasIds);
  });

  test('arriving with a #section link lands on that section', async ({ page }) => {
    // The reader-facing outcome behind `useAnchorOnArrival` in
    // `PublicArticle`: a shared section link has to put the reader at that
    // section, on an article whose body React draws after the fragment has
    // already been resolved.
    //
    // What this asserts is the outcome, not the hook. Removing the hook does
    // not fail this test: Chromium keeps a pending fragment scroll and
    // re-applies it when the element appears, even when the page module is
    // held back for seconds past load. So the hook is belt-and-braces here,
    // and no Chromium-only spec can pin it. The outcome is still worth
    // watching — it is what breaks silently when an anchor stops rendering,
    // and it is the half of the contents feature no unit test can reach.
    await login(page);
    const { url } = await seedArticle(page, {
      prefix: 'toc-anchor',
      titlePrefix: 'Anchored',
      publishedAt: SEED_DATE,
      publish: true,
      body: contentsBody([
        heading('h-a', 'The survey'),
        ...filler('f-a', 8),
        heading('h-b', 'How it was done'),
        ...filler('f-b', 8),
        heading('h-c', 'What it found'),
        ...filler('f-c', 8),
      ]),
    });

    await page.goto(`${url}#what-it-found`);
    await expect(page.locator('h2#what-it-found')).toBeInViewport();
    // Two more assertions because "in the viewport" alone would also hold for
    // an article short enough to fit on one screen: the page moved, and it
    // moved far enough to leave the headline behind.
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    await expect(page.getByRole('heading', { level: 1 })).not.toBeInViewport();

    // The other way a reader reaches a section: from the contents list, on a
    // page that is already open. This one is the browser's own anchor
    // handling rather than the hook — which is the point. It only works
    // because the `href` the list rendered and the `id` the heading rendered
    // are the same string in the same document.
    await page.goto(url);
    await expect(page.getByRole('heading', { level: 1 })).toBeInViewport();
    await page
      .locator(`nav[aria-label="${CONTENTS_LABEL}"]`)
      .getByRole('link', { name: 'How it was done' })
      .click();
    await expect(page.locator('h2#how-it-was-done')).toBeInViewport();
    await expect(page.getByRole('heading', { level: 1 })).not.toBeInViewport();
  });
});
