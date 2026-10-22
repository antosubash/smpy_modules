/**
 * Pages seeded through the API (#65) carrying Markdown seeded from existing
 * content (#66): the create call keeps its nav flags and meta title, and the
 * published page renders images, linked images and nested lists instead of
 * literal markup.
 */

import { expect, test } from '@playwright/test';

import { login, moduleCsrfHeader, uniqueSlug } from './helpers';

const CONTENT = [
  '## Partners',
  '',
  '![Acme logo](https://example.com/acme.png) [![Globex logo](https://example.com/globex.png)](https://globex.example) ![bad](javascript:alert(1))',
  '',
  '- Gold',
  '  - Acme',
  '    - EU office',
  '- Silver',
  '',
  '3. Plan',
  '4. Build',
  '   - Test',
].join('\n');

test.describe('Pagebuilder Markdown seeded through the API', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('keeps the create fields and renders images and nested lists', async ({ page }) => {
    const slug = uniqueSlug('md-seed');
    const headers = await moduleCsrfHeader(page, '/pagebuilder/');
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers,
      data: {
        title: `Partners ${slug}`,
        slug,
        meta_title: 'Our partners',
        show_in_header_nav: true,
        show_in_footer: true,
        draft_data: {
          root: { props: {} },
          content: [{ type: 'Markdown', props: { id: 'md-1', content: CONTENT } }],
        },
      },
    });
    expect(created.status(), await created.text()).toBe(201);
    const { id } = await created.json();

    const stored = await (await page.request.get(`/api/pagebuilder/pages/${id}`)).json();
    expect(stored).toMatchObject({
      meta_title: 'Our partners',
      show_in_header_nav: true,
      show_in_footer: true,
    });

    const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, { headers });
    expect(published.ok(), await published.text()).toBe(true);

    await page.goto(`/p/${slug}`);
    const main = page.locator('main');
    await expect(main.locator('img[alt="Acme logo"]')).toHaveAttribute(
      'src',
      'https://example.com/acme.png',
    );
    await expect(main.locator('a[href="https://globex.example"] img')).toHaveAttribute(
      'alt',
      'Globex logo',
    );
    // An unsafe source stays visible text rather than becoming an <img>.
    await expect(main.getByText('![bad](javascript:alert(1))')).toBeVisible();
    await expect(main.locator('img[src^="javascript"]')).toHaveCount(0);

    await expect(main.locator('li > ul > li', { hasText: 'Acme' })).toBeVisible();
    await expect(main.locator('li > ul > li > ul > li')).toHaveText('EU office');

    // Numbered items, keeping the first number, with a bullet nested inside.
    const ordered = main.locator('ol');
    await expect(ordered).toHaveAttribute('start', '3');
    await expect(ordered.locator('> li')).toHaveCount(2);
    await expect(ordered.locator('li > ul > li')).toHaveText('Test');

    await page.request.delete(`/api/pagebuilder/pages/${id}`, { headers });
  });
  test('a blank Social image falls back to the first Image block, sent absolute', async ({
    page,
  }) => {
    const slug = uniqueSlug('og-fallback');
    const headers = await moduleCsrfHeader(page, '/pagebuilder/');
    const created = await page.request.post('/api/pagebuilder/pages', {
      headers,
      data: {
        title: `Gallery ${slug}`,
        slug,
        draft_data: {
          root: { props: {} },
          content: [
            { type: 'Heading', props: { id: 'h', text: 'Gallery', level: 'h1', align: 'left' } },
            { type: 'Image', props: { id: 'i', src: '/media/og-first.png', alt: 'First' } },
            { type: 'Image', props: { id: 'j', src: '/media/og-second.png', alt: 'Second' } },
          ],
          zones: {},
        },
      },
    });
    expect(created.status(), await created.text()).toBe(201);
    const { id } = await created.json();
    const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, { headers });
    expect(published.ok(), await published.text()).toBe(true);

    try {
      await page.goto(`/p/${slug}`);
      const ogImage = page.locator('meta[property="og:image"]');
      await expect(ogImage).toHaveAttribute('content', /^https?:\/\/[^/]+\/media\/og-first\.png$/);
      await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute(
        'content',
        'summary_large_image',
      );
    } finally {
      await page.request.delete(`/api/pagebuilder/pages/${id}`, { headers });
    }
  });
});
