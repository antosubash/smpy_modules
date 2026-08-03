import { expect, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';

/**
 * Coverage for the widget set ported from IIASA.GeoWiki's Global Canopy Atlas.
 *
 * The existing specs only exercise the six original blocks, so a broken widget
 * — or a broken split of one — showed up as a green suite and a blank page.
 * These build a page out of the ported widgets through the API and assert what
 * actually reaches the DOM at /p/{slug}.
 */

/** Every ported widget, by the `label` Puck shows in its palette. */
const WIDGET_LABELS = [
  'Page header',
  'Hero',
  'Eyebrow + heading + body',
  'Media object (image + body + link)',
  'Call to action',
  'Feature cards (linked grid)',
  'FAQ',
  'Statistics',
  'Article cards (image-top, with category & date)',
  'Contact Cards',
  'Contact form',
  'Logo cloud (partners / funders)',
  'Tags (pill row)',
  'Divider',
] as const;

test.describe('Ported GCA widgets', () => {
  test('every ported widget is offered in the editor', async ({ page }) => {
    await login(page);
    await page.goto('/pagebuilder/new');

    // The three categories the ported widgets are filed under.
    for (const category of ['Sections', 'Collections', 'Forms']) {
      await expect(page.getByText(category, { exact: true }).first()).toBeVisible();
    }

    // Assert the palette *offers* each widget. Puck collapses categories by
    // default, so the entries are attached but not in the layout until the
    // author expands one — that's its UI state, not what this test is about.
    for (const label of WIDGET_LABELS) {
      await expect(
        page.locator('[class*="DrawerItem-name"]').filter({ hasText: label }).first(),
        `"${label}" should be registered in the component palette`,
      ).toBeAttached();
    }
  });

  test('a page built from the ported widgets renders publicly', async ({ page }) => {
    await login(page);
    const slug = uniqueSlug();

    const content = [
      {
        type: 'PageHeader',
        props: { id: 'ph', title: 'Widget coverage', subtitle: 'Every ported section.' },
      },
      {
        type: 'EyebrowSection',
        props: {
          id: 'es',
          eyebrow: 'Coverage',
          heading: 'Sections render',
          body: 'Body copy for the eyebrow section.',
        },
      },
      {
        type: 'Stats',
        props: {
          id: 'st',
          title: 'By the numbers',
          items: [
            { value: '3,458', label: 'ALS acquisitions' },
            { value: '87%', label: 'Open-access data' },
          ],
        },
      },
      {
        type: 'Faq',
        props: {
          id: 'fq',
          eyebrow: '',
          title: 'Questions',
          variant: 'divider',
          items: [{ question: 'Does the accordion render?', answer: 'It does.' }],
        },
      },
      { type: 'Divider', props: { id: 'dv' } },
      {
        type: 'Tags',
        props: { id: 'tg', label: 'Topics', items: [{ label: 'canopy', href: '#canopy' }] },
      },
    ];

    const created = await page.request.post('/api/pagebuilder/pages', {
      headers: await csrfHeader(page),
      data: {
        title: 'Widget coverage',
        slug,
        draft_data: {
          root: { props: { title: 'Widget coverage', width: 'full' } },
          content,
          zones: {},
        },
      },
    });
    expect(created.ok()).toBeTruthy();
    const { id } = await created.json();

    const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
      headers: await csrfHeader(page),
      data: { note: 'widget coverage' },
    });
    expect(published.ok()).toBeTruthy();

    await page.goto(`/p/${slug}`);

    // Each assertion pins one widget's distinctive output.
    await expect(page.getByRole('heading', { name: 'Widget coverage' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Sections render' })).toBeVisible();
    await expect(page.getByText('3,458')).toBeVisible();
    await expect(page.getByText('ALS acquisitions')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Questions' })).toBeVisible();
    await expect(page.getByText('Does the accordion render?')).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Topics' })).toBeVisible();

    // Exactly one root: the pack is a site-wide branding setting, so
    // PublicPage wraps the whole document and the page root renders none of
    // its own. The body is inside it.
    await expect(page.locator('.gca-root')).toHaveCount(1);
    await expect(page.locator('.gca-root main')).toHaveCount(1);
  });

  test('the FAQ accordion opens', async ({ page }) => {
    await login(page);
    const slug = uniqueSlug();

    const created = await page.request.post('/api/pagebuilder/pages', {
      headers: await csrfHeader(page),
      data: {
        title: 'FAQ behaviour',
        slug,
        draft_data: {
          root: { props: { title: 'FAQ behaviour', width: 'full' } },
          content: [
            {
              type: 'Faq',
              props: {
                id: 'fq',
                eyebrow: '',
                title: 'Help',
                variant: 'divider',
                items: [{ question: 'Can I open this?', answer: 'Yes — the answer is revealed.' }],
              },
            },
          ],
          zones: {},
        },
      },
    });
    const { id } = await created.json();
    await page.request.post(`/api/pagebuilder/pages/${id}/publish`, {
      headers: await csrfHeader(page),
      data: { note: 'faq' },
    });

    await page.goto(`/p/${slug}`);
    const answer = page.getByText('Yes — the answer is revealed.');
    await expect(answer).not.toBeVisible();
    await page.getByText('Can I open this?').click();
    await expect(answer).toBeVisible();
  });
});
