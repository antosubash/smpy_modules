import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, publishWithNote, uniqueSlug } from './helpers';

/**
 * The admin shell below 900px — screen 2i.
 *
 * The design's rule: drag-and-drop layout needs width, so the canvas goes
 * read-only and everything that does not need width stays. These tests are
 * mostly about that boundary holding in both directions — the canvas really is
 * withheld when narrow, and really is still there when not.
 */

const PHONE = { width: 390, height: 844 };

const BLOCKS = [
  { type: 'Heading', props: { id: 'b-head', text: 'Canopy survey', level: 'h2', align: 'left' } },
  { type: 'Text', props: { id: 'b-text', text: 'Plot 14 was resurveyed in March.' } },
  { type: 'Quote', props: { id: 'b-quote', quote: 'The trees are fine.' } },
];

async function makePage(page: Page, slug: string): Promise<number> {
  const headers = await csrfHeader(page);
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: {
      title: 'Narrow editing',
      slug,
      draft_data: {
        root: { props: { title: 'Narrow editing', width: 'contained' } },
        content: BLOCKS,
        zones: {},
      },
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  return (await created.json()).id as number;
}

/** The block types listed in the outline, top to bottom.
 *
 * `evaluateAll` does not auto-wait, so an empty list would otherwise be
 * indistinguishable from a list that has not rendered yet.
 */
async function outlineOrder(page: Page): Promise<string[]> {
  const items = page.getByTestId('block-outline').locator('li');
  await expect(items.first()).toBeAttached();
  return items.evaluateAll((rows) => rows.map((li) => li.getAttribute('data-block-type') ?? ''));
}

/** The block types actually stored on the page's draft. */
async function storedOrder(page: Page, id: number): Promise<string[]> {
  const response = await page.request.get(`/api/pagebuilder/pages/${id}`);
  expect(response.ok(), await response.text()).toBeTruthy();
  const body = (await response.json()) as { draft_data?: { content?: { type: string }[] } };
  return (body.draft_data?.content ?? []).map((block) => block.type);
}

test.describe('The page editor below 900px', () => {
  test.use({ viewport: PHONE });

  test('withholds the canvas and offers the outline instead', async ({ page }) => {
    await login(page);
    const id = await makePage(page, uniqueSlug('narrow'));

    await page.goto(`/pagebuilder/${id}/edit`);

    await expect(page.getByText(/Preview and publish here, edit on a larger screen/)).toBeVisible();
    await expect(page.getByTestId('block-outline')).toBeVisible();
    // Puck mounts the canvas in an iframe. Not rendering it at all is the
    // point — a hidden one would still load the whole drag surface.
    await expect(page.locator('iframe')).toHaveCount(0);
  });

  test('names each block the way the palette does', async ({ page }) => {
    await login(page);
    const id = await makePage(page, uniqueSlug('narrow-names'));

    await page.goto(`/pagebuilder/${id}/edit`);

    const outline = page.getByTestId('block-outline');
    await expect(outline).toContainText('Heading');
    await expect(outline).toContainText('Quote');
    // And enough of the block's own content to tell two Headings apart.
    await expect(outline).toContainText('Canopy survey');
  });

  test('reorders a block without dragging, and the new order sticks', async ({ page }) => {
    await login(page);
    const id = await makePage(page, uniqueSlug('narrow-reorder'));

    await page.goto(`/pagebuilder/${id}/edit`);
    await expect(page.getByTestId('block-outline')).toBeVisible();
    expect(await outlineOrder(page)).toEqual(['Heading', 'Text', 'Quote']);

    await page.getByRole('button', { name: 'Move Heading down' }).click();
    expect(await outlineOrder(page)).toEqual(['Text', 'Heading', 'Quote']);

    await page.getByRole('button', { name: /save draft/i }).click();

    // Polled rather than waiting on one PUT: autosave fires its own, so the
    // first response to arrive is not necessarily the one carrying this edit.
    await expect
      .poll(() => storedOrder(page, id))
      .toEqual(['Text', 'Heading', 'Quote']);

    await page.reload();
    expect(await outlineOrder(page)).toEqual(['Text', 'Heading', 'Quote']);
  });

  test('does not offer a move past either end', async ({ page }) => {
    await login(page);
    const id = await makePage(page, uniqueSlug('narrow-ends'));

    await page.goto(`/pagebuilder/${id}/edit`);

    await expect(page.getByRole('button', { name: 'Move Heading up' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Move Quote down' })).toBeDisabled();
  });

  test('previews the draft rather than the published page', async ({ page }) => {
    await login(page);
    const id = await makePage(page, uniqueSlug('narrow-preview'));

    await page.goto(`/pagebuilder/${id}/edit`);
    const preview = page.getByRole('link', { name: /preview the draft/i });
    await expect(preview).toHaveAttribute('href', `/pagebuilder/${id}/preview`);

    // Follow it directly rather than through the new tab: what matters is that
    // the route renders this draft's body, not how the browser opened it.
    await page.goto(`/pagebuilder/${id}/preview`);
    await expect(page.getByText('Canopy survey')).toBeVisible();
    await expect(page.getByText('Plot 14 was resurveyed in March.')).toBeVisible();
  });

  test('still publishes', async ({ page }) => {
    await login(page);
    const id = await makePage(page, uniqueSlug('narrow-publish'));

    await page.goto(`/pagebuilder/${id}/edit`);
    await publishWithNote(page, 'Published from a phone');

    await expect(page.getByRole('link', { name: /^view$/i })).toBeVisible();
  });

  test('collapses the rail to a menu button', async ({ page }) => {
    await login(page);

    await page.goto('/pagebuilder/');

    await expect(page.getByRole('button', { name: /open sidebar/i })).toBeVisible();
  });
});

test.describe('The page editor at desktop width', () => {
  test('still gets the drag canvas', async ({ page }) => {
    await login(page);
    const id = await makePage(page, uniqueSlug('wide'));

    await page.goto(`/pagebuilder/${id}/edit`);

    // The other half of the boundary: without this, a bug that always took the
    // narrow branch would pass every test above.
    await expect(page.locator('iframe').first()).toBeAttached();
    await expect(page.getByTestId('block-outline')).toHaveCount(0);
    await expect(page.getByText(/edit on a larger screen/)).toHaveCount(0);
  });
});

test.describe('The layout editor below 900px', () => {
  test.use({ viewport: PHONE });

  test('outlines the header and footer instead of stacking two canvases', async ({ page }) => {
    await login(page);

    await page.goto('/pagebuilder/layout');

    await expect(page.getByText(/the canvases are read-only at this size/)).toBeVisible();
    await expect(page.locator('iframe')).toHaveCount(0);
    await expect(page.getByTestId('layout-header-slot')).toBeVisible();
    await expect(page.getByTestId('layout-footer-slot')).toBeVisible();
  });
});

test.describe('The article list below 900px', () => {
  test.use({ viewport: PHONE });

  test('keeps every row action reachable without a gesture', async ({ page }) => {
    await login(page);
    const slug = uniqueSlug('narrow-article');
    const pageId = await makePage(page, slug);
    const headers = await csrfHeader(page);
    const attached = await page.request.post('/api/news/articles', {
      headers,
      data: { page_id: pageId, category: 'Research', published_at: null },
    });
    expect(attached.ok(), await attached.text()).toBeTruthy();

    // Searched rather than trusting page 1 to still hold the newest row.
    await page.goto(`/news/?q=${slug}`);
    const row = page.locator(`[data-testid="article-row"][data-slug="${slug}"]`);
    await expect(row).toBeVisible();

    // The design moves these to a swipe or long-press. They wrap onto their own
    // line here instead: a gesture has no keyboard or screen-reader equivalent,
    // and nothing on screen would say it exists.
    await expect(row.getByRole('link', { name: /^edit$/i })).toBeVisible();
    await expect(row.getByRole('button', { name: /^detach$/i })).toBeVisible();
    await expect(row.getByRole('button', { name: /more actions/i })).toBeVisible();
  });

  test('does not push the page sideways', async ({ page }) => {
    await login(page);

    await page.goto('/news/');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
