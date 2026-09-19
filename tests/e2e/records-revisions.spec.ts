import { expect, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateRecord,
  apiCreateType,
  apiGetRecord,
  apiGetType,
  apiUpdateRecord,
  apiUpdateType,
  expectTypeSaved,
  recordField,
  uniqueTypeKey,
} from './records-helpers';

/**
 * The two history panels: `RecordRevisions` over a record's own versions and
 * `TypeRevisions` over a type's schema snapshots (design §8.6 — a rollback
 * re-enters the same classify-and-dry-run pipeline as any other change).
 */
test.describe('Records — revisions', () => {
  test('restores an earlier version of a record from its history', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('rev');
    await apiCreateType(page, {
      key,
      label: 'Versioned',
      fields: [{ key: 'title', type: 'text', label: 'Title', indexed: true }],
      display_field: 'title',
    });
    const created = await apiCreateRecord(page, key, { data: { title: 'v1 title' } });
    const second = await apiUpdateRecord(page, key, created.uuid, created.version, {
      data: { title: 'v2 title' },
    });
    await apiUpdateRecord(page, key, created.uuid, second.version, {
      data: { title: 'v3 title' },
    });

    await page.goto(`/admin/records/${key}/${created.uuid}`);
    await expect(page.getByRole('heading', { name: 'v3 title' })).toBeVisible();

    const history = page
      .locator('div')
      .filter({ hasText: /^History/ })
      .last();
    await page.getByRole('button', { name: 'Show' }).click();

    const items = page.getByTestId('records-revision-item');
    await expect(items.first()).toBeVisible();
    expect(await items.count()).toBeGreaterThanOrEqual(2);
    await expect(history).toBeVisible();

    // Open the oldest snapshot read-only before committing to anything.
    const oldest = items.last();
    await oldest.getByRole('button').first().click();
    await expect(oldest.locator('pre')).toContainText('v1 title');

    await oldest.getByRole('button', { name: 'Restore this version' }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Restore this version' }).click();

    await expect
      .poll(async () => (await apiGetRecord(page, key, created.uuid)).data.title)
      .toBe('v1 title');
    await expect(recordField(page, 'title')).toHaveValue('v1 title');
  });

  test('a never-edited record still has its creation snapshot', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('norev');
    await apiCreateType(page, {
      key,
      label: 'Fresh',
      fields: [{ key: 'title', type: 'text', label: 'Title', indexed: true }],
      display_field: 'title',
    });
    const created = await apiCreateRecord(page, key, { data: { title: 'Only' } });

    await page.goto(`/admin/records/${key}/${created.uuid}`);
    await page.getByRole('button', { name: 'Show' }).click();
    const items = page.getByTestId('records-revision-item');
    await expect(items).toHaveCount(1);
    await expect(items.first()).toContainText('create');
    await expect(items.first()).toContainText('Only');
  });

  test('rolls a type back to an earlier schema snapshot', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('screv');
    const created = await apiCreateType(page, {
      key,
      label: 'Schema history',
      label_plural: 'Schema histories',
      fields: [{ key: 'title', type: 'text', label: 'Title', indexed: true }],
      display_field: 'title',
    });
    // Additive: a second field, which the rollback below has to take away.
    await apiUpdateType(page, key, created.version, {
      fields: [
        { key: 'title', type: 'text', label: 'Title', indexed: true },
        { key: 'extra', type: 'text', label: 'Extra' },
      ],
    });

    await page.goto(`/admin/records/types/${key}`);
    await expect(page.getByRole('heading', { name: 'Schema history' })).toBeVisible();
    expect((await apiGetType(page, key)).fields.map((f) => f.key)).toEqual(['title', 'extra']);

    await page.getByRole('button', { name: 'Show' }).filter({ hasNotText: 'Hide' }).first().click();
    const snapshots = page.getByTestId('records-type-revision-item');
    await expect(snapshots.first()).toBeVisible();

    // The oldest snapshot is the one-field schema the type started with.
    await snapshots.last().getByRole('button', { name: 'Restore this schema' }).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Restore this schema' }).click();

    await expect
      .poll(async () => (await apiGetType(page, key)).fields.map((f) => f.key))
      .toEqual(['title']);
    await expectTypeSaved(page);
    await expect(page.getByTestId('records-field-row')).toHaveCount(1);
  });

  test('a rollback that would break records is refused like any other change', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('screvx');
    const created = await apiCreateType(page, {
      key,
      label: 'Strict history',
      fields: [
        { key: 'title', type: 'text', label: 'Title', indexed: true },
        { key: 'rank', type: 'integer', label: 'Rank', required: true },
      ],
      display_field: 'title',
    });
    // Relax the schema, add a record that only the relaxed schema allows,
    // then try to roll back to the strict one.
    await apiUpdateType(page, key, created.version, {
      fields: [
        { key: 'title', type: 'text', label: 'Title', indexed: true },
        { key: 'rank', type: 'integer', label: 'Rank' },
      ],
    });
    await apiCreateRecord(page, key, { data: { title: 'No rank' } });

    await page.goto(`/admin/records/types/${key}`);
    await expect(page.getByRole('heading', { name: 'Strict history' })).toBeVisible();
    await page.getByRole('button', { name: 'Show' }).filter({ hasNotText: 'Hide' }).first().click();

    const snapshots = page.getByTestId('records-type-revision-item');
    await expect(snapshots.first()).toBeVisible();
    await snapshots.last().getByRole('button', { name: 'Restore this schema' }).click();
    const dialog = page.getByRole('alertdialog');
    await dialog.getByRole('button', { name: 'Restore this schema' }).click();

    // Same refusal surface as a hand-typed restrictive edit (§8.6).
    const report = page.getByTestId('records-schema-report');
    await expect(report).toBeVisible();
    await expect(report).toContainText('This change would leave records invalid');
    expect((await apiGetType(page, key)).fields.find((f) => f.key === 'rank')?.required).toBe(
      false,
    );
  });
});
