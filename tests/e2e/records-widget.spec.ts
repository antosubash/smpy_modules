import { expect, type Page, test } from '@playwright/test';

import { csrfHeader, login, uniqueSlug } from './helpers';
import {
  apiCreateRecord,
  apiCreateTranslation,
  apiGetRecord,
  apiUpdateRecord,
  seedTextType,
} from './records-helpers';

/**
 * The `RecordsList` Puck block (design doc §16's deferred "natural
 * integration", with `news`'s `puck-blocks.ts` as the seam copied for it).
 *
 * Block scaffolding goes through the JSON APIs, exactly as
 * `image-block.spec.ts` builds its page content — Puck's drag-and-drop is
 * flaky under Playwright, and nothing here is testing the editor UI itself.
 * What earns a browser test is the thing a unit test can't reach: an
 * anonymous visitor, on the real public page, getting real data back from
 * the anonymous read API.
 */

async function createPublishedPage(
  page: Page,
  title: string,
  slug: string,
  blockProps: Record<string, unknown>,
): Promise<number> {
  const headers = await csrfHeader(page);
  const draftData = {
    root: { props: { title, width: 'full' } },
    content: [
      {
        type: 'RecordsList',
        props: {
          id: 'RecordsList-test',
          typeKey: '',
          fields: [],
          fieldMeta: [],
          typeIsPublic: null,
          filter: '',
          sort: '',
          limit: 10,
          layout: 'list',
          title: '',
          emptyText: '',
          linkTemplate: '',
          apiPrefix: '/api/records/public',
          ...blockProps,
        },
      },
    ],
  };
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers,
    data: { title, slug, draft_data: draftData },
  });
  expect(created.status(), await created.text()).toBe(201);
  const { id } = (await created.json()) as { id: number };
  // The 201 can arrive before the row is committed (the framework commits in
  // the session dependency's exit code, after the response — upstream GH
  // #257), and publishing a page the next request cannot see is a 404.
  await expect
    .poll(async () => (await page.request.get(`/api/pagebuilder/pages/${id}`)).status())
    .toBe(200);
  const published = await page.request.post(`/api/pagebuilder/pages/${id}/publish`, { headers });
  expect(published.status(), await published.text()).toBe(200);
  return id;
}

test.describe('RecordsList widget on a public page', () => {
  test('an anonymous visitor sees the published records of a public type', async ({
    page,
    browser,
  }) => {
    await login(page);
    const key = await seedTextType(page, 'widget', {
      label: 'Widget thing',
      label_plural: 'Widget things',
      is_public: true,
    });
    await apiCreateRecord(page, key, {
      data: { title: 'First public record' },
      status: 'published',
    });
    await apiCreateRecord(page, key, {
      data: { title: 'Second public record' },
      status: 'published',
    });
    // A draft must not show up alongside the published two.
    await apiCreateRecord(page, key, { data: { title: 'Still a draft' }, status: 'draft' });

    const slug = uniqueSlug('records-widget');
    await createPublishedPage(page, `Records widget ${slug}`, slug, {
      typeKey: key,
      typeIsPublic: true,
      title: 'Widget things',
      emptyText: 'Nothing published yet.',
    });

    // Fresh context: no login, no cookie from the admin `page` above.
    const anonContext = await browser.newContext();
    try {
      const anonPage = await anonContext.newPage();
      await anonPage.goto(`/p/${slug}`);
      await expect(anonPage.getByText('First public record')).toBeVisible();
      await expect(anonPage.getByText('Second public record')).toBeVisible();
      await expect(anonPage.getByText('Still a draft')).toHaveCount(0);
    } finally {
      await anonContext.close();
    }
  });

  test('a private type renders the empty state, not its records', async ({ page, browser }) => {
    await login(page);
    const key = await seedTextType(page, 'priv', {
      label: 'Private widget thing',
      is_public: false,
    });
    await apiCreateRecord(page, key, {
      data: { title: 'Should never render publicly' },
      status: 'published',
    });

    const slug = uniqueSlug('records-widget-private');
    await createPublishedPage(page, `Private widget ${slug}`, slug, {
      typeKey: key,
      typeIsPublic: false,
      title: 'Private things',
      emptyText: 'Nothing to show here.',
    });

    const anonContext = await browser.newContext();
    try {
      const anonPage = await anonContext.newPage();
      await anonPage.goto(`/p/${slug}`);
      await expect(anonPage.getByText('Nothing to show here.')).toBeVisible();
      await expect(anonPage.getByText('Should never render publicly')).toHaveCount(0);
      // The "only public types render" hint is editor-only — a visitor on
      // the real public page must never see it.
      await expect(anonPage.getByText('Only public types render on the site.')).toHaveCount(0);
    } finally {
      await anonContext.close();
    }
  });

  test("the block's `locale` prop decides which language a visitor sees", async ({
    page,
    browser,
  }) => {
    await login(page);
    const key = await seedTextType(page, 'wlocale', {
      label: 'Localized widget thing',
      label_plural: 'Localized widget things',
      is_public: true,
      translatable: true,
    });
    const en = await apiCreateRecord(page, key, {
      data: { title: 'English article' },
      status: 'published',
    });
    // The sibling starts as a draft with the source's payload copied, so it
    // is retitled and published before a visitor could see it.
    const de = await apiCreateTranslation(page, key, en.uuid, { locale: 'de' });
    const fetched = await apiGetRecord(page, key, de.uuid);
    await apiUpdateRecord(page, key, de.uuid, fetched.version, {
      data: { title: 'Deutscher Artikel' },
      status: 'published',
    });

    const slug = uniqueSlug('records-widget-de');
    await createPublishedPage(page, `Records widget ${slug}`, slug, {
      typeKey: key,
      typeIsPublic: true,
      locale: 'de',
      title: 'Auf Deutsch',
      emptyText: 'Nothing published yet.',
    });

    const anonContext = await browser.newContext();
    try {
      const anonPage = await anonContext.newPage();
      await anonPage.goto(`/p/${slug}`);
      await expect(anonPage.getByText('Deutscher Artikel')).toBeVisible();
      // `?locale=` is a filter, not a fallback: the English sibling is a
      // different record and never stands in for the German one (§4.4).
      await expect(anonPage.getByText('English article')).toHaveCount(0);
    } finally {
      await anonContext.close();
    }
  });
});
