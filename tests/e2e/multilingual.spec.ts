import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * A page published in two languages.
 *
 * The module suites cover the model, the routing and the API. What only
 * exists end to end is the thing a reader actually meets: that the German
 * page is the *same page* — same site chrome, same block structure, same
 * geometry — with different words in it. A translation that quietly rendered
 * without the header, or at a different width, would pass every unit test in
 * the repo.
 */

/** Geometry + element tree of a region, with the words deliberately left out. */
async function shape(page: Page, selector: string) {
  return page.locator(selector).evaluate((el) => {
    const box = el.getBoundingClientRect();
    const walk = (n: Element): unknown => ({
      tag: n.tagName,
      cls: n.className,
      kids: Array.from(n.children).map(walk),
    });
    return { width: box.width, height: box.height, left: box.left, tree: walk(el) };
  });
}

function doc(heading: string, body: string) {
  return {
    root: { props: { title: heading, width: 'full' } },
    content: [
      { type: 'Heading', props: { id: 'h1', text: heading, level: 'h1', align: 'left' } },
      { type: 'Text', props: { id: 't1', text: body, size: 'lg', align: 'left' } },
    ],
    zones: {},
  };
}

/**
 * Give the site a header and a footer.
 *
 * `PublicPage` only renders the `site-header` / `site-footer` landmarks when
 * the site-wide layout record holds one, and that record starts empty on a
 * fresh database. Set here rather than leaned on from `site-chrome.spec.ts`:
 * the chrome is the thing this test is comparing across languages, so it has
 * to be this file's own precondition, not another file's leftover.
 */
async function putLayout(page: Page, headers: Record<string, string>, chrome: boolean) {
  // An empty `content` is how a slot reads as unset — `public_layout_props`
  // drops the wrapper entirely rather than render an empty <header>.
  const slot = (block: unknown) => ({
    root: { props: {} },
    zones: {},
    content: chrome ? [block] : [],
  });
  const response = await page.request.put('/api/pagebuilder/layout', {
    headers,
    data: {
      header_data: slot({
        type: 'SiteHeader',
        props: {
          id: 'hdr',
          logoUrl: '',
          logoAlt: 'E2E Site',
          homeHref: '/p/home',
          utilityLinks: [],
          navItems: [{ label: 'Atlas', href: '/p/atlas', children: [] }],
          ctaLabel: 'Contact us',
          ctaHref: '/p/contact',
          sticky: false,
        },
      }),
      footer_data: slot({
        type: 'SiteFooter',
        props: {
          id: 'ftr',
          logoUrl: '',
          logoAlt: 'E2E Site',
          homeHref: '/p/home',
          links: [{ label: 'Privacy notice', href: '/p/privacy' }],
          note: 'A small print line.',
        },
      }),
      note: 'e2e multilingual chrome',
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
}

test.describe('Multilingual pages', () => {
  // The layout is one site-wide record shared by every spec, so put it back
  // the way this file found it. Otherwise every later spec that loads a public
  // page renders it with a header it did not ask for.
  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage();
    await login(page);
    await putLayout(page, await csrfHeader(page), false);
    await page.close();
  });

  test('a translation renders identically to its source, in the other language', async ({
    page,
  }) => {
    await login(page);
    const headers = await csrfHeader(page);
    await putLayout(page, headers, true);
    const slug = uniqueSlug('e2e-lang');

    const en = await (
      await page.request.post('/api/pagebuilder/pages', {
        headers,
        data: { title: 'About us', slug, draft_data: doc('About us', 'The English body.') },
      })
    ).json();

    const created = await page.request.post(`/api/pagebuilder/pages/${en.id}/translations`, {
      headers,
      data: { locale: 'de', title: 'Über uns' },
    });
    expect(created.status(), await created.text()).toBe(201);
    const de = await created.json();
    // The slug is reused: unique per language, so it does not collide.
    expect(de.slug).toBe(slug);

    await page.request.put(`/api/pagebuilder/pages/${de.id}`, {
      headers,
      data: { title: 'Über uns', draft_data: doc('Über uns', 'Der deutsche Text.') },
    });
    for (const id of [en.id, de.id]) {
      const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
        headers,
        data: {},
      });
      expect(published.status(), await published.text()).toBe(200);
    }

    await page.setViewportSize({ width: 1440, height: 900 });

    await page.goto(`/p/${slug}`);
    await expect(page.getByRole('heading', { name: 'About us' })).toBeVisible();
    const enHeader = await shape(page, '[data-testid="site-header"]');
    const enFooter = await shape(page, '[data-testid="site-footer"]');
    const enMain = await shape(page, 'main');

    await page.goto(`/de/p/${slug}`);
    await expect(page.getByRole('heading', { name: 'Über uns' })).toBeVisible();

    // Same site layout, applied to every locale — not a second, drifting copy.
    expect(await shape(page, '[data-testid="site-header"]')).toEqual(enHeader);
    expect(await shape(page, '[data-testid="site-footer"]')).toEqual(enFooter);

    // And the body: same blocks, same width, same offset. Only the words move.
    const deMain = await shape(page, 'main');
    expect(deMain.tree).toEqual(enMain.tree);
    expect(deMain.width).toBe(enMain.width);
    expect(deMain.left).toBe(enMain.left);
  });

  test('each language advertises the other, and the default keeps its address', async ({
    page,
  }) => {
    await login(page);
    const headers = await csrfHeader(page);
    const slug = uniqueSlug('e2e-alt');

    const en = await (
      await page.request.post('/api/pagebuilder/pages', {
        headers,
        data: { title: 'Alternates', slug, draft_data: doc('Alternates', 'Body.') },
      })
    ).json();
    const de = await (
      await page.request.post(`/api/pagebuilder/pages/${en.id}/translations`, {
        headers,
        data: { locale: 'de' },
      })
    ).json();
    for (const id of [en.id, de.id]) {
      const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
        headers,
        data: {},
      });
      expect(published.status(), await published.text()).toBe(200);
    }

    await page.goto(`/p/${slug}`);
    // Inertia writes the head client-side, so it is not there at `load`.
    // `evaluateAll` does not retry — without a wait that resolves to `[]` and
    // the assertion below reports "no alternates" for a page that has three.
    const links = page.locator('link[rel="alternate"]');
    await expect(links).toHaveCount(3);
    const alternates = await links.evaluateAll((found) =>
      found.map((l) => [
        l.getAttribute('hreflang'),
        new URL(l.getAttribute('href') ?? '').pathname,
      ]),
    );
    // Every member names every other, itself included, plus x-default —
    // an hreflang set is only honoured when it is reciprocal.
    expect(alternates).toEqual([
      ['de', `/de/p/${slug}`],
      ['en', `/p/${slug}`],
      ['x-default', `/p/${slug}`],
    ]);

    // The default locale's redundant prefix forwards rather than serving a
    // second copy of the same document.
    const redundant = await page.request.get(`/en/p/${slug}`, { maxRedirects: 0 });
    expect(redundant.status()).toBe(301);
    expect(redundant.headers().location).toBe(`/p/${slug}`);
  });

  test('the page list can duplicate a page into another language', async ({ page }) => {
    // The whole point of the row action: an author who thinks "we need this in
    // German" while scanning the list should not have to open the page, find
    // Settings and then find a tab.
    await login(page);
    const headers = await csrfHeader(page);
    const slug = uniqueSlug('e2e-dup');
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers,
      data: { title: 'Duplicate me', slug, draft_data: doc('Duplicate me', 'Original body.') },
    });
    const en = await created.json();

    await page.goto('/pagebuilder/?view=list');
    await page.getByTestId(`translate-page-${en.id}`).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    // Only the languages the page does not have yet are on offer.
    await expect(dialog.getByLabel('Language')).toHaveValue('de');
    await expect(dialog.getByText(`/de/p/${slug}`)).toBeVisible();

    await Promise.all([
      page.waitForURL(/\/pagebuilder\/\d+\/edit/),
      dialog.getByRole('button', { name: /create and open editor/i }).click(),
    ]);

    // It landed in the new page, and the content came with it.
    const id = Number(page.url().match(/\/pagebuilder\/(\d+)\/edit/)?.[1]);
    expect(id).not.toBe(en.id);
    const detail = await (await page.request.get(`/api/pagebuilder/pages/${id}`)).json();
    expect(detail.locale).toBe('de');
    expect(detail.slug).toBe(slug);
    expect(detail.status).toBe('draft');
    expect(detail.draft_data.content).toEqual(en.draft_data.content);
    expect(detail.translation_group).toBe(en.translation_group);
  });
});
