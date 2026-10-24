import { expect, test } from '@playwright/test';

import { login } from './helpers';
import {
  apiCreateRecord,
  apiDeleteType,
  apiGetType,
  type Json,
  recordField,
  saveTypeAndWait,
  seedTextType,
  uniqueTypeKey,
} from './records-helpers';

const FORM_SYSTEM_KEYS = [
  'sm_source_page',
  'sm_source_block',
  'sm_locale',
  'sm_ip_hash',
  'sm_user_agent',
  'sm_consent_text',
  'sm_spam',
  'sm_notified_at',
];

/**
 * "Accept submissions from the website" (#101, part 1): the type editor's card
 * turns a record type into a contact form or a newsletter list, the server
 * appends its locked `sm_*` system fields, and the record editor shows their
 * values read-only. The public endpoints arrive in a later part; this covers
 * the configuration.
 */
test.describe('Records — accepting submissions from the website', () => {
  test('switching it on in the type editor configures a contact form', async ({ page }) => {
    await login(page);
    const key = await seedTextType(page, 'contactsw', { field: 'name' });

    await page.goto(`/admin/records/types/${key}`);
    const card = page.getByTestId('records-public-submissions');
    const enabled = page.locator('#public-submissions-enabled');
    await expect(enabled).not.toBeChecked();

    await enabled.click();
    await expect(enabled).toBeChecked();
    // Advice, not a refusal: nothing narrows who can read the submissions.
    await expect(card.getByText('Anyone with the records.view permission')).toBeVisible();
    await expect(card.getByText('Nobody is notified of new submissions.')).toBeVisible();

    await card.getByRole('checkbox', { name: /Name/ }).click();
    await card.getByLabel('Notify', { exact: true }).fill('team@example.com');
    await expect(card.getByText('Nobody is notified of new submissions.')).toHaveCount(0);
    await saveTypeAndWait(page, key);

    const stored = await apiGetType(page, key);
    const config = stored.public_submissions as Json;
    expect(config.kind).toBe('form');
    expect(config.enabled).toBe(true);
    expect(config.public_fields).toEqual(['name']);
    expect(config.notify_to).toEqual(['team@example.com']);
    expect(stored.fields.map((f) => f.key)).toEqual(['name', ...FORM_SYSTEM_KEYS]);

    await page.reload();
    await expect(page.locator('#public-submissions-enabled')).toBeChecked();
    // The kind is fixed once saved, and every system row is locked.
    await expect(page.locator('#public-submissions-kind')).toBeDisabled();
    const systemRows = page.locator('[data-testid="records-field-row"][data-field-system="true"]');
    await expect(systemRows).toHaveCount(FORM_SYSTEM_KEYS.length);
    await expect(systemRows.first().getByTestId('records-field-system')).toHaveText('System');
    await expect(systemRows.first().getByTestId('records-field-toggle')).toBeDisabled();

    // The record editor leaves the system fields out of the form and shows
    // them in their own read-only panel.
    const record = await apiCreateRecord(page, key, { data: { name: 'Ada' } });
    await page.goto(`/admin/records/${key}/${record.uuid}`);
    await expect(recordField(page, 'name')).toHaveValue('Ada');
    await expect(recordField(page, 'sm_source_page')).toHaveCount(0);
    const details = page.getByTestId('records-submission-details');
    await expect(details).toBeVisible();
    await expect(details.getByText('Source page')).toBeVisible();

    await apiDeleteType(page, key, 1);
  });

  test('a new type starts from the newsletter preset', async ({ page }) => {
    await login(page);
    const key = uniqueTypeKey('newsletter');
    await page.goto('/admin/records/types/new');
    await expect(page.getByRole('heading', { name: 'New type' })).toBeVisible();
    await page.locator('#type-editor-key').fill(key);
    await page.locator('#type-editor-label').fill(`Newsletter ${key}`);

    const presets = page.getByTestId('records-public-submissions-presets');
    await presets.getByRole('button', { name: 'Newsletter list' }).click();
    await expect(page.locator('#public-submissions-enabled')).toBeChecked();
    await expect(page.locator('#public-submissions-kind')).toHaveValue('subscription');
    await expect(page.locator('#public-submissions-double-opt-in')).toBeChecked();

    const created = page.waitForResponse(
      (res) =>
        res.request().method() === 'POST' && new URL(res.url()).pathname === '/api/records/types',
    );
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    expect((await created).status()).toBe(201);
    await expect(page).toHaveURL(new RegExp(`/admin/records/types/${key}$`));

    const stored = await apiGetType(page, key);
    expect((stored.public_submissions as Json).kind).toBe('subscription');
    expect(stored.display_field).toBe('sm_email');
    const email = stored.fields.find((f) => f.key === 'sm_email');
    expect(email?.unique).toBe(true);
    // The preset is gone once the type exists.
    await expect(presets).toHaveCount(0);

    await apiDeleteType(page, key, 0);
  });
});
