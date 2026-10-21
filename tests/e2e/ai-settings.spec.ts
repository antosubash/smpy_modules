import { expect, test } from '@playwright/test';

import { login } from './helpers';

/**
 * The AI settings page is the module's whole UI surface, so these specs pin
 * the full loop: load → edit → save → persisted read-back, the
 * never-echo-the-key contract, and the test-connection button's failure path
 * (127.0.0.1:1 refuses connections instantly — deterministic, no stubs, and
 * no live provider is ever called in CI).
 */

test.describe('AI settings', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/ai/');
    await expect(page.getByRole('heading', { name: 'AI' })).toBeVisible();
  });

  test('page loads with both slot cards', async ({ page }) => {
    await expect(page.getByText('Chat', { exact: true })).toBeVisible();
    await expect(page.getByText('Embeddings', { exact: true })).toBeVisible();
    await expect(page.locator('#ai-chat-provider')).toBeVisible();
    await expect(page.locator('#ai-embedding-provider')).toBeVisible();
  });

  test('saving the chat model persists across reload', async ({ page }) => {
    // Unique per run: with reuseExistingServer the DB survives between local
    // runs, and re-asserting a value a previous run already persisted would
    // pass even if this run's save silently failed.
    const model = `claude-sonnet-5-${Date.now()}`;
    await page.locator('#ai-chat-model').fill(model);
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('AI settings saved')).toBeVisible();
    await page.reload();
    await expect(page.locator('#ai-chat-model')).toHaveValue(model);
  });

  test('saved key is masked, never echoed', async ({ page }) => {
    await page.locator('#ai-chat-key').fill('sk-e2e-secret');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('AI settings saved')).toBeVisible();
    await page.reload();
    await expect(page.locator('#ai-chat-key')).toHaveValue('');
    await expect(page.locator('#ai-chat-key')).toHaveAttribute(
      'placeholder',
      /leave blank to keep/,
    );
  });

  test('test connection surfaces an unreachable endpoint as an inline error', async ({ page }) => {
    await page.locator('#ai-chat-provider').selectOption('openai_compatible');
    await page.locator('#ai-chat-model').fill('some-model');
    await page.locator('#ai-chat-url').fill('http://127.0.0.1:1/v1');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('AI settings saved')).toBeVisible();
    await page.getByRole('button', { name: 'Test connection' }).first().click();
    await expect(page.getByTestId('ai-chat-test-result')).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId('ai-chat-test-result')).not.toContainText('OK —');
  });

  test('load models reports an unreachable endpoint inline', async ({ page }) => {
    await page.locator('#ai-chat-provider').selectOption('openai_compatible');
    await page.locator('#ai-chat-model').fill('some-model');
    await page.locator('#ai-chat-url').fill('http://127.0.0.1:1/v1');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('AI settings saved')).toBeVisible();
    await page.getByRole('button', { name: 'Load models' }).first().click();
    const result = page.getByTestId('ai-chat-models-result');
    await expect(result).toBeVisible({ timeout: 45_000 });
    await expect(result).not.toContainText('Models found');
    // A failed listing offers no suggestions; the field stays free text.
    await expect(page.locator('#ai-chat-model')).not.toHaveAttribute('list', /.+/);
  });

  test('openai_compatible without a base URL is flagged and not saved (#164)', async ({ page }) => {
    const url = page.locator('#ai-embedding-url');
    await page.locator('#ai-embedding-provider').selectOption('openai_compatible');
    await url.fill('   ');
    await expect(url).toHaveAttribute('aria-invalid', 'true');
    await expect(page.locator('#ai-embedding-url-error')).toContainText('no default endpoint');

    let puts = 0;
    page.on('request', (r) => {
      if (r.method() === 'PUT' && r.url().includes('/api/ai/settings')) puts += 1;
    });
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText(/Save failed/)).toBeVisible();
    expect(puts).toBe(0);

    await url.fill('http://127.0.0.1:1/v1');
    await expect(url).toHaveAttribute('aria-invalid', 'false');
    await expect(page.locator('#ai-embedding-url-error')).toHaveCount(0);
  });

  test('the generic Settings screen links to /ai/ instead of editing it (#164)', async ({
    page,
  }) => {
    await page.goto('/admin/settings/');
    await page.getByRole('button', { name: /sm_ai/ }).click();
    await expect(page.getByText('Managed on its own page')).toBeVisible();
    await page.getByRole('link', { name: /Open Ai settings/ }).click();
    await expect(page).toHaveURL(/\/ai\/$/);
  });
});
