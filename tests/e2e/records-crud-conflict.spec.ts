import { expect, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateRecord,
  apiCreateType,
  apiGetRecord,
  apiUpdateRecord,
  recordField,
  uniqueTypeKey,
} from './records-helpers';

/**
 * The "Overwrite anyway" branch of the 409 conflict panel (H1) — split out
 * of `records-crud.spec.ts`, which was already near the 300-line cap.
 *
 * Before the fix, a 409 never touched the editor's own `current` state, so
 * pressing Save again after the conflict panel appeared kept sending the
 * stale `expected_version` and 409'd forever; the only way out was
 * "Reload", which discards the person's edit. "Overwrite anyway" is the
 * other half of the promise the panel's own help text makes: keep the
 * edit, resend it stamped with the version the 409 just reported.
 */
test.describe('Records — conflict overwrite', () => {
  test('"Overwrite anyway" keeps the editor\'s own edit and saves against the server\'s version', async ({
    page,
  }) => {
    await login(page);
    const key = uniqueTypeKey('conflict');
    await apiCreateType(page, {
      key,
      label: 'Conflicted',
      fields: [{ key: 'title', type: 'text', label: 'Title', indexed: true }],
      display_field: 'title',
    });
    const record = await apiCreateRecord(page, key, { data: { title: 'Mine' } });

    await page.goto(`/admin/records/${key}/${record.uuid}`);
    await recordField(page, 'title').fill('My edit');

    // Someone else saves between the load and the save.
    const theirs = await apiUpdateRecord(page, key, record.uuid, record.version, {
      data: { title: 'Their edit' },
    });

    await page.getByRole('button', { name: 'Save', exact: true }).click();
    const panel = page.getByTestId('records-conflict-panel');
    await expect(panel).toBeVisible();
    await expect(panel).toContainText('My edit');

    // A plain re-press of Save without "Overwrite anyway" would still carry
    // the stale `expected_version` from before the 409 and 409 again — the
    // overwrite path has to pick up `theirs.version` instead.
    await panel.getByTestId('records-conflict-overwrite').click();
    await expect(panel).toHaveCount(0);
    await expect(page.getByText('Saved', { exact: true })).toBeVisible();

    const stored = await apiGetRecord(page, key, record.uuid);
    expect(stored.data.title).toBe('My edit');
    expect(stored.version).toBe(theirs.version + 1);
    await expect(recordField(page, 'title')).toHaveValue('My edit');
  });
});
