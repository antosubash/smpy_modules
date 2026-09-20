import { expect, request, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateRecord,
  apiCreateTranslation,
  apiCreateType,
  apiGetRecord,
  apiUpdateRecord,
  applyFilter,
  rowTitles,
  uniqueTypeKey,
} from './records-helpers';

/**
 * Content i18n (design §4): a translatable Record Type's records can exist
 * in more than one content locale, each its own record with its own slug in
 * its own locale.
 *
 * `start-test-server.sh` sets `sm_records.content_locales` to `["en","de"]`
 * (and `default_content_locale` to `en`) the same way it does for
 * pagebuilder, so this suite exercises the real multi-locale surface rather
 * than a mocked one.
 */

async function seedTranslatableType(page: import('@playwright/test').Page): Promise<string> {
  const key = uniqueTypeKey('i18n');
  await apiCreateType(page, {
    key,
    label: 'Localized thing',
    label_plural: 'Localized things',
    fields: [{ key: 'title', type: 'text', label: 'Title', indexed: true }],
    display_field: 'title',
    translatable: true,
  });
  return key;
}

test.describe('Records — content i18n', () => {
  test('the Languages panel offers "Add" for the missing locale and creates a draft sibling', async ({
    page,
  }) => {
    await login(page);
    const key = await seedTranslatableType(page);
    const en = await apiCreateRecord(page, key, {
      data: { title: 'Hello' },
      status: 'published',
    });

    await page.goto(`/admin/records/${key}/${en.uuid}`);
    const panel = page.getByTestId('records-translations');
    await expect(panel).toBeVisible();
    await expect(page.getByTestId('records-translation-en')).toContainText('Editing');
    const addDe = page.getByTestId('records-translation-add-de');
    await expect(addDe).toBeVisible();
    await addDe.click();

    // Landed on the new sibling's own editor URL.
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}/[0-9a-f]{32}$`));
    await expect(page).not.toHaveURL(new RegExp(`/${en.uuid}$`));

    await expect(page.getByTestId('records-locale-badge')).toHaveText('Deutsch');
    await expect(page.getByTestId('records-translation-de')).toContainText('Editing');
    await expect(page.getByTestId('records-translation-open-en')).toBeVisible();
    // The sibling starts as a draft with the source's payload copied.
    await expect(page.locator('#record-status')).toHaveValue('draft');
    await expect(page.locator('#record-field-title')).toHaveValue('Hello');
  });

  test('a non-translatable type shows no Languages panel and no locale column', async ({
    page,
  }) => {
    await login(page);
    const key = uniqueTypeKey('mono');
    await apiCreateType(page, {
      key,
      label: 'Monolingual thing',
      fields: [{ key: 'title', type: 'text', label: 'Title', indexed: true }],
      display_field: 'title',
    });
    const record = await apiCreateRecord(page, key, { data: { title: 'Only English' } });

    await page.goto(`/admin/records/${key}/${record.uuid}`);
    await expect(page.getByTestId('records-translations')).toHaveCount(0);
    await expect(page.getByTestId('records-locale-badge')).toHaveCount(0);

    await page.goto(`/admin/records/${key}`);
    await expect(page.locator('thead').getByText('Language', { exact: true })).toHaveCount(0);
    await expect(
      page.locator('#records-filter-field').locator('option', { hasText: 'Language' }),
    ).toHaveCount(0);
  });

  test('the list shows a locale badge per row and the locale filter narrows to one', async ({
    page,
  }) => {
    await login(page);
    const key = await seedTranslatableType(page);
    const en = await apiCreateRecord(page, key, { data: { title: 'English one' } });
    await apiCreateTranslation(page, key, en.uuid, { locale: 'de' });

    await page.goto(`/admin/records/${key}`);
    await expect(page.locator('thead').getByText('Language', { exact: true })).toBeVisible();
    await expect(rowTitles(page)).resolves.toEqual(expect.arrayContaining(['English one']));

    await applyFilter(page, 'locale', 'eq', 'de');
    await expect.poll(() => rowTitles(page)).toEqual(['English one']);
  });

  test('the same slug can exist in both locales', async ({ page }) => {
    await login(page);
    const key = await seedTranslatableType(page);
    // No underscores: an explicit slug is still run through `slugify`, which
    // turns any non `[a-z0-9]` run (including `_`) into a single `-`.
    const slug = `shared-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    const en = await apiCreateRecord(page, key, { data: { title: 'EN' }, slug });
    const de = await apiCreateRecord(page, key, { data: { title: 'DE' }, locale: 'de', slug });
    expect(en.slug).toBe(slug);
    expect(de.slug).toBe(slug);
    expect(en.locale).toBe('en');
    expect(de.locale).toBe('de');
  });

  test('the public JSON lists a sibling under translations only once it is published', async ({
    page,
    baseURL,
  }) => {
    await login(page);
    const key = uniqueTypeKey('pubi18n');
    await apiCreateType(page, {
      key,
      label: 'Public localized thing',
      fields: [{ key: 'title', type: 'text', label: 'Title', indexed: true }],
      display_field: 'title',
      translatable: true,
      is_public: true,
    });
    const en = await apiCreateRecord(page, key, {
      data: { title: 'Hello' },
      status: 'published',
    });
    const de = await apiCreateTranslation(page, key, en.uuid, { locale: 'de' });

    const anon = await request.newContext();
    try {
      // `translations` lists every *published* member of the group, the
      // record asked about included (`services._translations.published_siblings`
      // does not exclude it) — so before `de` is published this is `en` alone.
      const beforePublish = await (
        await anon.get(`${baseURL}/api/records/public/${key}/${en.uuid}`)
      ).json();
      expect(beforePublish.translations).toEqual([{ locale: 'en', uuid: en.uuid, slug: en.slug }]);

      const deData = await apiGetRecord(page, key, de.uuid);
      await apiUpdateRecord(page, key, de.uuid, deData.version, {
        data: deData.data,
        status: 'published',
      });

      const afterPublish = await (
        await anon.get(`${baseURL}/api/records/public/${key}/${en.uuid}`)
      ).json();
      // Ordered by locale ('de' < 'en'), both published now.
      expect(afterPublish.translations).toEqual([
        { locale: 'de', uuid: de.uuid, slug: de.slug },
        { locale: 'en', uuid: en.uuid, slug: en.slug },
      ]);
    } finally {
      await anon.dispose();
    }
  });
});
