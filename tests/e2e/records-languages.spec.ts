import { expect, type Page, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateRecord,
  apiCreateTranslation,
  apiCreateType,
  apiGetType,
  saveType,
  uniqueTypeKey,
} from './records-helpers';

/**
 * The content-i18n surfaces `records-i18n.spec.ts` does not reach: the
 * "Translatable" toggle's refusal, what the locale badge tells an editor,
 * and what the Languages panel says once a language is taken.
 *
 * `start-test-server.sh` configures `sm_records.content_locales` as
 * `["en","de"]`, so "another language" here is German.
 */

async function seedTranslatableType(page: Page, prefix = 'lang'): Promise<string> {
  const key = uniqueTypeKey(prefix);
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

test.describe('Records — languages', () => {
  test('turning "Translatable" off while a German record exists is refused inline', async ({
    page,
  }) => {
    await login(page);
    const key = await seedTranslatableType(page, 'transoff');
    const en = await apiCreateRecord(page, key, { data: { title: 'Hello' } });
    await apiCreateTranslation(page, key, en.uuid, { locale: 'de' });

    await page.goto(`/admin/records/types/${key}`);
    const toggle = page.getByTestId('records-translatable-toggle');
    await expect(toggle).toBeVisible();
    await toggle.click();
    await saveType(page);

    // A 409 carrying none of `useSchemaApply`'s four shapes: `TypeEditor`
    // keeps it and `TypeMetadataForm` renders it next to the toggle, rather
    // than a toast that a screen this long would scroll away from.
    const error = page.getByTestId('records-translatable-error');
    await expect(error).toBeVisible();
    await expect(error).toContainText("holds 1 record(s) in a locale other than 'en'");
    await expect(error).toContainText("is what makes 'translatable' safe to turn off");

    // The type is untouched, so the German record stays reachable.
    expect((await apiGetType(page, key)).translatable).toBe(true);

    // The toggle itself reverts to the saved value as soon as the 409 lands
    // (UX-7) — no reload needed to see it agree with the error underneath.
    await expect(page.getByTestId('records-translatable-toggle')).toBeChecked();
  });

  test('turning "Translatable" off is allowed once no foreign-locale record is left', async ({
    page,
  }) => {
    await login(page);
    const key = await seedTranslatableType(page, 'transok');
    await apiCreateRecord(page, key, { data: { title: 'English only' } });

    await page.goto(`/admin/records/types/${key}`);
    await page.getByTestId('records-translatable-toggle').click();
    await saveType(page);

    await expect(page.getByTestId('records-translatable-error')).toHaveCount(0);
    expect((await apiGetType(page, key)).translatable).toBe(false);
    // And the language UI goes with it.
    await page.goto(`/admin/records/${key}`);
    await expect(page.locator('thead').getByText('Language', { exact: true })).toHaveCount(0);
  });

  test('the editor names the languages a type can be authored in, and fixes each record to one', async ({
    page,
  }) => {
    await login(page);
    const key = await seedTranslatableType(page, 'badge');
    const record = await apiCreateRecord(page, key, { data: { title: 'Hello' } });

    // The toggle's help text names the configured content locales — the
    // list is DB-backed, so the screen is the only place it is visible.
    await page.goto(`/admin/records/types/${key}`);
    await expect(page.getByText(/Records can exist in several languages \(en, de\)/)).toBeVisible();

    await page.goto(`/admin/records/${key}/${record.uuid}`);
    const badge = page.getByTestId('records-locale-badge');
    await expect(badge).toHaveText('English');
    await expect(badge).toHaveAttribute(
      'title',
      "This record's language is fixed for its lifetime.",
    );
    // The same sentence is also visible text, not only a hover tooltip
    // (UX-8) — reachable on touch and by keyboard, not just a mouse.
    await expect(page.getByTestId('records-locale-help')).toHaveText(
      "This record's language is fixed for its lifetime.",
    );
    // Which is why the editor of an existing record offers no language
    // control — only the new-record screen does.
    await expect(page.getByTestId('records-locale-select')).toHaveCount(0);

    await page.goto(`/admin/records/${key}/new`);
    const select = page.getByTestId('records-locale-select');
    await expect(select).toBeVisible();
    await expect(select.locator('option')).toHaveText(['English', 'Deutsch']);
  });

  test('the Languages panel offers "Open" once a language is taken, never a second "Add"', async ({
    page,
  }) => {
    await login(page);
    const key = await seedTranslatableType(page, 'panel');
    const en = await apiCreateRecord(page, key, { data: { title: 'Hello' } });
    const de = await apiCreateTranslation(page, key, en.uuid, { locale: 'de' });

    await page.goto(`/admin/records/${key}/${en.uuid}`);
    const panel = page.getByTestId('records-translations');
    await expect(panel).toBeVisible();
    await expect(page.getByTestId('records-translation-en')).toContainText('Editing');
    // One record per (group, locale): the taken language shows its sibling's
    // title and state and a link, not another "Add translation".
    const german = page.getByTestId('records-translation-de');
    await expect(german).toContainText('Deutsch');
    await expect(german).toContainText('Draft');
    await expect(page.getByTestId('records-translation-add-de')).toHaveCount(0);

    await page.getByTestId('records-translation-open-de').click();
    await expect(page).toHaveURL(new RegExp(`/admin/records/${key}/${de.uuid}$`));
    await expect(page.getByTestId('records-locale-badge')).toHaveText('Deutsch');
    // And back the other way, so the group is navigable from either side.
    await expect(page.getByTestId('records-translation-open-en')).toBeVisible();
  });

  test('a failed "Add" refetches the panel so a language taken meanwhile shows "Open"', async ({
    page,
  }) => {
    await login(page);
    const key = await seedTranslatableType(page, 'panelrace');
    const en = await apiCreateRecord(page, key, { data: { title: 'Hello' } });

    await page.goto(`/admin/records/${key}/${en.uuid}`);
    await expect(page.getByTestId('records-translation-add-de')).toBeVisible();

    // Simulate another tab winning the race: by the time this request is
    // answered, the sibling really exists.
    await page.route(
      `**/api/records/types/${key}/records/${en.uuid}/translations`,
      async (route) => {
        await apiCreateTranslation(page, key, en.uuid, { locale: 'de' });
        await route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({ detail: "a 'de' translation already exists for this record" }),
        });
      },
    );

    await page.getByTestId('records-translation-add-de').click();
    await expect(page.getByTestId('records-translations-error')).toBeVisible();
    // The panel refetches (UX-9) rather than keep offering "Add" for a
    // language that now exists.
    await expect(page.getByTestId('records-translation-add-de')).toHaveCount(0);
    await expect(page.getByTestId('records-translation-open-de')).toBeVisible();
  });
});
