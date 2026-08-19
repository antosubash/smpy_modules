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
});
