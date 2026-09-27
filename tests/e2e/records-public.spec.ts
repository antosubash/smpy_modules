import { expect, request, test } from '@playwright/test';

import { login } from './helpers';
import { apiCreateRecord, seedTextType, uniqueTypeKey } from './records-helpers';

/**
 * The anonymous read API (design §10): `is_public` on a Record Type serves
 * its published records under `public_route_prefix` (default
 * `/api/records/public`) to a caller with no session at all, in a shape
 * stripped of audit columns — and the TypeEditor's own affordance for it.
 *
 * Every read here goes through a *fresh* `request.newContext()` rather than
 * `page.request` — the admin `page` used to seed the fixtures carries a
 * session cookie, and the point under test is that these routes answer with
 * none at all.
 */

// `locale`/`translations` joined the public shape with content i18n (design
// §4.4) — every record has a locale, and `translations` lists its published
// siblings (empty for a record with none, as here).
const PUBLIC_SHAPE = [
  'data',
  'display_title',
  'locale',
  'published_at',
  'slug',
  'translations',
  'uuid',
].sort();

test.describe('Records — public read API', () => {
  test("serves a public type's list and one record, in the public shape, with no session", async ({
    page,
    baseURL,
  }) => {
    await login(page);
    const key = await seedTextType(page, 'pub', { label: 'Public thing', is_public: true });
    const record = await apiCreateRecord(page, key, {
      data: { title: 'Hello' },
      status: 'published',
    });

    const anon = await request.newContext();
    try {
      const listed = await anon.get(`${baseURL}/api/records/public/${key}`);
      expect(listed.status()).toBe(200);
      const listedBody = await listed.json();
      expect(listedBody.total).toBe(1);
      expect(Object.keys(listedBody.items[0]).sort()).toEqual(PUBLIC_SHAPE);
      expect(listedBody.items[0].display_title).toBe('Hello');

      const one = await anon.get(`${baseURL}/api/records/public/${key}/${record.uuid}`);
      expect(one.status()).toBe(200);
      const oneBody = await one.json();
      expect(Object.keys(oneBody).sort()).toEqual(PUBLIC_SHAPE);
      expect(oneBody.display_title).toBe('Hello');
      expect(oneBody.data).toEqual({ title: 'Hello' });
      expect(oneBody.locale).toBe('en');
      // A published record's own group includes itself (Phase 5 §4.4's
      // "the record itself is included" rule applies here too — there is no
      // other member of this record's group).
      expect(oneBody.translations).toEqual([
        { locale: 'en', uuid: record.uuid, slug: record.slug },
      ]);
      // Removed from the shape, not merely absent by accident — the audit
      // trail, `status`/`version`/`invalid` and `expanded` are all admin-only.
      for (const auditKey of [
        'version',
        'status',
        'invalid',
        'created_by',
        'updated_by',
        'created_at',
        'updated_at',
        'is_deleted',
        'expanded',
        'schema_version',
        'schema_stale',
        'position',
      ]) {
        expect(oneBody).not.toHaveProperty(auditKey);
      }

      // No session was ever attached to this context.
      expect(one.headers()['set-cookie']).toBeUndefined();
    } finally {
      await anon.dispose();
    }
  });

  test('a private type and a draft record both answer 404, anonymously', async ({
    page,
    baseURL,
  }) => {
    await login(page);
    const publicKey = await seedTextType(page, 'pub', { label: 'Public thing', is_public: true });
    const draft = await apiCreateRecord(page, publicKey, {
      data: { title: 'WIP' },
      status: 'draft',
    });

    const privateKey = await seedTextType(page, 'priv', {
      label: 'Private thing',
      is_public: false,
    });
    const privateRecord = await apiCreateRecord(page, privateKey, {
      data: { title: 'Secret' },
      status: 'published',
    });

    const anon = await request.newContext();
    try {
      expect((await anon.get(`${baseURL}/api/records/public/${privateKey}`)).status()).toBe(404);
      expect(
        (
          await anon.get(`${baseURL}/api/records/public/${privateKey}/${privateRecord.uuid}`)
        ).status(),
      ).toBe(404);
      expect(
        (await anon.get(`${baseURL}/api/records/public/${publicKey}/${draft.uuid}`)).status(),
      ).toBe(404);
      // Not-yet-invented type key: indistinguishable from a private one.
      expect(
        (await anon.get(`${baseURL}/api/records/public/${uniqueTypeKey('missing')}`)).status(),
      ).toBe(404);
    } finally {
      await anon.dispose();
    }
  });

  test('the TypeEditor shows the public URL once "Public" is on', async ({ page }) => {
    await login(page);
    const key = await seedTextType(page, 'pub', { label: 'Public thing', is_public: true });

    await page.goto(`/admin/records/types/${key}`);
    const codeLine = page.getByTestId('records-public-url');
    await expect(codeLine).toBeVisible();
    await expect(codeLine).toContainText(`/api/records/public/${key}`);

    // Off by default for a type that isn't public — no stale URL left showing.
    const privateKey = await seedTextType(page, 'priv', {
      label: 'Private thing',
      is_public: false,
    });
    await page.goto(`/admin/records/types/${privateKey}`);
    await expect(page.getByTestId('records-public-url')).toHaveCount(0);
  });
});
